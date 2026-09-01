# CLAUDE.md — claims-rework-agent

Agentic claims-rework pipeline ("Recommend-then-Release") on fully synthetic data.
Read `AGENTS.md` for the agent/graph design contract before touching `pipeline/`.

## Hard rules

1. **Synthetic data only.** Never add real claims, member, or provider data. All datasets
   come from `data/generate_rework.py` (seeded from public CMS/Synthea sources).
2. **No employer-internal names.** Refer to integrated systems only by class:
   "claims adjudication platform" (mock-unet), "ticketing system" (mock-servicenow),
   "RPA execution queue" (mock-uipath). Never name the production systems or company
   this architecture is derived from anywhere in committed code or docs.
3. **The STP gate lives in the orchestrator, never in the agent.** Only recommendations
   flagged `favorable_to_provider == true` may auto-release; denials/recoupments always
   require a human Approve. Any change touching this path needs a test proving
   unfavorable cases cannot auto-release.
4. **Every layer writes to the audit ledger.** Any new decision point must append a
   `pipeline_events` row (append-only; never UPDATE or DELETE ledger rows).
5. Simulated metrics must be labeled as simulated in all docs.

## Layout

```
pipeline/    # classifier, rules engine, LangGraph agent, orchestrator
mocks/       # FastAPI stand-ins: servicenow/ (tickets), uipath/ (exec queue), unet/ (claims store)
data/        # synthetic data generator + frozen demo dataset
evals/       # evaluation harness (per-layer accuracy, STP safety gate)
dashboard/   # Next.js analyst Approve UI (deployed on Vercel)
docs/        # architecture, data dictionary, model card, eval report
tests/       # pytest suite
```

## Commands

```bash
uv sync                    # install deps (Python 3.11+, managed by uv)
uv run ruff check .        # lint
uv run ruff format .       # format
uv run pytest              # tests
docker compose up          # mocks + Postgres ledger (from Phase 2)
```

## Conventions

- Python 3.11+, `uv` for env/deps, `ruff` for lint+format, `pytest` for tests.
- Pydantic models for every cross-boundary payload (recommendation schema, ticket,
  queue job, ledger event). Schemas live in `pipeline/schemas.py` — single source of truth.
- Mock services are honest HTTP boundaries: pipeline code talks to them over HTTP,
  never imports their internals.
- Anthropic model via `ANTHROPIC_API_KEY` env var; default model configurable in
  `pipeline/config.py`. Recorded agent traces in `evals/traces/` keep the repo
  demoable without a key.
- Dashboard (Phase 6): Next.js App Router, deployed on Vercel; talks to a thin
  FastAPI gateway, ships a seeded demo mode.

## Build phases

Scaffold → synthetic data → mocks+ledger → NAN classifier → rules → LangGraph agent →
dashboard → evals → polish. Status tracked in README.
