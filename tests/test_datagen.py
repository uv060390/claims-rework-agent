from decimal import Decimal

from pipeline.datagen.codes import BH_SERVICES, CARC_CODES, TIMELY_FILING_DAYS
from pipeline.datagen.generator import SynthGenerator, write_csvs
from pipeline.datagen.npi import is_valid_npi
from pipeline.schemas import Action

N = 800  # big enough for every scenario to appear


def _cases(seed: int = 42):
    return SynthGenerator(seed=seed).generate(N)


def test_deterministic_given_seed():
    a = SynthGenerator(seed=7).generate(50)
    b = SynthGenerator(seed=7).generate(50)
    assert [c.model_dump() for c in a] == [c.model_dump() for c in b]


def test_different_seeds_differ():
    a = SynthGenerator(seed=1).generate(50)
    b = SynthGenerator(seed=2).generate(50)
    assert [c.model_dump() for c in a] != [c.model_dump() for c in b]


def test_codes_and_npis_valid():
    for case in _cases():
        for claim in [case.claim, *case.extra_claims]:
            assert claim.cpt_code in BH_SERVICES
            assert is_valid_npi(claim.provider_npi)
            if claim.status == "denied":
                assert claim.denial_carc in CARC_CODES
                assert claim.paid_amount == Decimal("0.00")
            else:
                assert claim.denial_carc == ""


def test_ground_truth_consistency():
    for case in _cases():
        t = case.truth
        assert t.request_id == case.request.request_id
        # NAN label is derived from the action, one source of truth
        assert t.no_adjustment_needed == (
            t.correct_action in (Action.NO_CHANGE, Action.UPHOLD_DENIAL)
        )
        # favorable outcomes are exactly the pay-more / reprocess-for-payment actions
        if t.favorable_to_provider:
            assert t.correct_action in (Action.ADJUST_UP, Action.REPROCESS)
        # adjustment amounts appear iff the action adjusts
        if t.correct_action in (Action.ADJUST_UP, Action.ADJUST_DOWN):
            assert t.correct_adjustment_amount is not None
            assert t.correct_adjustment_amount > 0
        else:
            assert t.correct_adjustment_amount is None


def test_underpayment_amounts_reconcile():
    for case in _cases():
        if case.truth.scenario_id in ("underpaid_fee_schedule", "wrong_units_underpaid"):
            claim = case.claim
            delta = claim.allowed_amount - claim.paid_amount
            assert delta == case.truth.correct_adjustment_amount
            assert claim.status == "partial"


def test_timely_filing_scenarios_exceed_limit():
    for case in _cases():
        if case.truth.scenario_id.startswith("timely_filing"):
            lag = (case.claim.submitted_date - case.claim.service_date).days
            assert lag > TIMELY_FILING_DAYS


def test_label_balance():
    cases = _cases()
    nan_share = sum(c.truth.no_adjustment_needed for c in cases) / len(cases)
    fav_share = sum(c.truth.favorable_to_provider for c in cases) / len(cases)
    assert 0.30 <= nan_share <= 0.55
    assert 0.30 <= fav_share <= 0.55
    assert len({c.truth.scenario_id for c in cases}) == 13


def test_csv_writer_roundtrip(tmp_path):
    cases = SynthGenerator(seed=3).generate(40)
    counts = write_csvs(cases, tmp_path)
    assert counts["rework_requests"] == counts["ground_truth"] == 40
    assert counts["claims"] >= 40  # duplicates/resubmissions add extra claims
    header = (tmp_path / "rework_requests.csv").read_text().splitlines()[0]
    assert "note" in header and "scenario" not in header  # no label leakage
