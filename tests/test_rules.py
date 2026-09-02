"""Rules engine tests, including the 100%-precision contract on the golden set."""

import csv
from decimal import Decimal
from pathlib import Path

import pytest

from pipeline.rules.engine import RulesEngine
from pipeline.schemas import Action, Source

DATA = Path("data/demo")


@pytest.fixture(scope="module")
def engine():
    return RulesEngine()


@pytest.fixture(scope="module")
def dataset():
    with (DATA / "claims.csv").open() as f:
        claims = {r["claim_id"]: r for r in csv.DictReader(f)}
    with (DATA / "ground_truth.csv").open() as f:
        truth = {r["request_id"]: r for r in csv.DictReader(f)}
    with (DATA / "rework_requests.csv").open() as f:
        requests = list(csv.DictReader(f))
    return claims, truth, requests


def _resolve(engine, claims, request):
    claim = claims[request["claim_id"]]
    original = claims.get(claim["original_claim_id"]) or None
    return engine.evaluate(request, claim, original)


# ------------------------------------------------------------- unit behavior


def test_underpayment_rule_fires_with_exact_delta(engine):
    request = {"requester_type": "provider"}
    claim = {
        "status": "partial",
        "denial_carc": "",
        "units": "1",
        "cpt_code": "90837",
        "paid_amount": "100.00",
        "allowed_amount": "141.47",
        "billed_amount": "200.00",
        "service_date": "2025-03-01",
        "member_id": "MBR-1",
        "original_claim_id": "",
    }
    rec = engine.evaluate(request, claim)
    assert rec is not None
    assert rec.action == Action.ADJUST_UP
    assert rec.adjustment_amount == Decimal("41.47")
    assert rec.source == Source.RULE and rec.rule_id == "R001_exact_fee_schedule_underpayment"
    assert rec.favorable_to_provider is True


def test_underpayment_rule_skips_multi_unit_claims(engine):
    request = {"requester_type": "provider"}
    claim = {
        "status": "partial",
        "denial_carc": "",
        "units": "2",
        "cpt_code": "90837",
        "paid_amount": "141.47",
        "allowed_amount": "282.94",
        "billed_amount": "400.00",
        "service_date": "2025-03-01",
        "member_id": "MBR-1",
        "original_claim_id": "",
    }
    assert engine.evaluate(request, claim) is None  # documentation question -> agent


def test_unlinked_duplicate_falls_through(engine):
    request = {"requester_type": "provider"}
    claim = {
        "status": "denied",
        "denial_carc": "18",
        "units": "1",
        "cpt_code": "90834",
        "paid_amount": "0.00",
        "allowed_amount": "94.55",
        "billed_amount": "150.00",
        "service_date": "2025-03-01",
        "member_id": "MBR-1",
        "original_claim_id": "",
    }
    assert engine.evaluate(request, claim) is None  # finding the original is agent work


def test_ambiguous_denials_fall_through(engine):
    # timely filing and auth denials must never be rules-resolved: structurally
    # identical cases have opposite ground truth
    request = {"requester_type": "provider"}
    for carc in ("29", "197", "22", "16"):
        claim = {
            "status": "denied",
            "denial_carc": carc,
            "units": "1",
            "cpt_code": "90834",
            "paid_amount": "0.00",
            "allowed_amount": "94.55",
            "billed_amount": "150.00",
            "service_date": "2025-03-01",
            "member_id": "MBR-1",
            "original_claim_id": "",
        }
        assert engine.evaluate(request, claim) is None


# ------------------------------------------- golden-set contract (hard gates)


def test_rules_are_100_percent_precise_on_golden_set(engine, dataset):
    claims, truth, requests = dataset
    fired = 0
    for request in requests:
        rec = _resolve(engine, claims, request)
        if rec is None:
            continue
        fired += 1
        t = truth[request["request_id"]]
        assert rec.action.value == t["correct_action"], (
            f"{rec.rule_id} wrong action on {request['request_id']} "
            f"({t['scenario_id']}): {rec.action} != {t['correct_action']}"
        )
        if t["correct_adjustment_amount"]:
            assert rec.adjustment_amount == Decimal(t["correct_adjustment_amount"])
        assert rec.favorable_to_provider == (t["favorable_to_provider"] == "True")
    assert fired > 0


def test_rules_resolve_every_clear_cut_case(engine, dataset):
    claims, truth, requests = dataset
    clear_cut = [r for r in requests if truth[r["request_id"]]["clear_cut"] == "True"]
    resolved = sum(_resolve(engine, claims, r) is not None for r in clear_cut)
    assert resolved == len(clear_cut)


def test_rules_coverage_share(engine, dataset):
    claims, _, requests = dataset
    coverage = sum(_resolve(engine, claims, r) is not None for r in requests) / len(requests)
    assert 0.28 <= coverage <= 0.38, f"coverage {coverage:.1%} outside expected band"
