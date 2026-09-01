"""Single source of truth for every cross-boundary payload in the pipeline.

See AGENTS.md before changing anything here: the Recommendation schema is emitted by
both the rules engine and the triage agent, gated by the orchestrator, and scored by
the eval harness.
"""

from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field


class Action(StrEnum):
    NO_CHANGE = "no_change"
    ADJUST_UP = "adjust_up"
    ADJUST_DOWN = "adjust_down"
    UPHOLD_DENIAL = "uphold_denial"
    REPROCESS = "reprocess"
    ROUTE_SPECIALIST = "route_specialist"


class Source(StrEnum):
    CLASSIFIER = "classifier"
    RULE = "rule"
    AGENT = "agent"


class Recommendation(BaseModel):
    """What every decision layer emits; what the orchestrator gates on."""

    action: Action
    adjustment_amount: Decimal | None = None
    rationale: str
    confidence: float = Field(ge=0.0, le=1.0)
    favorable_to_provider: bool
    source: Source
    rule_id: str | None = None


class LedgerEvent(BaseModel):
    """One append-only audit row per decision, per layer."""

    request_id: str
    layer: str
    decision: str
    payload_hash: str
