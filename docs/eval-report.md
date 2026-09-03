# Evaluation report

Generated 2026-09-03 by `evals/report.py` against the frozen
demo golden set (5,000 requests, seed 42) and the committed agent traces
(45 stratified agent-bound cases, `evals/traces/traces.jsonl`). Every number below is
reproducible offline except the LLM-judge section. **All data is synthetic.**

## Safety gates (CI hard-fails, `tests/test_evals.py`)

| Gate | Result |
|---|---|
| Unsafe agent errors (favorable rec on unfavorable truth — the only class STP would release unreviewed) | **0** |
| Ungrounded identifiers in rationales (claim ids / CARC codes / amounts absent from evidence) | **0** |
| Rules golden-set action precision | **100%** |

## Layer 1 — No-Adjustment-Needed classifier (held-out provider split, n=1284)

| Metric | Value |
|---|---|
| PR-AUC | 0.989 |
| Precision @ threshold | 99.1% |
| Recall @ threshold | 77.8% |
| Auto-close share | 34.7% |
| False auto-closes | 4 / 1284 |

## Layer 2 — Rules engine (full golden set, n=5000)

| Metric | Value |
|---|---|
| Coverage | 32.2% (1610 requests) |
| Action precision | 100% |
| Adjustment-amount precision | 100% |

## Layer 3 — Triage agent (trace replay, n=45)

| Metric | Value |
|---|---|
| Action accuracy | 93.3% |
| Adjustment-amount precision (n=5) | 100% |
| Unsafe errors | 0 |
| Mean confidence — correct / miss | 0.88 / 0.90 |
| Mean tool calls per case | 1.7 |

Per scenario:

| Scenario | Correct |
|---|---|
| `auth_denied_in_error` | 5/5 |
| `cob_conflict` | 5/5 |
| `corrected_resubmission_denied_as_dup` | 5/5 |
| `missing_auth_valid_denial` | 5/5 |
| `telehealth_modifier_denial` | 5/5 |
| `timely_filing_exception` | 2/5 |
| `timely_filing_expired` | 5/5 |
| `true_duplicate` | 5/5 |
| `wrong_units_underpaid` | 5/5 |

Every agent miss recommends the **unfavorable** direction (uphold instead of
reprocess), so each one parks with a human analyst rather than releasing money —
errors are absorbed by the architecture, not just minimized by the model.

## Deterministic groundedness (offline)

45/45 rationales cite only claim ids, CARC codes, and
dollar amounts that appear in — or are exact arithmetic on — the evidence the agent
retrieved. Violations hard-fail CI.

## LLM judge — semantic groundedness

A Claude judge replayed each trace and checked every material assertion in the
rationale against the evidence the agent saw. **40/45 grounded.**

Flagged:
- `RWK-003746`: POS 10 is characterized as telehealth by the rationale as if confirmed/factual, but this is the requester's claim/domain interpretation being asserted as fact about the claim's meaning without evidence support beyond the code itself - though POS code meaning is domain knowledge, the claim record does not label POS 10 as telehealth
- `RWK-001837`: Provider history shows no earlier claim record for this member/date/CPT.
- `RWK-000301`: No prior rework or earlier claim record exists in the system for this member/date/CPT combination, consistent with the original submission not having been logged as a separate claim.
- `RWK-001081`: No earlier claim record was found in provider history (only this same CLM-00001262 record appears), consistent with an original submission that didn't create a separate system record.
- `RWK-002021`: The rework request specifically asks for a 'hardship-style' exception

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
- Confidence separation between correct (~0.88) and missed
  (~0.90) answers is weak — confidence should not yet be used
  as an autonomous gate, which is one more reason STP keys off action favorability only.
- Trace sample is 45 cases (5 per agent-bound scenario); production would score
  continuously on adjudicated outcomes.
