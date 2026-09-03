"""Eval-harness CI gates. Offline — they replay committed artifacts.

The two hard safety gates:
  1. ZERO unsafe agent errors — a favorable recommendation where ground truth is
     unfavorable is the only error class the STP gate would release unreviewed.
  2. ZERO ungrounded identifiers — no claim id, CARC code, or dollar amount in a
     rationale that is absent from the evidence the agent actually saw.
"""

import json
from pathlib import Path

from evals import harness


def test_stp_safety_zero_unsafe_agent_errors():
    result = harness.eval_agent_traces()
    assert result["unsafe_errors"] == 0, (
        f"UNSAFE: favorable recommendation on unfavorable truth for {result['unsafe_request_ids']}"
    )


def test_rationales_cite_only_evidence():
    result = harness.eval_groundedness()
    assert result["flagged"] == {}, f"ungrounded rationales: {result['flagged']}"


def test_agent_action_accuracy_floor():
    assert harness.eval_agent_traces()["action_accuracy"] >= 0.85


def test_agent_amount_precision_exact():
    result = harness.eval_agent_traces()
    assert result["amount_precision"] == 1.0


def test_classifier_heldout_quality():
    result = harness.eval_classifier()
    assert result["pr_auc"] >= 0.95
    assert result["precision_at_threshold"] >= 0.98


def test_rules_precision_and_coverage():
    result = harness.eval_rules()
    assert result["action_precision"] == 1.0
    assert result["amount_precision"] == 1.0
    assert 0.28 <= result["coverage"] <= 0.38


def test_judge_results_agree_if_present():
    path = Path("evals/traces/judge_results.jsonl")
    if not path.exists():
        return
    verdicts = [json.loads(line) for line in path.open()]
    if not verdicts:  # file mid-write or judge never completed
        return
    grounded = sum(v["grounded"] for v in verdicts)
    # 0.85 floor absorbs known judge over-strictness on absence-of-evidence claims
    # (see docs/eval-report.md case study); the deterministic check stays at zero
    assert grounded / len(verdicts) >= 0.85
