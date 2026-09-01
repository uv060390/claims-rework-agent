# AGENTS.md — agent design contract

This file is the contract for every automated decision-maker in the pipeline: the two
non-LLM gates, the LangGraph triage agent, and the orchestrator that binds them. Code in
`pipeline/` must match this document; update both together.

## Decision chain

A rework request passes through layers in strict order. Each layer either resolves the
request or passes it down. Cheaper layers run first; the LLM only sees cases the
deterministic layers could not resolve.

```
request ─► [1] NAN classifier ─► [2] rules engine ─► [3] triage agent ─► [4] orchestrator gate
```

### 1. No-Adjustment-Needed (NAN) classifier — `pipeline/classifier/`

- XGBoost binary classifier over structured claim/request features.
- If `P(no_adjustment_needed)` ≥ the high-precision operating threshold (see
  `docs/model-card.md`), the request auto-closes with action `no_change`.
- May only ever produce `no_change` — it can never trigger an adjustment.

### 2. Rules engine — `pipeline/rules/`

- Deterministic YAML rules for clear-cut cases (duplicate claim, timely-filing expiry,
  exact fee-schedule underpayment, …).
- Emits the same `Recommendation` schema as the agent, with `source="rule"` and a
  `rule_id`. A rule must be 100% precise on the golden set or it is removed.

### 3. Triage agent — `pipeline/agent/` (LangGraph + Claude)

Graph:

```
gather_context ─► analyze ─►(tool calls as needed)─► recommend ─► post_to_ticket
```

Tools (all read-only, all HTTP against mocks):
| Tool | Backs onto |
|---|---|
| `get_claim` | mock-unet claim record |
| `get_provider_history` | mock-unet claim history for the NPI |
| `fee_schedule_lookup` | static fee schedule in mock-unet |
| `get_prior_rework` | ledger: previous requests on the same claim |

Output — `Recommendation` (Pydantic, validated before anything is posted):

```python
{
    "action": "adjust_up | adjust_down | uphold_denial | reprocess | route_specialist",
    "adjustment_amount": Decimal | None,
    "rationale": str,  # must cite claim facts; no invented codes
    "confidence": float,  # 0-1
    "favorable_to_provider": bool,
    "source": "agent",
}
```

Agent constraints:
- The agent **recommends only**. It has no tool that mutates a claim, releases a queue
  job, or approves anything.
- The recommendation is posted as a work-note to the mock-servicenow ticket; state
  transitions happen in the orchestrator.
- Rationales must reference retrieved evidence; the eval harness LLM-judge fails
  rationales containing codes or amounts not present in tool outputs.

### 4. Orchestrator gate — `pipeline/orchestrator.py`

- **STP rule:** a recommendation auto-releases to the execution queue only if
  `favorable_to_provider is True`. Everything else parks the ticket in
  `Pending Approval` for a human analyst (dashboard).
- This gate is plain code in the orchestrator — deliberately outside the agent — so the
  LLM cannot authorize its own actions. Guarded by `tests/test_stp_gate.py`
  (CI hard-fail if an unfavorable case ever auto-releases).
- On analyst Approve (or STP), the orchestrator enqueues a job to mock-uipath, which
  executes against mock-unet.

## Audit ledger

Every layer appends one `pipeline_events` row per decision:
`(request_id, layer, decision, payload_hash, created_at)` — append-only. The full
provenance of any outcome must be reconstructable from the ledger alone.

## Working on this repo with an agent (Claude Code etc.)

- Obey the Hard rules in `CLAUDE.md` (synthetic data only, no employer-internal names,
  STP gate placement, append-only ledger).
- `uv run pytest && uv run ruff check .` must pass before any commit.
- Changing the `Recommendation` schema means updating: `pipeline/schemas.py`, this file,
  the rules engine emitters, the agent's structured-output prompt, and the eval harness.
