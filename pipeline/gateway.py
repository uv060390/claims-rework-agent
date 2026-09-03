"""API gateway for the analyst dashboard.

Thin read/act layer over the mocks + ledger + orchestrator: the dashboard never
talks to the enterprise systems directly. Approve/Reject land here; approval
releases the parked recommendation through the orchestrator (same code path as
STP — one release implementation, two triggers).

Run locally (mocks must be up, e.g. `docker compose up`):
    uv run uvicorn pipeline.gateway:app --port 8000
"""

import json
import os
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from pipeline import config
from pipeline.ledger import Ledger
from pipeline.orchestrator import Orchestrator


def build_app(*, unet=None, servicenow=None, uipath=None, ledger=None, orchestrator=None):
    """Clients injectable for tests/snapshot generation; real HTTP clients by default."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.unet = unet or httpx.Client(base_url=config.UNET_URL, timeout=10)
        app.state.servicenow = servicenow or httpx.Client(
            base_url=config.SERVICENOW_URL, timeout=10
        )
        app.state.uipath = uipath or httpx.Client(base_url=config.UIPATH_URL, timeout=10)
        app.state.ledger = ledger or Ledger()
        app.state.orchestrator = orchestrator or Orchestrator(
            unet=app.state.unet,
            servicenow=app.state.servicenow,
            uipath=app.state.uipath,
            ledger=app.state.ledger,
        )
        yield

    app = FastAPI(title="claims-rework gateway", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=os.environ.get("DASHBOARD_ORIGINS", "http://localhost:3000").split(","),
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def _ticket_view(app_state, ticket: dict) -> dict:
        claim_resp = app_state.unet.get(f"/claims/{ticket['claim_id']}")
        recommendation = None
        for note in reversed(ticket["work_notes"]):
            try:
                recommendation = json.loads(note["note"])
                break
            except (json.JSONDecodeError, TypeError):
                continue
        job = None
        for j in app_state.uipath.get("/queues/claims-rework/jobs").json():
            if j["ticket_id"] == ticket["sys_id"]:
                job = j
        return {
            **ticket,
            "claim": claim_resp.json() if claim_resp.status_code == 200 else None,
            "recommendation": recommendation,
            "ledger": [
                {"layer": e["layer"], "decision": e["decision"], "at": str(e["created_at"])}
                for e in app_state.ledger.for_request(ticket["request_id"])
            ],
            "job": job,
        }

    @app.get("/api/queue")
    def queue(state: str = "pending_approval"):
        tickets = app.state.servicenow.get("/tickets", params={"state": state}).json()
        return [_ticket_view(app.state, t) for t in tickets]

    @app.get("/api/tickets/{sys_id}")
    def ticket_detail(sys_id: str):
        resp = app.state.servicenow.get(f"/tickets/{sys_id}")
        if resp.status_code != 200:
            raise HTTPException(404, f"ticket {sys_id} not found")
        return _ticket_view(app.state, resp.json())

    class Decision(BaseModel):
        actor: str = "analyst"

    @app.post("/api/tickets/{sys_id}/approve")
    def approve(sys_id: str, decision: Decision):
        resp = app.state.servicenow.post(
            f"/tickets/{sys_id}/transition", json={"state": "approved", "actor": decision.actor}
        )
        if resp.status_code != 200:
            raise HTTPException(resp.status_code, resp.json().get("detail", "transition failed"))
        job = app.state.orchestrator.release(sys_id)
        return {"ticket": ticket_detail(sys_id), "job": job}

    @app.post("/api/tickets/{sys_id}/reject")
    def reject(sys_id: str, decision: Decision):
        resp = app.state.servicenow.post(
            f"/tickets/{sys_id}/transition", json={"state": "rejected", "actor": decision.actor}
        )
        if resp.status_code != 200:
            raise HTTPException(resp.status_code, resp.json().get("detail", "transition failed"))
        return ticket_detail(sys_id)

    @app.get("/api/metrics")
    def metrics():
        tickets = app.state.servicenow.get("/tickets").json()
        views = [_ticket_view(app.state, t) for t in tickets]
        by_source: dict[str, int] = {}
        stp = executed = 0
        for v in views:
            rec = v["recommendation"] or {}
            by_source[rec.get("source", "unknown")] = (
                by_source.get(rec.get("source", "unknown"), 0) + 1
            )
            decisions = {e["layer"]: e["decision"] for e in v["ledger"]}
            if decisions.get("gate") == "stp_released":
                stp += 1
            if v["job"] and v["job"]["status"] == "succeeded":
                executed += 1
        states: dict[str, int] = {}
        for t in tickets:
            states[t["state"]] = states.get(t["state"], 0) + 1
        return {
            "total": len(tickets),
            "by_source": by_source,
            "by_state": states,
            "stp_released": stp,
            "jobs_succeeded": executed,
        }

    @app.post("/api/batch")
    def batch(n: int = 25):
        """Process the next n unprocessed demo requests through the pipeline."""
        import csv

        processed = {t["request_id"] for t in app.state.servicenow.get("/tickets").json()}
        outcomes = []
        with open("data/demo/rework_requests.csv") as f:
            for request in csv.DictReader(f):
                if len(outcomes) >= n:
                    break
                if request["request_id"] in processed:
                    continue
                outcomes.append(app.state.orchestrator.process(request))
        return outcomes

    return app


app = build_app()
