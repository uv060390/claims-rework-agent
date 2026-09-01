"""mock-servicenow — stand-in for the ticketing system.

Tickets carry the rework request through the human side of the pipeline: the
agent posts its recommendation as a work note, the analyst approves or rejects,
and an approval webhook notifies the orchestrator.
"""

import contextlib
import os
from datetime import UTC, datetime

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="mock-servicenow (ticketing system)")

TICKETS: dict[str, dict] = {}
_seq = 0

# state machine: which target states are reachable from each state
TRANSITIONS: dict[str, set[str]] = {
    "new": {"in_review", "pending_approval", "closed"},
    "in_review": {"pending_approval", "closed"},
    "pending_approval": {"approved", "rejected"},
    "approved": {"closed"},
    "rejected": {"in_review", "closed"},
    "closed": set(),
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


class TicketIn(BaseModel):
    request_id: str
    claim_id: str
    short_description: str


class WorkNoteIn(BaseModel):
    note: str
    author: str = "pipeline"


class TransitionIn(BaseModel):
    state: str
    actor: str = "pipeline"


@app.get("/health")
def health():
    return {"status": "ok", "tickets": len(TICKETS)}


@app.post("/tickets", status_code=201)
def create_ticket(ticket: TicketIn):
    global _seq
    _seq += 1
    sys_id = f"TKT-{_seq:06d}"
    record = {
        "sys_id": sys_id,
        **ticket.model_dump(),
        "state": "new",
        "work_notes": [],
        "created_at": _now(),
        "updated_at": _now(),
    }
    TICKETS[sys_id] = record
    return record


@app.get("/tickets/{sys_id}")
def get_ticket(sys_id: str):
    if sys_id not in TICKETS:
        raise HTTPException(404, f"ticket {sys_id} not found")
    return TICKETS[sys_id]


@app.get("/tickets")
def list_tickets(state: str | None = None):
    tickets = list(TICKETS.values())
    if state:
        tickets = [t for t in tickets if t["state"] == state]
    return tickets


@app.post("/tickets/{sys_id}/work_notes", status_code=201)
def add_work_note(sys_id: str, work_note: WorkNoteIn):
    ticket = TICKETS.get(sys_id)
    if ticket is None:
        raise HTTPException(404, f"ticket {sys_id} not found")
    entry = {**work_note.model_dump(), "at": _now()}
    ticket["work_notes"].append(entry)
    ticket["updated_at"] = _now()
    return entry


def _fire_webhook(payload: dict) -> None:
    url = os.environ.get("SERVICENOW_WEBHOOK_URL", "")
    if not url:
        return
    # a mock webhook must never take the ticket flow down with it
    with contextlib.suppress(httpx.HTTPError):
        httpx.post(url, json=payload, timeout=5)


@app.post("/tickets/{sys_id}/transition")
def transition(sys_id: str, t: TransitionIn, background: BackgroundTasks):
    ticket = TICKETS.get(sys_id)
    if ticket is None:
        raise HTTPException(404, f"ticket {sys_id} not found")
    if t.state not in TRANSITIONS[ticket["state"]]:
        raise HTTPException(409, f"cannot transition {ticket['state']} -> {t.state}")
    ticket["state"] = t.state
    ticket["updated_at"] = _now()
    if t.state == "approved":
        background.add_task(
            _fire_webhook,
            {
                "event": "ticket.approved",
                "sys_id": sys_id,
                "actor": t.actor,
                "request_id": ticket["request_id"],
                "claim_id": ticket["claim_id"],
            },
        )
    return ticket
