"""Feature engineering for the No-Adjustment-Needed classifier.

Features are built ONLY from what the pipeline can legitimately see at inference
time: the rework request row, the disputed claim, and (when the claim references
one) the original claim. Never the free-text note, never anything label-derived.
The same function serves training (from CSVs) and online inference.
"""

from datetime import date

from pipeline.datagen.codes import BH_SERVICES, TIMELY_FILING_DAYS

CARC_VOCAB = ["16", "18", "22", "29", "45", "50", "96", "97", "197"]
STATUS_VOCAB = ["paid", "partial", "denied"]
REQUESTER_VOCAB = ["provider", "internal_audit", "member_advocate"]
CPT_VOCAB = sorted(BH_SERVICES)


def _d(value: str) -> date:
    return date.fromisoformat(value)


def build_features(
    request: dict, claim: dict, original_claim: dict | None = None
) -> dict[str, float]:
    billed = float(claim["billed_amount"])
    allowed = float(claim["allowed_amount"])
    paid = float(claim["paid_amount"])
    submit_lag = (_d(claim["submitted_date"]) - _d(claim["service_date"])).days
    request_lag = (_d(request["received_date"]) - _d(claim["submitted_date"])).days

    features: dict[str, float] = {
        "units": float(claim["units"]),
        "billed_amount": billed,
        "allowed_amount": allowed,
        "paid_amount": paid,
        "allowed_minus_paid": allowed - paid,
        "paid_over_allowed_ratio": paid / allowed if allowed else 0.0,
        "paid_is_zero": float(paid == 0.0),
        "paid_equals_allowed": float(abs(paid - allowed) < 0.005),
        "paid_exceeds_allowed": float(paid - allowed > 0.005),
        "days_service_to_submit": float(submit_lag),
        "over_timely_limit": float(submit_lag > TIMELY_FILING_DAYS),
        "days_submit_to_request": float(request_lag),
        "is_telehealth_pos": float(claim["pos_code"] in ("02", "10")),
        "has_modifier_95": float("95" in claim["modifiers"].split()),
        "resubmission_count": float(request["resubmission_count"]),
        "has_attachment": float(request["has_attachment"] in (True, "True", "true", "1")),
        "has_original_claim": float(bool(claim["original_claim_id"])),
        "original_was_paid": float(
            original_claim is not None and float(original_claim["paid_amount"]) > 0.0
        ),
        "original_was_denied": float(
            original_claim is not None and original_claim["status"] == "denied"
        ),
    }
    for carc in CARC_VOCAB:
        features[f"carc_{carc}"] = float(claim["denial_carc"] == carc)
    for status in STATUS_VOCAB:
        features[f"status_{status}"] = float(claim["status"] == status)
    for requester in REQUESTER_VOCAB:
        features[f"requester_{requester}"] = float(request["requester_type"] == requester)
    for cpt in CPT_VOCAB:
        features[f"cpt_{cpt}"] = float(claim["cpt_code"] == cpt)
    return features


FEATURE_NAMES: list[str] = list(
    build_features(
        {
            "received_date": "2025-06-01",
            "resubmission_count": 0,
            "has_attachment": "False",
            "requester_type": "provider",
        },
        {
            "billed_amount": "100.00",
            "allowed_amount": "100.00",
            "paid_amount": "100.00",
            "units": "1",
            "submitted_date": "2025-05-01",
            "service_date": "2025-04-20",
            "pos_code": "11",
            "modifiers": "",
            "denial_carc": "",
            "status": "paid",
            "cpt_code": "90837",
            "original_claim_id": "",
        },
    )
)
