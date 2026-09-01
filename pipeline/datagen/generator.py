"""Deterministic synthetic generator for behavioral-health claims rework requests.

Every request is built from a *scenario*: a joint recipe for the claim facts, the
free-text rework note (sometimes deliberately misleading, as real requests are),
and the ground-truth resolution. Ground truth is written to a separate file so
pipeline code can never see labels.

Same seed -> byte-identical output.
"""

import csv
import random
from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel

from pipeline.datagen.codes import (
    BH_SERVICES,
    ICD10_BH,
    POS_CODES,
    PROVIDER_NAMES,
    TIMELY_FILING_DAYS,
)
from pipeline.datagen.npi import make_npi
from pipeline.schemas import Action

CENT = Decimal("0.01")


class Claim(BaseModel):
    claim_id: str
    member_id: str
    provider_npi: str
    provider_name: str
    service_date: date
    submitted_date: date
    cpt_code: str
    modifiers: str  # space-separated, may be empty
    icd10_code: str
    pos_code: str
    units: int
    billed_amount: Decimal
    allowed_amount: Decimal
    paid_amount: Decimal
    status: str  # paid | partial | denied
    denial_carc: str  # empty when not denied
    original_claim_id: str  # set for duplicates / resubmissions


class ReworkRequest(BaseModel):
    request_id: str
    claim_id: str
    received_date: date
    requester_type: str  # provider | internal_audit | member_advocate
    resubmission_count: int
    has_attachment: bool
    note: str


class GroundTruth(BaseModel):
    request_id: str
    scenario_id: str
    correct_action: Action
    correct_adjustment_amount: Decimal | None
    no_adjustment_needed: bool
    favorable_to_provider: bool
    clear_cut: bool  # resolvable by the deterministic rules layer


class Case(BaseModel):
    claim: Claim
    extra_claims: list[Claim] = []  # e.g. the original claim behind a duplicate
    request: ReworkRequest
    truth: GroundTruth


def _money(x: Decimal) -> Decimal:
    return x.quantize(CENT)


class SynthGenerator:
    """All randomness flows through one seeded ``random.Random``."""

    def __init__(self, seed: int = 42, n_providers: int = 20):
        self.rng = random.Random(seed)
        self._claim_seq = 0
        self._req_seq = 0
        self.providers = [
            (make_npi(self.rng), PROVIDER_NAMES[i % len(PROVIDER_NAMES)])
            for i in range(n_providers)
        ]

    # ---------------------------------------------------------------- helpers

    def _next_claim_id(self) -> str:
        self._claim_seq += 1
        return f"CLM-{self._claim_seq:08d}"

    def _next_request_id(self) -> str:
        self._req_seq += 1
        return f"RWK-{self._req_seq:06d}"

    def _base_claim(self, *, submit_lag: tuple[int, int] = (5, 30)) -> Claim:
        rng = self.rng
        npi, name = rng.choice(self.providers)
        cpt = rng.choice(list(BH_SERVICES))
        _, allowed_per_unit = BH_SERVICES[cpt]
        units = 1
        pos = rng.choices(list(POS_CODES), weights=[8, 10, 45, 5, 4, 8, 12, 8], k=1)[0]
        mods = []
        if pos in ("02", "10") and rng.random() < 0.9:
            mods.append("95")
        if cpt.startswith("H") and rng.random() < 0.4:
            mods.append(rng.choice(["HO", "HN"]))
        allowed = _money(allowed_per_unit * units)
        billed = _money(allowed * Decimal(str(rng.uniform(1.1, 1.9))))
        service = date(2025, 1, 1) + timedelta(days=rng.randint(0, 330))
        return Claim(
            claim_id=self._next_claim_id(),
            member_id=f"MBR-{rng.randint(1, 3_000_000):07d}",
            provider_npi=npi,
            provider_name=name,
            service_date=service,
            submitted_date=service + timedelta(days=rng.randint(*submit_lag)),
            cpt_code=cpt,
            modifiers=" ".join(mods),
            icd10_code=rng.choice(list(ICD10_BH)),
            pos_code=pos,
            units=units,
            billed_amount=billed,
            allowed_amount=allowed,
            paid_amount=allowed,
            status="paid",
            denial_carc="",
            original_claim_id="",
        )

    def _request(
        self,
        claim: Claim,
        note: str,
        *,
        requester: str = "provider",
        attachment: bool = False,
    ) -> ReworkRequest:
        rng = self.rng
        return ReworkRequest(
            request_id=self._next_request_id(),
            claim_id=claim.claim_id,
            received_date=claim.submitted_date + timedelta(days=rng.randint(20, 90)),
            requester_type=requester,
            resubmission_count=rng.choices([0, 1, 2], weights=[75, 20, 5], k=1)[0],
            has_attachment=attachment,
            note=note,
        )

    def _pick(self, templates: list[str], **slots) -> str:
        return self.rng.choice(templates).format(**slots)

    # -------------------------------------------------------------- scenarios
    # Each scenario returns a Case. Notes intentionally mix honest and
    # misleading framings, mirroring real rework queues.

    def s_underpaid_fee_schedule(self) -> Case:
        claim = self._base_claim()
        delta = _money(claim.allowed_amount * Decimal(str(self.rng.uniform(0.15, 0.45))))
        claim.paid_amount = _money(claim.allowed_amount - delta)
        claim.status = "partial"
        note = self._pick(
            [
                "Payment received of ${paid} is below the contracted fee schedule rate of "
                "${allowed} for CPT {cpt} on DOS {dos}. Requesting adjustment for the difference.",
                "Underpayment on claim for CPT {cpt}, DOS {dos}. Allowed should be ${allowed}, "
                "we were paid ${paid}. Please reprocess at the correct rate.",
                "EOB shows ${paid} paid vs fee schedule ${allowed} for {cpt}. Requesting the "
                "underpaid balance be released.",
            ],
            paid=claim.paid_amount,
            allowed=claim.allowed_amount,
            cpt=claim.cpt_code,
            dos=claim.service_date,
        )
        return Case(
            claim=claim,
            request=self._request(claim, note),
            truth=GroundTruth(
                request_id="",
                scenario_id="underpaid_fee_schedule",
                correct_action=Action.ADJUST_UP,
                correct_adjustment_amount=delta,
                no_adjustment_needed=False,
                favorable_to_provider=True,
                clear_cut=True,
            ),
        )

    def s_overpaid_recoupment(self) -> Case:
        claim = self._base_claim()
        delta = _money(claim.allowed_amount * Decimal(str(self.rng.uniform(0.2, 0.6))))
        claim.paid_amount = _money(claim.allowed_amount + delta)
        note = self._pick(
            [
                "Audit finding: claim paid ${paid} against an allowed amount of ${allowed} for "
                "CPT {cpt}. Overpayment of ${delta} identified; initiate recoupment.",
                "Payment integrity review flagged this claim as overpaid by ${delta} "
                "(paid ${paid}, allowed ${allowed}). Please adjust.",
            ],
            paid=claim.paid_amount,
            allowed=claim.allowed_amount,
            cpt=claim.cpt_code,
            delta=delta,
        )
        return Case(
            claim=claim,
            request=self._request(claim, note, requester="internal_audit"),
            truth=GroundTruth(
                request_id="",
                scenario_id="overpaid_recoupment",
                correct_action=Action.ADJUST_DOWN,
                correct_adjustment_amount=delta,
                no_adjustment_needed=False,
                favorable_to_provider=False,
                clear_cut=True,
            ),
        )

    def s_correct_payment_dispute(self) -> Case:
        claim = self._base_claim()  # paid == allowed: nothing wrong
        note = self._pick(
            [
                "We believe this claim for CPT {cpt} on {dos} was underpaid. Our billed amount "
                "was ${billed} but only ${paid} was received. Requesting review and adjustment.",
                "Reimbursement of ${paid} appears low for {cpt}. Please reprocess this claim "
                "at the correct rate.",
                "Provider disputes the payment amount on this claim and requests the balance "
                "of the billed charges (${billed}).",
            ],
            cpt=claim.cpt_code,
            dos=claim.service_date,
            billed=claim.billed_amount,
            paid=claim.paid_amount,
        )
        return Case(
            claim=claim,
            request=self._request(claim, note),
            truth=GroundTruth(
                request_id="",
                scenario_id="correct_payment_dispute",
                correct_action=Action.NO_CHANGE,
                correct_adjustment_amount=None,
                no_adjustment_needed=True,
                favorable_to_provider=False,
                clear_cut=False,
            ),
        )

    def s_true_duplicate(self) -> Case:
        original = self._base_claim()
        dup = original.model_copy(deep=True)
        dup.claim_id = self._next_claim_id()
        dup.submitted_date = original.submitted_date + timedelta(days=self.rng.randint(7, 40))
        dup.paid_amount = Decimal("0.00")
        dup.status = "denied"
        dup.denial_carc = "18"
        dup.original_claim_id = original.claim_id
        note = self._pick(
            [
                "Claim denied as duplicate. This is a separate service for CPT {cpt} on {dos}; "
                "please reprocess for payment.",
                "Disputing the duplicate denial on this claim. We show no other payment for "
                "this date of service.",
            ],
            cpt=dup.cpt_code,
            dos=dup.service_date,
        )
        return Case(
            claim=dup,
            extra_claims=[original],
            request=self._request(dup, note),
            truth=GroundTruth(
                request_id="",
                scenario_id="true_duplicate",
                correct_action=Action.UPHOLD_DENIAL,
                correct_adjustment_amount=None,
                no_adjustment_needed=True,
                favorable_to_provider=False,
                clear_cut=True,
            ),
        )

    def s_corrected_resubmission_denied_as_dup(self) -> Case:
        original = self._base_claim()
        original.paid_amount = Decimal("0.00")
        original.status = "denied"
        original.denial_carc = "16"
        resub = original.model_copy(deep=True)
        resub.claim_id = self._next_claim_id()
        resub.submitted_date = original.submitted_date + timedelta(days=self.rng.randint(5, 25))
        resub.icd10_code = self.rng.choice(list(ICD10_BH))
        resub.denial_carc = "18"
        resub.original_claim_id = original.claim_id
        note = self._pick(
            [
                "This is a corrected claim, not a duplicate. The original claim {orig} was "
                "denied CARC 16 for missing information; this resubmission includes the "
                "corrected diagnosis. Please reprocess.",
                "Denied in error as duplicate of {orig}. That claim was itself denied and never "
                "paid. Corrected claim attached; requesting reprocessing.",
            ],
            orig=original.claim_id,
        )
        return Case(
            claim=resub,
            extra_claims=[original],
            request=self._request(resub, note, attachment=True),
            truth=GroundTruth(
                request_id="",
                scenario_id="corrected_resubmission_denied_as_dup",
                correct_action=Action.REPROCESS,
                correct_adjustment_amount=None,
                no_adjustment_needed=False,
                favorable_to_provider=True,
                clear_cut=False,
            ),
        )

    def s_timely_filing_expired(self) -> Case:
        lag = self.rng.randint(TIMELY_FILING_DAYS + 20, TIMELY_FILING_DAYS + 180)
        claim = self._base_claim(submit_lag=(lag, lag))
        claim.paid_amount = Decimal("0.00")
        claim.status = "denied"
        claim.denial_carc = "29"
        note = self._pick(
            [
                "Requesting reconsideration of the timely filing denial for DOS {dos}. Our "
                "billing office experienced staffing turnover during this period.",
                "Claim denied for untimely filing. Provider requests an exception be applied "
                "and the claim paid.",
            ],
            dos=claim.service_date,
        )
        return Case(
            claim=claim,
            request=self._request(claim, note),
            truth=GroundTruth(
                request_id="",
                scenario_id="timely_filing_expired",
                correct_action=Action.UPHOLD_DENIAL,
                correct_adjustment_amount=None,
                no_adjustment_needed=True,
                favorable_to_provider=False,
                clear_cut=True,
            ),
        )

    def s_timely_filing_exception(self) -> Case:
        lag = self.rng.randint(TIMELY_FILING_DAYS + 10, TIMELY_FILING_DAYS + 90)
        claim = self._base_claim(submit_lag=(lag, lag))
        claim.paid_amount = Decimal("0.00")
        claim.status = "denied"
        claim.denial_carc = "29"
        note = self._pick(
            [
                "Timely filing denial disputed. Attached clearinghouse acceptance report shows "
                "the original submission on {orig_date}, within the filing limit; this claim is "
                "a corrected resubmission. Please reprocess.",
                "Denied CARC 29 in error. Proof of timely original submission ({orig_date}) is "
                "attached per the provider manual exception policy.",
            ],
            orig_date=claim.service_date + timedelta(days=self.rng.randint(10, 60)),
        )
        return Case(
            claim=claim,
            request=self._request(claim, note, attachment=True),
            truth=GroundTruth(
                request_id="",
                scenario_id="timely_filing_exception",
                correct_action=Action.REPROCESS,
                correct_adjustment_amount=None,
                no_adjustment_needed=False,
                favorable_to_provider=True,
                clear_cut=False,
            ),
        )

    def s_auth_denied_in_error(self) -> Case:
        claim = self._base_claim()
        claim.paid_amount = Decimal("0.00")
        claim.status = "denied"
        claim.denial_carc = "197"
        auth = f"AUTH-{self.rng.randint(100000, 999999)}"
        note = self._pick(
            [
                "Claim denied for missing authorization, but authorization {auth} was approved "
                "for this member covering DOS {dos}. Attached. Please reprocess for payment.",
                "Denial CARC 197 issued in error — prior auth {auth} is on file for this episode "
                "of care. Requesting reprocessing.",
            ],
            auth=auth,
            dos=claim.service_date,
        )
        return Case(
            claim=claim,
            request=self._request(claim, note, attachment=True),
            truth=GroundTruth(
                request_id="",
                scenario_id="auth_denied_in_error",
                correct_action=Action.REPROCESS,
                correct_adjustment_amount=None,
                no_adjustment_needed=False,
                favorable_to_provider=True,
                clear_cut=False,
            ),
        )

    def s_missing_auth_valid_denial(self) -> Case:
        claim = self._base_claim()
        claim.paid_amount = Decimal("0.00")
        claim.status = "denied"
        claim.denial_carc = "197"
        note = self._pick(
            [
                "Requesting reconsideration of the authorization denial for {cpt} on {dos}. "
                "The service was clinically necessary and could not be delayed.",
                "Provider disputes the CARC 197 denial and requests retro-authorization and "
                "payment for this service.",
            ],
            cpt=claim.cpt_code,
            dos=claim.service_date,
        )
        return Case(
            claim=claim,
            request=self._request(claim, note),
            truth=GroundTruth(
                request_id="",
                scenario_id="missing_auth_valid_denial",
                correct_action=Action.UPHOLD_DENIAL,
                correct_adjustment_amount=None,
                no_adjustment_needed=True,
                favorable_to_provider=False,
                clear_cut=False,
            ),
        )

    def s_cob_conflict(self) -> Case:
        claim = self._base_claim()
        claim.paid_amount = Decimal("0.00")
        claim.status = "denied"
        claim.denial_carc = "22"
        note = self._pick(
            [
                "Claim denied for coordination of benefits. Member states the other coverage "
                "terminated before DOS {dos}. Requesting COB update and reprocessing.",
                "COB denial on this claim; primary payer EOB attached showing partial payment. "
                "Please coordinate benefits and process the secondary balance.",
            ],
            dos=claim.service_date,
        )
        return Case(
            claim=claim,
            request=self._request(
                claim,
                note,
                requester=self.rng.choice(["provider", "member_advocate"]),
                attachment=self.rng.random() < 0.5,
            ),
            truth=GroundTruth(
                request_id="",
                scenario_id="cob_conflict",
                correct_action=Action.ROUTE_SPECIALIST,
                correct_adjustment_amount=None,
                no_adjustment_needed=False,
                favorable_to_provider=False,
                clear_cut=False,
            ),
        )

    def s_wrong_units_underpaid(self) -> Case:
        claim = self._base_claim()
        per_unit = BH_SERVICES[claim.cpt_code][1]
        claim.units = 2
        claim.billed_amount = _money(per_unit * 2 * Decimal(str(self.rng.uniform(1.1, 1.6))))
        claim.allowed_amount = _money(per_unit * 2)
        claim.paid_amount = _money(per_unit)  # paid for one unit only
        claim.status = "partial"
        delta = _money(claim.allowed_amount - claim.paid_amount)
        note = self._pick(
            [
                "Claim billed with 2 units of {cpt} but payment of ${paid} reflects a single "
                "unit. Session documentation supports both units. Requesting adjustment.",
                "Underpayment: two units of {cpt} rendered on {dos}, one unit paid. Please "
                "adjust for the remaining unit.",
            ],
            cpt=claim.cpt_code,
            dos=claim.service_date,
            paid=claim.paid_amount,
        )
        return Case(
            claim=claim,
            request=self._request(claim, note, attachment=self.rng.random() < 0.6),
            truth=GroundTruth(
                request_id="",
                scenario_id="wrong_units_underpaid",
                correct_action=Action.ADJUST_UP,
                correct_adjustment_amount=delta,
                no_adjustment_needed=False,
                favorable_to_provider=True,
                clear_cut=False,
            ),
        )

    def s_bundled_service_denial(self) -> Case:
        claim = self._base_claim()
        claim.paid_amount = Decimal("0.00")
        claim.status = "denied"
        claim.denial_carc = "97"
        note = self._pick(
            [
                "Disputing the bundling denial for {cpt} on {dos}; we consider this a "
                "separately payable service.",
                "Claim denied CARC 97. Requesting review — provider believes this service "
                "should not be bundled.",
            ],
            cpt=claim.cpt_code,
            dos=claim.service_date,
        )
        return Case(
            claim=claim,
            request=self._request(claim, note),
            truth=GroundTruth(
                request_id="",
                scenario_id="bundled_service_denial",
                correct_action=Action.UPHOLD_DENIAL,
                correct_adjustment_amount=None,
                no_adjustment_needed=True,
                favorable_to_provider=False,
                clear_cut=True,
            ),
        )

    def s_telehealth_modifier_denial(self) -> Case:
        claim = self._base_claim()
        claim.pos_code = self.rng.choice(["02", "10"])
        claim.modifiers = ""  # the missing modifier 95 is the whole problem
        claim.paid_amount = Decimal("0.00")
        claim.status = "denied"
        claim.denial_carc = "16"
        note = self._pick(
            [
                "Telehealth claim denied for missing information. Corrected claim with "
                "modifier 95 appended is attached; service was rendered via synchronous "
                "video. Please reprocess.",
                "CARC 16 denial — the {cpt} service on {dos} was telehealth and the claim "
                "omitted modifier 95. Corrected claim submitted.",
            ],
            cpt=claim.cpt_code,
            dos=claim.service_date,
        )
        return Case(
            claim=claim,
            request=self._request(claim, note, attachment=True),
            truth=GroundTruth(
                request_id="",
                scenario_id="telehealth_modifier_denial",
                correct_action=Action.REPROCESS,
                correct_adjustment_amount=None,
                no_adjustment_needed=False,
                favorable_to_provider=True,
                clear_cut=False,
            ),
        )

    # ------------------------------------------------------------ generation

    SCENARIO_WEIGHTS: list[tuple[str, float]] = [
        ("s_underpaid_fee_schedule", 0.14),
        ("s_overpaid_recoupment", 0.06),
        ("s_correct_payment_dispute", 0.14),
        ("s_true_duplicate", 0.10),
        ("s_corrected_resubmission_denied_as_dup", 0.07),
        ("s_timely_filing_expired", 0.09),
        ("s_timely_filing_exception", 0.06),
        ("s_auth_denied_in_error", 0.07),
        ("s_missing_auth_valid_denial", 0.07),
        ("s_cob_conflict", 0.06),
        ("s_wrong_units_underpaid", 0.07),
        ("s_bundled_service_denial", 0.04),
        ("s_telehealth_modifier_denial", 0.03),
    ]

    def generate(self, n_requests: int) -> list[Case]:
        names = [n for n, _ in self.SCENARIO_WEIGHTS]
        weights = [w for _, w in self.SCENARIO_WEIGHTS]
        cases = []
        for _ in range(n_requests):
            case = getattr(self, self.rng.choices(names, weights=weights, k=1)[0])()
            case.truth.request_id = case.request.request_id
            cases.append(case)
        return cases


def write_csvs(cases: list[Case], out_dir: Path) -> dict[str, int]:
    """Write claims.csv, rework_requests.csv, ground_truth.csv. Returns row counts."""
    out_dir.mkdir(parents=True, exist_ok=True)

    def dump(path: Path, rows: Sequence[BaseModel]) -> int:
        data = [r.model_dump(mode="json") for r in rows]
        with path.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(data[0].keys()))
            writer.writeheader()
            writer.writerows(data)
        return len(data)

    claims: list[Claim] = []
    for c in cases:
        claims.extend(c.extra_claims)
        claims.append(c.claim)
    counts = {
        "claims": dump(out_dir / "claims.csv", claims),
        "rework_requests": dump(out_dir / "rework_requests.csv", [c.request for c in cases]),
        "ground_truth": dump(out_dir / "ground_truth.csv", [c.truth for c in cases]),
    }
    return counts
