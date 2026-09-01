"""mock-unet — stand-in for the claims adjudication platform (system of record).

Loads the synthetic claims CSV at startup and exposes the read/adjust API the
pipeline and the RPA queue use. In-memory state is fine for a mock: restart = reset.
"""

import csv
import os
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from pipeline.datagen.codes import BH_SERVICES
from pipeline.schemas import Action

CLAIMS: dict[str, dict] = {}
ADJUSTMENTS: dict[str, dict] = {}
_adj_seq = 0


def load_claims(path: Path) -> None:
    CLAIMS.clear()
    with path.open() as f:
        for row in csv.DictReader(f):
            CLAIMS[row["claim_id"]] = row


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_claims(Path(os.environ.get("CLAIMS_CSV", "data/demo/claims.csv")))
    yield


app = FastAPI(title="mock-unet (claims adjudication platform)", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok", "claims_loaded": len(CLAIMS)}


@app.get("/claims/{claim_id}")
def get_claim(claim_id: str):
    claim = CLAIMS.get(claim_id)
    if claim is None:
        raise HTTPException(404, f"claim {claim_id} not found")
    return claim


@app.get("/providers/{npi}/claims")
def provider_history(npi: str):
    return [c for c in CLAIMS.values() if c["provider_npi"] == npi]


@app.get("/fee-schedule/{cpt_code}")
def fee_schedule(cpt_code: str):
    if cpt_code not in BH_SERVICES:
        raise HTTPException(404, f"CPT {cpt_code} not on fee schedule")
    description, allowed = BH_SERVICES[cpt_code]
    return {"cpt_code": cpt_code, "description": description, "allowed_amount": str(allowed)}


class AdjustmentIn(BaseModel):
    action: Action
    amount: str | None = None  # decimal string
    source_ticket: str = ""


@app.post("/claims/{claim_id}/adjustments", status_code=201)
def post_adjustment(claim_id: str, adj: AdjustmentIn):
    global _adj_seq
    claim = CLAIMS.get(claim_id)
    if claim is None:
        raise HTTPException(404, f"claim {claim_id} not found")

    paid = Decimal(claim["paid_amount"])
    if adj.action in (Action.ADJUST_UP, Action.ADJUST_DOWN):
        if adj.amount is None:
            raise HTTPException(422, f"{adj.action} requires an amount")
        delta = Decimal(adj.amount)
        if delta <= 0:
            raise HTTPException(422, "amount must be positive")
        if adj.action == Action.ADJUST_UP:
            claim["paid_amount"] = str(paid + delta)
        else:
            if delta > paid:
                raise HTTPException(409, "cannot recoup more than was paid")
            claim["paid_amount"] = str(paid - delta)
        claim["status"] = "adjusted"
    elif adj.action == Action.REPROCESS:
        claim["paid_amount"] = claim["allowed_amount"]
        claim["status"] = "reprocessed"
        claim["denial_carc"] = ""
    # no_change / uphold_denial / route_specialist: recorded, no state change

    _adj_seq += 1
    record = {
        "adjustment_id": f"ADJ-{_adj_seq:06d}",
        "claim_id": claim_id,
        "action": adj.action.value,
        "amount": adj.amount,
        "source_ticket": adj.source_ticket,
        "resulting_status": claim["status"],
        "resulting_paid_amount": claim["paid_amount"],
    }
    ADJUSTMENTS[record["adjustment_id"]] = record
    return record
