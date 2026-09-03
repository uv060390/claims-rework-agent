"""Gateway integration tests: queue, detail, approve->execute, metrics."""

import pytest
from langchain_core.messages import AIMessage
from starlette.testclient import TestClient

from mocks.servicenow.app import app as servicenow_app
from mocks.uipath.app import app as uipath_app
from mocks.unet.app import app as unet_app
from pipeline.gateway import build_app
from pipeline.ledger import Ledger
from pipeline.orchestrator import Orchestrator
from tests.scripted_llm import ScriptedChatModel, tool_call
from tests.test_stp_gate import _NeverAuto, _NoRules, _request_for


@pytest.fixture()
def gateway(tmp_path, monkeypatch):
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
        orch = Orchestrator(
            unet=unet,
            servicenow=servicenow,
            uipath=uipath,
            ledger=ledger,
            classifier=_NeverAuto(),
            rules=_NoRules(),
            llm=ScriptedChatModel(
                script=[
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
                ]
            ),
        )
        app = build_app(
            unet=unet, servicenow=servicenow, uipath=uipath, ledger=ledger, orchestrator=orch
        )
        with TestClient(app) as client:
            yield client, orch


def test_queue_detail_approve_flow(gateway):
    client, orch = gateway
    request = _request_for("overpaid_recoupment")
    orch.process(request)

    queue = client.get("/api/queue").json()
    assert len(queue) == 1
    view = queue[0]
    assert view["recommendation"]["action"] == "adjust_down"
    assert view["claim"]["claim_id"] == request["claim_id"]
    assert [e["layer"] for e in view["ledger"]][:2] == ["intake", "classifier"]

    sys_id = view["sys_id"]
    detail = client.get(f"/api/tickets/{sys_id}").json()
    assert detail["state"] == "pending_approval"

    result = client.post(f"/api/tickets/{sys_id}/approve", json={"actor": "analyst"}).json()
    assert result["job"]["status"] == "succeeded"
    assert client.get("/api/queue").json() == []

    metrics = client.get("/api/metrics").json()
    assert metrics["total"] == 1
    assert metrics["jobs_succeeded"] == 1
    assert metrics["by_source"] == {"agent": 1}


def test_reject_leaves_queue_without_execution(gateway):
    client, orch = gateway
    orch.process(_request_for("overpaid_recoupment"))
    sys_id = client.get("/api/queue").json()[0]["sys_id"]
    rejected = client.post(f"/api/tickets/{sys_id}/reject", json={"actor": "analyst"}).json()
    assert rejected["state"] == "rejected"
    assert rejected["job"] is None
    assert client.get("/api/metrics").json()["jobs_succeeded"] == 0


def test_missing_ticket_404s(gateway):
    client, _ = gateway
    assert client.get("/api/tickets/TKT-999999").status_code == 404
