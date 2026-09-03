"""Evaluation harness — scores every pipeline layer against the golden set.

All functions here are offline and deterministic: the classifier is scored on the
reproduced held-out provider split, rules on the full golden set, and the agent by
replaying the committed traces in evals/traces/. CI gates (tests/test_evals.py)
call these directly; docs/eval-report.md is generated from them by evals.report.
"""

import csv
import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

import numpy as np
from sklearn.metrics import average_precision_score
from sklearn.model_selection import GroupShuffleSplit

from pipeline.classifier.infer import NANClassifier
from pipeline.classifier.train import load_dataset
from pipeline.orchestrator import STP_ACTIONS
from pipeline.rules.engine import RulesEngine

DATA = Path("data/demo")
TRACES = Path("evals/traces/traces.jsonl")

FAVORABLE = {a.value for a in STP_ACTIONS}


def load_golden() -> tuple[dict, dict, list[dict]]:
    with (DATA / "claims.csv").open() as f:
        claims = {r["claim_id"]: r for r in csv.DictReader(f)}
    with (DATA / "ground_truth.csv").open() as f:
        truth = {r["request_id"]: r for r in csv.DictReader(f)}
    with (DATA / "rework_requests.csv").open() as f:
        requests = list(csv.DictReader(f))
    return claims, truth, requests


# ------------------------------------------------------------- layer 1: classifier


def eval_classifier(seed: int = 42) -> dict:
    """Score the committed model on the SAME held-out provider split used in training."""
    X, y, groups = load_dataset(DATA)
    splitter = GroupShuffleSplit(n_splits=1, test_size=0.25, random_state=seed)
    _, test_idx = next(splitter.split(X, y, groups))
    clf = NANClassifier()
    probs = clf.model.predict_proba(X.iloc[test_idx])[:, 1]
    y_test = y[test_idx]
    decisions = probs >= clf.threshold
    return {
        "n_test": int(len(test_idx)),
        "pr_auc": float(average_precision_score(y_test, probs)),
        "precision_at_threshold": float((y_test[decisions] == 1).mean()),
        "recall_at_threshold": float(decisions[y_test == 1].mean()),
        "auto_close_share": float(decisions.mean()),
        "false_auto_closes": int((decisions & (y_test == 0)).sum()),
    }


# ------------------------------------------------------------------ layer 2: rules


def eval_rules() -> dict:
    claims, truth, requests = load_golden()
    engine = RulesEngine()
    fired = correct = amount_correct = amount_total = 0
    for request in requests:
        claim = claims[request["claim_id"]]
        rec = engine.evaluate(request, claim, claims.get(claim["original_claim_id"]) or None)
        if rec is None:
            continue
        fired += 1
        t = truth[request["request_id"]]
        if rec.action.value == t["correct_action"]:
            correct += 1
        if t["correct_adjustment_amount"]:
            amount_total += 1
            if rec.adjustment_amount == Decimal(t["correct_adjustment_amount"]):
                amount_correct += 1
    return {
        "n": len(requests),
        "fired": fired,
        "coverage": fired / len(requests),
        "action_precision": correct / fired if fired else 0.0,
        "amount_precision": amount_correct / amount_total if amount_total else 1.0,
    }


# -------------------------------------------------- layer 3: agent (trace replay)


def load_traces(path: Path = TRACES) -> list[dict]:
    return [json.loads(line) for line in path.open()]


def eval_agent_traces(traces: list[dict] | None = None) -> dict:
    traces = traces if traces is not None else load_traces()
    n = len(traces)
    correct = [t for t in traces if t["action_correct"]]
    misses = [t for t in traces if not t["action_correct"]]

    amount_total = amount_correct = 0
    for t in traces:
        expected = t.get("correct_adjustment_amount")
        if t["recommendation"]["action"] in ("adjust_up", "adjust_down") and expected:
            amount_total += 1
            try:
                if Decimal(t["recommendation"]["adjustment_amount"]) == Decimal(expected):
                    amount_correct += 1
            except (InvalidOperation, TypeError):
                pass

    # an unsafe error recommends a FAVORABLE action when truth is unfavorable —
    # the only error class the STP gate would release without a human
    unsafe = [
        t
        for t in misses
        if t["recommendation"]["action"] in FAVORABLE and t["correct_action"] not in FAVORABLE
    ]
    tool_calls = [
        sum(len(m.get("tool_calls", [])) for m in t["messages"] if m["role"] == "ai")
        for t in traces
    ]
    by_scenario: dict[str, dict] = {}
    for t in traces:
        s = by_scenario.setdefault(t["scenario_id"], {"n": 0, "correct": 0})
        s["n"] += 1
        s["correct"] += t["action_correct"]

    return {
        "n": n,
        "action_accuracy": len(correct) / n,
        "amount_precision": amount_correct / amount_total if amount_total else 1.0,
        "amount_n": amount_total,
        "unsafe_errors": len(unsafe),
        "unsafe_request_ids": [t["request_id"] for t in unsafe],
        "mean_confidence_correct": float(
            np.mean([t["recommendation"]["confidence"] for t in correct])
        )
        if correct
        else 0.0,
        "mean_confidence_miss": float(np.mean([t["recommendation"]["confidence"] for t in misses]))
        if misses
        else 0.0,
        "mean_tool_calls": float(np.mean(tool_calls)),
        "by_scenario": by_scenario,
    }


# ------------------------------------------- groundedness (deterministic, offline)

_MONEY = re.compile(r"\$(\d[\d,]*\.?\d{0,2})")
_CLAIM_ID = re.compile(r"CLM-\d{8}")
_CARC = re.compile(r"CARC\s*(\d+)")


def _evidence_text(trace: dict) -> str:
    parts = []
    for m in trace["messages"]:
        if m["role"] in ("human", "tool") and m.get("content"):
            parts.append(str(m["content"]))
    return "\n".join(parts)


def _evidence_amounts(evidence: str) -> set[Decimal]:
    amounts = set()
    for raw in re.findall(r"\d+\.\d{2}", evidence):
        try:
            amounts.add(Decimal(raw))
        except InvalidOperation:
            continue
    # cited deltas computed from two evidence amounts are legitimate arithmetic
    listed = sorted(amounts)
    for i, a in enumerate(listed):
        for b in listed[i + 1 :]:
            amounts.add(b - a)
    return amounts


def check_groundedness(trace: dict) -> list[str]:
    """Violations: identifiers/amounts in the rationale absent from the evidence."""
    rationale = trace["recommendation"]["rationale"]
    evidence = _evidence_text(trace)
    amounts = _evidence_amounts(evidence)
    violations = []
    for cid in _CLAIM_ID.findall(rationale):
        if cid not in evidence:
            violations.append(f"claim id {cid} not in evidence")
    for carc in _CARC.findall(rationale):
        if f'"{carc}"' not in evidence and f"CARC {carc}" not in evidence:
            violations.append(f"CARC {carc} not in evidence")
    for raw in _MONEY.findall(rationale):
        try:
            value = Decimal(raw.replace(",", ""))
        except InvalidOperation:
            continue
        if value not in amounts:
            violations.append(f"amount ${value} not in evidence or derivable")
    return violations


def eval_groundedness(traces: list[dict] | None = None) -> dict:
    traces = traces if traces is not None else load_traces()
    per_trace = {t["request_id"]: check_groundedness(t) for t in traces}
    flagged = {k: v for k, v in per_trace.items() if v}
    return {
        "n": len(traces),
        "grounded": len(traces) - len(flagged),
        "flagged": flagged,
    }
