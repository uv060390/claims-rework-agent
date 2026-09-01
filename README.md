# claims-rework-agent

**Recommend-then-Release: a human-in-the-loop agentic pipeline for healthcare claims rework, on fully synthetic data.**

A public reimplementation of the architecture behind a production claims-rework automation
system I designed and shipped at a Fortune-10 healthcare company — rebuilt end-to-end on
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
| 2 | Mock services + Postgres audit ledger (docker compose) | ⬜ |
| 3 | NAN classifier + model card | ⬜ |
| 4 | Rules engine | ⬜ |
| 5 | LangGraph + Claude triage agent | ⬜ |
| 6 | Analyst dashboard (Next.js / Vercel) | ⬜ |
| 7 | Evaluation harness + eval report | ⬜ |
| 8 | Polish, demo GIF, live deployment | ⬜ |

## Quickstart

```bash
uv sync
uv run pytest
uv run python data/generate_rework.py --n-requests 5000 --seed 42 --out data/demo
# full pipeline quickstart lands with Phase 2 (docker compose up)
```

A frozen 5,000-request demo dataset (5,837 claims, 13 rework scenarios, separate
ground-truth file so the pipeline can never see labels) ships in `data/demo/` —
see the [data dictionary](docs/data-dictionary.md).

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/). Agent runs need an
`ANTHROPIC_API_KEY`; recorded traces in `evals/traces/` demo the agent without one.

## License

MIT
