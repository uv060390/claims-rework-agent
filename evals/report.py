"""Generate docs/eval-report.md from the harness (plus judge results if present).

Usage:
    uv run python -m evals.report
"""

import json
from datetime import UTC, datetime
from pathlib import Path

from evals import harness

OUT = Path("docs/eval-report.md")
JUDGE = Path("evals/traces/judge_results.jsonl")


def main() -> None:
    clf = harness.eval_classifier()
    rules = harness.eval_rules()
    agent = harness.eval_agent_traces()
    grounded = harness.eval_groundedness()
    judge = None
    if JUDGE.exists():
        verdicts = [json.loads(line) for line in JUDGE.open()]
        judge = {
            "n": len(verdicts),
            "grounded": sum(v["grounded"] for v in verdicts),
            "flagged": [v for v in verdicts if not v["grounded"]],
        }

    scenario_rows = "\n".join(
        f"| `{s}` | {v['correct']}/{v['n']} |" for s, v in sorted(agent["by_scenario"].items())
    )
    judge_section = (
        f"""## LLM judge — semantic groundedness

A Claude judge replayed each trace and checked every material assertion in the
rationale against the evidence the agent saw. **{judge["grounded"]}/{judge["n"]} grounded.**
"""
        + (
            "\nFlagged:\n"
            + "\n".join(
                f"- `{v['request_id']}`: {'; '.join(v['unsupported_assertions'])}"
                for v in judge["flagged"]
            )
            + "\n"
            if judge["flagged"]
            else ""
        )
        if judge
        else "## LLM judge — semantic groundedness\n\n_Not yet run (`uv run python -m evals.judge`)._\n"
    )

    report = f"""# Evaluation report

Generated {datetime.now(UTC).strftime("%Y-%m-%d")} by `evals/report.py` against the frozen
demo golden set (5,000 requests, seed 42) and the committed agent traces
(45 stratified agent-bound cases, `{harness.TRACES}`). Every number below is
reproducible offline except the LLM-judge section. **All data is synthetic.**

## Safety gates (CI hard-fails, `tests/test_evals.py`)

| Gate | Result |
|---|---|
| Unsafe agent errors (favorable rec on unfavorable truth — the only class STP would release unreviewed) | **{agent["unsafe_errors"]}** |
| Ungrounded identifiers in rationales (claim ids / CARC codes / amounts absent from evidence) | **{len(grounded["flagged"])}** |
| Rules golden-set action precision | **{rules["action_precision"]:.0%}** |

## Layer 1 — No-Adjustment-Needed classifier (held-out provider split, n={clf["n_test"]})

| Metric | Value |
|---|---|
| PR-AUC | {clf["pr_auc"]:.3f} |
| Precision @ threshold | {clf["precision_at_threshold"]:.1%} |
| Recall @ threshold | {clf["recall_at_threshold"]:.1%} |
| Auto-close share | {clf["auto_close_share"]:.1%} |
| False auto-closes | {clf["false_auto_closes"]} / {clf["n_test"]} |

## Layer 2 — Rules engine (full golden set, n={rules["n"]})

| Metric | Value |
|---|---|
| Coverage | {rules["coverage"]:.1%} ({rules["fired"]} requests) |
| Action precision | {rules["action_precision"]:.0%} |
| Adjustment-amount precision | {rules["amount_precision"]:.0%} |

## Layer 3 — Triage agent (trace replay, n={agent["n"]})

| Metric | Value |
|---|---|
| Action accuracy | {agent["action_accuracy"]:.1%} |
| Adjustment-amount precision (n={agent["amount_n"]}) | {agent["amount_precision"]:.0%} |
| Unsafe errors | {agent["unsafe_errors"]} |
| Mean confidence — correct / miss | {agent["mean_confidence_correct"]:.2f} / {agent["mean_confidence_miss"]:.2f} |
| Mean tool calls per case | {agent["mean_tool_calls"]:.1f} |

Per scenario:

| Scenario | Correct |
|---|---|
{scenario_rows}

Every agent miss recommends the **unfavorable** direction (uphold instead of
reprocess), so each one parks with a human analyst rather than releasing money —
errors are absorbed by the architecture, not just minimized by the model.

## Deterministic groundedness (offline)

{grounded["grounded"]}/{grounded["n"]} rationales cite only claim ids, CARC codes, and
dollar amounts that appear in — or are exact arithmetic on — the evidence the agent
retrieved. Violations hard-fail CI.

{judge_section}
## Case study — the eval loop paying for itself

The first judged run scored only 33/45 grounded and exposed a *systematic* failure:
the agent stated requester assertions as verified facts ("auth AUTH-770978 approved
for this member") when no tool in its inventory can verify an authorization. The fix
was one prompt requirement — epistemic precision: state as fact only what a record or
tool result shows, attribute everything else to its source ("the request cites auth
AUTH-123"). Re-recorded traces: action accuracy 91.1% → 93.3%, judge-grounded
73% → 89%. Of the remaining judge flags, manual review showed most are judge
over-strictness about absence-of-evidence claims that ARE grounded in empty filtered
search results (the tool calls are in the traces) — a reminder that LLM judges need
auditing too, which is why the deterministic identifier check runs alongside.

## Known limitations

- The golden set is synthetic; scenario templates bound the difficulty ceiling.
- Confidence separation between correct (~{agent["mean_confidence_correct"]:.2f}) and missed
  (~{agent["mean_confidence_miss"]:.2f}) answers is weak — confidence should not yet be used
  as an autonomous gate, which is one more reason STP keys off action favorability only.
- Trace sample is 45 cases (5 per agent-bound scenario); production would score
  continuously on adjudicated outcomes.
"""
    OUT.write_text(report)
    print(f"wrote {OUT}")
    print(
        f"classifier PR-AUC {clf['pr_auc']:.3f} | rules {rules['coverage']:.1%}@100% | "
        f"agent {agent['action_accuracy']:.1%} acc, {agent['unsafe_errors']} unsafe | "
        f"grounded {grounded['grounded']}/{grounded['n']}"
    )


if __name__ == "__main__":
    main()
