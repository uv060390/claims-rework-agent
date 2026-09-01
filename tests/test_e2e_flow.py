"""Phase 2 exit criterion: the full manual flow across all three mocks + ledger.

Plays the role the orchestrator takes over in later phases: create a ticket for a
rework request, post a recommendation, get analyst approval, release to the RPA
queue, watch it execute against the claims platform, and reconstruct the entire
story from the audit ledger alone.
"""

import csv
from decimal import Decimal

import pytest
from starlette.testclient import TestClient

from mocks.servicenow.app import app as servicenow_app
from mocks.uipath.app import app as uipath_app
from mocks.unet.app import app as unet_app
from pipeline.ledger import Ledger, hash_payload
from pipeline.schemas import LedgerEvent


@pytest.fixture()
def stack(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAIMS_CSV", "data/demo/claims.csv")
    monkeypatch.setenv("FAILURE_RATE", "0")
    monkeypatch.setenv("EXECUTION_LATENCY_SECONDS", "0")
    with (
        TestClient(unet_app) as unet,
        TestClient(servicenow_app) as servicenow,
        TestClient(uipath_app) as uipath,
    ):
        uipath_app.state.unet = unet
        ledger = Ledger(f"sqlite:///{tmp_path}/ledger.db")
        yield unet, servicenow, uipath, ledger


def _an_underpaid_request() -> tuple[str, str, Decimal]:
    """Pick an underpaid_fee_schedule case from the frozen demo dataset."""
    with open("data/demo/ground_truth.csv") as f:
        truth = next(r for r in csv.DictReader(f) if r["scenario_id"] == "underpaid_fee_schedule")
    with open("data/demo/rework_requests.csv") as f:
        request = next(r for r in csv.DictReader(f) if r["request_id"] == truth["request_id"])
    return request["request_id"], request["claim_id"], Decimal(truth["correct_adjustment_amount"])


def test_full_recommend_then_release_flow(stack):
    unet, servicenow, uipath, ledger = stack
    request_id, claim_id, delta = _an_underpaid_request()

    def log(layer: str, decision: str, payload: dict) -> None:
        ledger.append(
            LedgerEvent(
                request_id=request_id,
                layer=layer,
                decision=decision,
                payload_hash=hash_payload(payload),
            )
        )

    # 1. intake: a ticket is opened for the rework request
    ticket = servicenow.post(
        "/tickets",
        json={
            "request_id": request_id,
            "claim_id": claim_id,
            "short_description": "fee schedule underpayment dispute",
        },
    ).json()
    log("intake", "ticket_created", ticket)

    # 2. a recommendation is posted as a work note (hand-built here; the agent's job later)
    recommendation = {
        "action": "adjust_up",
        "amount": str(delta),
        "rationale": "paid below fee schedule allowed amount",
        "favorable_to_provider": True,
    }
    servicenow.post(
        f"/tickets/{ticket['sys_id']}/work_notes",
        json={"note": str(recommendation), "author": "agent"},
    )
    servicenow.post(f"/tickets/{ticket['sys_id']}/transition", json={"state": "pending_approval"})
    log("recommend", "adjust_up", recommendation)

    # 3. analyst approves
    approved = servicenow.post(
        f"/tickets/{ticket['sys_id']}/transition",
        json={"state": "approved", "actor": "analyst"},
    ).json()
    assert approved["state"] == "approved"
    log("approval", "approved_by_analyst", approved)

    # 4. release to the RPA queue, which executes against the claims platform
    before = Decimal(unet.get(f"/claims/{claim_id}").json()["paid_amount"])
    job = uipath.post(
        "/queues/claims-rework/jobs",
        json={
            "ticket_id": ticket["sys_id"],
            "claim_id": claim_id,
            "action": "adjust_up",
            "amount": str(delta),
        },
    ).json()
    final_job = uipath.get(f"/jobs/{job['job_id']}").json()
    assert final_job["status"] == "succeeded"
    log("execute", "job_succeeded", final_job)

    # 5. the claim is actually adjusted in the system of record
    claim = unet.get(f"/claims/{claim_id}").json()
    assert Decimal(claim["paid_amount"]) == before + delta
    assert claim["status"] == "adjusted"

    # 6. the whole story reconstructs from the ledger alone
    trail = ledger.for_request(request_id)
    assert [e["layer"] for e in trail] == ["intake", "recommend", "approval", "execute"]
