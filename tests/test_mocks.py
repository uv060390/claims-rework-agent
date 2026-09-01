"""Contract tests for the three mock enterprise services."""

from decimal import Decimal

import pytest
from starlette.testclient import TestClient

from mocks.servicenow.app import app as servicenow_app
from mocks.uipath.app import JOBS
from mocks.uipath.app import app as uipath_app
from mocks.unet.app import CLAIMS
from mocks.unet.app import app as unet_app


@pytest.fixture()
def unet(monkeypatch):
    monkeypatch.setenv("CLAIMS_CSV", "data/demo/claims.csv")
    with TestClient(unet_app) as client:
        yield client


@pytest.fixture()
def servicenow():
    with TestClient(servicenow_app) as client:
        yield client


@pytest.fixture()
def uipath(unet, monkeypatch):
    monkeypatch.setenv("FAILURE_RATE", "0")
    monkeypatch.setenv("EXECUTION_LATENCY_SECONDS", "0")
    with TestClient(uipath_app) as client:
        uipath_app.state.unet = unet  # route the worker's calls to the in-process mock
        yield client


# ------------------------------------------------------------------ mock-unet


def test_unet_serves_claims_and_history(unet):
    claim_id, claim = next(iter(CLAIMS.items()))
    assert unet.get(f"/claims/{claim_id}").json()["claim_id"] == claim_id
    history = unet.get(f"/providers/{claim['provider_npi']}/claims").json()
    assert any(c["claim_id"] == claim_id for c in history)
    assert unet.get("/claims/CLM-99999999").status_code == 404


def test_unet_fee_schedule(unet):
    body = unet.get("/fee-schedule/90837").json()
    assert body["allowed_amount"] == "141.47"
    assert unet.get("/fee-schedule/99999").status_code == 404


def test_unet_adjust_up_mutates_claim(unet):
    claim_id = next(c["claim_id"] for c in CLAIMS.values() if c["status"] == "partial")
    before = Decimal(unet.get(f"/claims/{claim_id}").json()["paid_amount"])
    resp = unet.post(
        f"/claims/{claim_id}/adjustments",
        json={"action": "adjust_up", "amount": "10.00", "source_ticket": "TKT-1"},
    )
    assert resp.status_code == 201
    after = Decimal(unet.get(f"/claims/{claim_id}").json()["paid_amount"])
    assert after == before + Decimal("10.00")


def test_unet_rejects_bad_adjustments(unet):
    claim_id = next(iter(CLAIMS))
    assert (
        unet.post(f"/claims/{claim_id}/adjustments", json={"action": "adjust_up"}).status_code
        == 422
    )
    assert (
        unet.post(
            f"/claims/{claim_id}/adjustments",
            json={"action": "adjust_down", "amount": "999999.00"},
        ).status_code
        == 409
    )


def test_unet_reprocess_clears_denial(unet):
    claim_id = next(c["claim_id"] for c in CLAIMS.values() if c["status"] == "denied")
    body = unet.post(f"/claims/{claim_id}/adjustments", json={"action": "reprocess"}).json()
    claim = unet.get(f"/claims/{claim_id}").json()
    assert claim["status"] == "reprocessed"
    assert claim["denial_carc"] == ""
    assert claim["paid_amount"] == claim["allowed_amount"]
    assert body["resulting_status"] == "reprocessed"


# ------------------------------------------------------------ mock-servicenow


def test_servicenow_ticket_lifecycle(servicenow):
    ticket = servicenow.post(
        "/tickets",
        json={"request_id": "RWK-1", "claim_id": "CLM-1", "short_description": "test"},
    ).json()
    sys_id = ticket["sys_id"]
    servicenow.post(
        f"/tickets/{sys_id}/work_notes", json={"note": "recommendation", "author": "agent"}
    )
    servicenow.post(f"/tickets/{sys_id}/transition", json={"state": "pending_approval"})
    approved = servicenow.post(
        f"/tickets/{sys_id}/transition", json={"state": "approved", "actor": "analyst"}
    ).json()
    assert approved["state"] == "approved"
    assert len(approved["work_notes"]) == 1


def test_servicenow_rejects_illegal_transition(servicenow):
    ticket = servicenow.post(
        "/tickets",
        json={"request_id": "RWK-2", "claim_id": "CLM-2", "short_description": "test"},
    ).json()
    # cannot approve a ticket that isn't pending approval
    resp = servicenow.post(f"/tickets/{ticket['sys_id']}/transition", json={"state": "approved"})
    assert resp.status_code == 409


# ---------------------------------------------------------------- mock-uipath


def test_uipath_executes_job_against_unet(uipath, unet):
    claim_id = next(c["claim_id"] for c in CLAIMS.values() if c["status"] == "partial")
    job = uipath.post(
        "/queues/claims-rework/jobs",
        json={"ticket_id": "TKT-1", "claim_id": claim_id, "action": "adjust_up", "amount": "5.00"},
    ).json()
    final = uipath.get(f"/jobs/{job['job_id']}").json()
    assert final["status"] == "succeeded"
    assert final["result"]["resulting_status"] == "adjusted"


def test_uipath_retries_then_fails_when_unet_errors(uipath):
    job = uipath.post(
        "/queues/claims-rework/jobs",
        json={"ticket_id": "TKT-1", "claim_id": "CLM-99999999", "action": "reprocess"},
    ).json()
    final = JOBS[job["job_id"]]
    assert final["status"] == "failed"
    assert final["attempts"] == 2
    assert final["last_error"]
