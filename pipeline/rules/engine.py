"""Deterministic rules engine — layer 2 of the pipeline.

Rules are declarative YAML (rules.yaml): ordered, first-match-wins, each a list
of {field, op, value} conditions over the derived context plus a Recommendation
recipe. The engine emits the same schema the agent uses, with rule provenance.

In production the fee-schedule check would call the pricing service; here it
reads the same static schedule mock-unet serves.
"""

from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from pipeline.datagen.codes import BH_SERVICES
from pipeline.schemas import Action, Recommendation, Source

RULES_PATH = Path(__file__).parent / "rules.yaml"

_OPS = {
    "eq": lambda a, b: a == b,
    "ne": lambda a, b: a != b,
    "gt": lambda a, b: a > b,
    "lt": lambda a, b: a < b,
}


def build_context(request: dict, claim: dict, original_claim: dict | None = None) -> dict[str, Any]:
    """Derived facts the YAML conditions and amount recipes reference."""
    paid = Decimal(claim["paid_amount"])
    allowed = Decimal(claim["allowed_amount"])
    units = int(claim["units"])
    fee = BH_SERVICES.get(claim["cpt_code"])
    same_service = original_claim is not None and (
        original_claim["cpt_code"] == claim["cpt_code"]
        and original_claim["service_date"] == claim["service_date"]
        and original_claim["member_id"] == claim["member_id"]
    )
    return {
        "status": claim["status"],
        "denial_carc": claim["denial_carc"],
        "units": units,
        "requester_type": request["requester_type"],
        "paid_lt_allowed": paid < allowed,
        "paid_gt_allowed": paid > allowed,
        "paid_eq_allowed": paid == allowed,
        "allowed_minus_paid": allowed - paid,
        "paid_minus_allowed": paid - allowed,
        "allowed_matches_fee_schedule": fee is not None and allowed == fee[1] * units,
        "has_original": original_claim is not None,
        "original_was_paid": (
            original_claim is not None and Decimal(original_claim["paid_amount"]) > 0
        ),
        "same_service_as_original": same_service,
    }


class RulesEngine:
    def __init__(self, rules_path: Path = RULES_PATH):
        self.rules: list[dict] = yaml.safe_load(rules_path.read_text())

    def evaluate(
        self, request: dict, claim: dict, original_claim: dict | None = None
    ) -> Recommendation | None:
        """First matching rule's recommendation, or None to fall through to the agent."""
        context = build_context(request, claim, original_claim)
        for rule in self.rules:
            if all(
                _OPS[cond["op"]](context[cond["field"]], cond["value"]) for cond in rule["when"]
            ):
                amount = Decimal(context[rule["amount_from"]]) if "amount_from" in rule else None
                return Recommendation(
                    action=Action(rule["action"]),
                    adjustment_amount=amount,
                    rationale=" ".join(rule["description"].split()),
                    confidence=1.0,
                    favorable_to_provider=rule["favorable_to_provider"],
                    source=Source.RULE,
                    rule_id=rule["id"],
                )
        return None
