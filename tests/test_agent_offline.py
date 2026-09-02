"""Offline agent tests: real graph, scripted model, no API key."""

import csv
from decimal import Decimal

import pytest
from langchain_core.messages import AIMessage
from starlette.testclient import TestClient

from mocks.servicenow.app import app as servicenow_app
from mocks.unet.app import app as unet_app
from pipeline.agent.graph import run_triage
from pipeline.agent.tools import READ_ONLY_TOOL_NAMES, make_tools
from pipeline.schemas import Action, Source
from tests.scripted_llm import ScriptedChatModel, tool_call


@pytest.fixture()
def clients(monkeypatch):
    monkeypatch.setenv("CLAIMS_CSV", "data/demo/claims.csv")
    with TestClient(unet_app) as unet, TestClient(servicenow_app) as servicenow:
        yield unet, servicenow


def _ambiguous_request():
    with open("data/demo/ground_truth.csv") as f:
        truth = next(r for r in csv.DictReader(f) if r["scenario_id"] == "timely_filing_expired")
    with open("data/demo/rework_requests.csv") as f:
        return next(r for r in csv.DictReader(f) if r["request_id"] == truth["request_id"])


def test_agent_tools_are_read_only_plus_submit(clients):
    unet, servicenow = clients
    tools = make_tools(unet, servicenow, {})
    names = {t.name for t in tools}
    assert names == READ_ONLY_TOOL_NAMES | {"submit_recommendation"}


def test_agent_investigates_then_submits(clients):
    unet, servicenow = clients
    request = _ambiguous_request()
    claim = unet.get(f"/claims/{request['claim_id']}").json()
    llm = ScriptedChatModel(
        script=[
            tool_call("get_provider_history", {"provider_npi": claim["provider_npi"]}),
            tool_call(
                "submit_recommendation",
                {
                    "action": "uphold_denial",
                    "rationale": "Filed past the 90-day limit with no proof of timely submission.",
                    "confidence": 0.9,
                },
                "call_2",
            ),
            AIMessage(content="done"),
        ]
    )
    rec, trace = run_triage(request, claim, unet=unet, servicenow=servicenow, llm=llm)
    assert rec.action == Action.UPHOLD_DENIAL
    assert rec.source == Source.AGENT
    assert rec.favorable_to_provider is False
    assert rec.confidence == 0.9
    # the tool loop actually ran: history tool result is in the trace
    assert any(getattr(m, "name", "") == "get_provider_history" for m in trace)


def test_favorability_derived_from_action_not_model(clients):
    unet, servicenow = clients
    request = _ambiguous_request()
    claim = unet.get(f"/claims/{request['claim_id']}").json()
    llm = ScriptedChatModel(
        script=[
            tool_call(
                "submit_recommendation",
                {"action": "reprocess", "rationale": "proof attached", "confidence": 0.8},
            ),
            AIMessage(content="done"),
        ]
    )
    rec, _ = run_triage(request, claim, unet=unet, servicenow=servicenow, llm=llm)
    assert rec.action == Action.REPROCESS
    assert rec.favorable_to_provider is True  # computed, not model-supplied


def test_fallback_when_model_never_submits(clients):
    unet, servicenow = clients
    request = _ambiguous_request()
    claim = unet.get(f"/claims/{request['claim_id']}").json()
    llm = ScriptedChatModel(script=[AIMessage(content="I am not sure what to do.")])
    rec, _ = run_triage(request, claim, unet=unet, servicenow=servicenow, llm=llm)
    assert rec.action == Action.ROUTE_SPECIALIST
    assert rec.confidence <= 0.3
    assert rec.favorable_to_provider is False


def test_adjustment_without_amount_falls_back(clients):
    unet, servicenow = clients
    request = _ambiguous_request()
    claim = unet.get(f"/claims/{request['claim_id']}").json()
    llm = ScriptedChatModel(
        script=[
            tool_call(
                "submit_recommendation",
                {"action": "adjust_up", "rationale": "underpaid", "confidence": 0.9},
            ),
            AIMessage(content="done"),
        ]
    )
    rec, _ = run_triage(request, claim, unet=unet, servicenow=servicenow, llm=llm)
    assert rec.action == Action.ROUTE_SPECIALIST  # unactionable adjustment -> human


def test_submitted_amount_parsed_as_decimal(clients):
    unet, servicenow = clients
    request = _ambiguous_request()
    claim = unet.get(f"/claims/{request['claim_id']}").json()
    llm = ScriptedChatModel(
        script=[
            tool_call(
                "submit_recommendation",
                {
                    "action": "adjust_up",
                    "adjustment_amount": "41.47",
                    "rationale": "paid below allowed",
                    "confidence": 0.85,
                },
            ),
            AIMessage(content="done"),
        ]
    )
    rec, _ = run_triage(request, claim, unet=unet, servicenow=servicenow, llm=llm)
    assert rec.adjustment_amount == Decimal("41.47")
