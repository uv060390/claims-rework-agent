# claims-rework-agent

**Recommend-then-Release: a human-in-the-loop agentic pipeline for healthcare claims rework, on fully synthetic data.**

A public reimplementation of the architecture behind a production claims-rework automation
system I designed and shipped at a Fortune-500 healthcare company — rebuilt end-to-end on
synthetic data so every layer is inspectable and runnable. In production, the original
system auto-resolves 25% of rework volume for a 120-FTE operation handling ~100K
adjustments/month. All data and metrics **in this repo** are synthetic/simulated.

## How it works

Cheap deterministic layers run first; the LLM only reasons over cases they can't resolve.
Irreversible outcomes always require a human.

```
Rework request (synthetic)
   │
   ▼
[1] XGBoost "No-Adjustment-Needed" classifier ──► confident no-change? → auto-close
   │
   ▼
[2] Deterministic rules engine ──► clear-cut case? → recommendation without LLM
   │
   ▼
[3] LangGraph + Claude triage agent ──► {action, amount, rationale, confidence}
   │
   ▼
[4] Recommendation posted to ticketing system (mock)
   │
   ├── favorable to provider ──► straight-through: released to execution queue
   └── unfavorable (denial / recoupment) ──► analyst Approve required (dashboard)
   │
   ▼
[5] RPA execution queue (mock) ──► executes against claims platform (mock)
   │
   ▼
[6] Append-only audit ledger — every decision, by every layer
```

Design decisions worth reading:

- **Classifier → rules → agent ordering** keeps LLM spend proportional to genuine
  ambiguity, not raw volume.
- **The STP gate lives in the orchestrator, not the agent** — the LLM recommends but can
  never authorize its own actions. Only provider-favorable outcomes skip human review.
- **Honest system boundaries**: the ticketing system, RPA queue, and claims platform are
  in-repo FastAPI mocks with realistic API contracts, so the integration architecture is
  real even though the vendors aren't.
- **Append-only ledger**: any outcome is reconstructable from `pipeline_events` alone.

See [`AGENTS.md`](AGENTS.md) for the full agent design contract.

## Status

| Phase | Deliverable | Status |
|---|---|---|
| 0 | Repo scaffold, CI, design docs | ✅ |
| 1 | Synthetic claims + rework dataset ([13 scenarios](docs/data-dictionary.md), CMS public code sets) | ✅ |
| 2 | Mock services + Postgres audit ledger (docker compose) | ✅ |
| 3 | NAN classifier + [model card](docs/model-card.md) — PR-AUC 0.989, 34.7% auto-close @ 99% precision | ✅ |
| 4 | Rules engine — 32.2% coverage at 100% precision (CI-gated) | ✅ |
| 5 | LangGraph + Claude triage agent + orchestrator with STP gate | ✅ |
| 6 | Analyst console — [live demo](https://claims-rework-console.vercel.app) | ✅ |
| 7 | Eval harness + [eval report](docs/eval-report.md) — 93.3% agent accuracy, 0 unsafe, CI safety gates | ✅ |
| 8 | Polish, demo GIF, live deployment | ⬜ |

## Quickstart

```bash
uv sync
uv run pytest
uv run python data/generate_rework.py --n-requests 5000 --seed 42 --out data/demo

docker compose up --build   # claims platform :8001, ticketing :8002, RPA queue :8003, Postgres :5432
```

With the stack up you can drive the whole Recommend-then-Release flow by hand —
create a ticket (`POST :8002/tickets`), post a recommendation work note, transition
to `pending_approval` → `approved`, release a job (`POST :8003/queues/claims-rework/jobs`),
and watch the claim change in the system of record (`GET :8001/claims/{id}`).
`tests/test_e2e_flow.py` runs exactly this flow in-process, ledger included.

A frozen 5,000-request demo dataset (5,837 claims, 13 rework scenarios, separate
ground-truth file so the pipeline can never see labels) ships in `data/demo/` —
see the [data dictionary](docs/data-dictionary.md).

On that dataset the funnel splits: **22.3%** auto-closed by the classifier,
**32.2%** resolved deterministically by rules, **45.5%** triaged by the
LangGraph + Claude agent — LLM spend goes only to genuine ambiguity.

Recorded real-Claude traces for a 45-case stratified sample of the agent-bound
queue live in `evals/traces/` (**93.3%** action accuracy; every miss was in the
safe, unfavorable direction — parked for a human, never auto-released). One
recorded find: the agent's early duplicate-hunt failures traced to a truncated
provider-history tool, fixed by adding member/date/code search filters —
a retrieval bug, not a reasoning bug.

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/). Agent runs need an
`ANTHROPIC_API_KEY`; recorded traces in `evals/traces/` demo the agent without one.

## License

MIT
