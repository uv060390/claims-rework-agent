"""THE safety gate tests — CI hard-fails if an unfavorable outcome can auto-release.

CLAUDE.md hard rule 3: only provider/member-favorable recommendations may skip the
human Approve. The gate recomputes favorability from the action; nothing a layer
writes about itself can change that.
"""

import csv
from decimal import Decimal

import pytest
from langchain_core.messages import AIMessage
from starlette.testclient import TestClient

from mocks.servicenow.app import app as servicenow_app
from mocks.uipath.app import app as uipath_app
from mocks.unet.app import app as unet_app
from pipeline.ledger import Ledger
from pipeline.orchestrator import STP_ACTIONS, Orchestrator, stp_eligible
from pipeline.schemas import Action, Recommendation, Source
from tests.scripted_llm import ScriptedChatModel, tool_call


def _rec(action: Action, favorable: bool) -> Recommendation:
    return Recommendation(
        action=action,
        adjustment_amount=Decimal("10.00") if action.value.startswith("adjust") else None,
        rationale="test",
        confidence=0.99,
        favorable_to_provider=favorable,
        source=Source.AGENT,
    )


@pytest.mark.parametrize("action", list(Action))
def test_only_favorable_actions_are_stp_eligible(action):
    assert stp_eligible(_rec(action, favorable=False)) == (action in STP_ACTIONS)
    assert {Action.ADJUST_UP, Action.REPROCESS} == STP_ACTIONS


@pytest.mark.parametrize(
    "action", [Action.ADJUST_DOWN, Action.UPHOLD_DENIAL, Action.NO_CHANGE, Action.ROUTE_SPECIALIST]
)
def test_gate_ignores_a_lying_favorable_flag(action):
    # even if a layer marks its own output favorable, the gate says no
    assert stp_eligible(_rec(action, favorable=True)) is False


# ------------------------------------------------- orchestrator integration


class _NeverAuto:
    threshold = 0.9

    def predict(self, request, claim, original=None):
        return 0.1, False


class _NoRules:
    def evaluate(self, request, claim, original=None):
        return None


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
        yield unet, servicenow, uipath, Ledger(f"sqlite:///{tmp_path}/ledger.db")


def _request_for(scenario: str) -> dict:
    with open("data/demo/ground_truth.csv") as f:
        truth = next(r for r in csv.DictReader(f) if r["scenario_id"] == scenario)
    with open("data/demo/rework_requests.csv") as f:
        return next(r for r in csv.DictReader(f) if r["request_id"] == truth["request_id"])


def _orchestrator(stack, script) -> Orchestrator:
    unet, servicenow, uipath, ledger = stack
    return Orchestrator(
        unet=unet,
        servicenow=servicenow,
        uipath=uipath,
        ledger=ledger,
        classifier=_NeverAuto(),
        rules=_NoRules(),
        llm=ScriptedChatModel(script=script),
    )


def test_favorable_recommendation_auto_releases_and_executes(stack):
    unet, servicenow, _, ledger = stack
    request = _request_for("auth_denied_in_error")
    orch = _orchestrator(
        stack,
        [
            tool_call(
                "submit_recommendation",
                {"action": "reprocess", "rationale": "auth on file", "confidence": 0.9},
            ),
            AIMessage(content="done"),
        ],
    )
    outcome = orch.process(request)
    assert outcome["stp_released"] is True
    assert outcome["job_status"] == "succeeded"
    ticket = servicenow.get(f"/tickets/{outcome['ticket_id']}").json()
    assert ticket["state"] == "approved"
    claim = unet.get(f"/claims/{request['claim_id']}").json()
    assert claim["status"] == "reprocessed"
    layers = [e["layer"] for e in ledger.for_request(request["request_id"])]
    assert layers == ["intake", "classifier", "agent", "gate", "execute"]


def test_unfavorable_recommendation_waits_for_human(stack):
    _, servicenow, uipath, ledger = stack
    request = _request_for("overpaid_recoupment")
    orch = _orchestrator(
        stack,
        [
            tool_call(
                "submit_recommendation",
                {
                    "action": "adjust_down",
                    "adjustment_amount": "25.00",
                    "rationale": "overpaid vs allowed",
                    "confidence": 0.95,
                },
            ),
            AIMessage(content="done"),
        ],
    )
    outcome = orch.process(request)
    assert outcome["stp_released"] is False
    assert outcome["job_status"] is None
    ticket = servicenow.get(f"/tickets/{outcome['ticket_id']}").json()
    assert ticket["state"] == "pending_approval"  # parked for the analyst
    assert uipath.get("/queues/claims-rework/jobs").json() == []  # nothing executed
    decisions = {e["layer"]: e["decision"] for e in ledger.for_request(request["request_id"])}
    assert decisions["gate"] == "pending_human_approval"


def test_analyst_approval_releases_the_parked_ticket(stack):
    unet, servicenow, _, _ = stack
    request = _request_for("overpaid_recoupment")
    before = Decimal(unet.get(f"/claims/{request['claim_id']}").json()["paid_amount"])
    orch = _orchestrator(
        stack,
        [
            tool_call(
                "submit_recommendation",
                {
                    "action": "adjust_down",
                    "adjustment_amount": "25.00",
                    "rationale": "overpaid vs allowed",
                    "confidence": 0.95,
                },
            ),
            AIMessage(content="done"),
        ],
    )
    outcome = orch.process(request)
    sys_id = outcome["ticket_id"]
    servicenow.post(f"/tickets/{sys_id}/transition", json={"state": "approved", "actor": "analyst"})
    job = orch.release(sys_id)
    assert job["status"] == "succeeded"
    after = Decimal(unet.get(f"/claims/{request['claim_id']}").json()["paid_amount"])
    assert after == before - Decimal("25.00")


def test_classifier_auto_close_never_touches_the_queue(stack):
    _, servicenow, uipath, _ = stack
    unet, _, _, ledger = stack

    class _AlwaysAuto:
        threshold = 0.9

        def predict(self, request, claim, original=None):
            return 0.97, True

    request = _request_for("correct_payment_dispute")
    orch = Orchestrator(
        unet=unet,
        servicenow=servicenow,
        uipath=uipath,
        ledger=ledger,
        classifier=_AlwaysAuto(),
        rules=_NoRules(),
        llm=ScriptedChatModel(script=[AIMessage(content="never called")]),
    )
    outcome = orch.process(request)
    assert outcome["resolved_by"] == "classifier"
    assert outcome["action"] == "no_change"
    assert servicenow.get(f"/tickets/{outcome['ticket_id']}").json()["state"] == "closed"
    assert uipath.get("/queues/claims-rework/jobs").json() == []
