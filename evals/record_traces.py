"""Record real Claude triage traces on agent-bound cases from the demo dataset.

Selects requests the classifier declines to auto-close AND the rules engine
cannot resolve (i.e., exactly the traffic the agent sees in production), samples
them stratified by scenario, runs the real LangGraph + Claude agent against
in-process mocks, and writes a JSONL trace per case. Committed traces let the
repo demonstrate agent behavior — and let evals replay — without an API key.

Usage:
    ANTHROPIC_API_KEY=... uv run python -m evals.record_traces --per-scenario 5
"""

import argparse
import csv
import json
import random
from collections import defaultdict
from pathlib import Path

from starlette.testclient import TestClient

from mocks.servicenow.app import app as servicenow_app
from mocks.unet.app import app as unet_app
from pipeline.agent.graph import run_triage
from pipeline.classifier.infer import NANClassifier
from pipeline.config import ANTHROPIC_MODEL
from pipeline.rules.engine import RulesEngine

DATA = Path("data/demo")
OUT = Path("evals/traces/traces.jsonl")


def _serialize_message(m) -> dict:
    entry: dict = {"role": m.type}
    if isinstance(m.content, str) and m.content:
        entry["content"] = m.content
    elif isinstance(m.content, list):  # anthropic content blocks
        text = " ".join(b.get("text", "") for b in m.content if isinstance(b, dict))
        if text.strip():
            entry["content"] = text.strip()
    calls = getattr(m, "tool_calls", None)
    if calls:
        entry["tool_calls"] = [{"name": c["name"], "args": c["args"]} for c in calls]
    if m.type == "tool":
        entry["tool"] = m.name
    return entry


def agent_bound_requests() -> tuple[dict, dict, list[dict]]:
    """The residual queue: not auto-closed, not rules-resolved."""
    with (DATA / "claims.csv").open() as f:
        claims = {r["claim_id"]: r for r in csv.DictReader(f)}
    with (DATA / "ground_truth.csv").open() as f:
        truth = {r["request_id"]: r for r in csv.DictReader(f)}
    classifier, rules = NANClassifier(), RulesEngine()

    residual = []
    with (DATA / "rework_requests.csv").open() as f:
        for request in csv.DictReader(f):
            claim = claims[request["claim_id"]]
            original = claims.get(claim["original_claim_id"]) or None
            if classifier.predict(request, claim, original)[1]:
                continue
            if rules.evaluate(request, claim, original) is not None:
                continue
            residual.append(request)
    return claims, truth, residual


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--per-scenario", type=int, default=5)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()

    claims, truth, residual = agent_bound_requests()
    print(f"agent-bound residual queue: {len(residual)}/5000")

    by_scenario: dict[str, list[dict]] = defaultdict(list)
    for request in residual:
        by_scenario[truth[request["request_id"]]["scenario_id"]].append(request)
    rng = random.Random(args.seed)
    sample = [
        r
        for scenario in sorted(by_scenario)
        for r in rng.sample(
            by_scenario[scenario], min(args.per_scenario, len(by_scenario[scenario]))
        )
    ]
    print(f"sampled {len(sample)} cases across {len(by_scenario)} scenarios")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    correct = 0
    with (
        TestClient(unet_app) as unet,
        TestClient(servicenow_app) as servicenow,
        args.out.open("w") as out,
    ):
        for i, request in enumerate(sample, 1):
            claim = claims[request["claim_id"]]
            t = truth[request["request_id"]]
            rec, trace = run_triage(request, claim, unet=unet, servicenow=servicenow)
            match = rec.action.value == t["correct_action"]
            correct += match
            out.write(
                json.dumps(
                    {
                        "request_id": request["request_id"],
                        "scenario_id": t["scenario_id"],
                        "model": ANTHROPIC_MODEL,
                        "messages": [_serialize_message(m) for m in trace],
                        "recommendation": rec.model_dump(mode="json"),
                        "correct_action": t["correct_action"],
                        "correct_adjustment_amount": t["correct_adjustment_amount"] or None,
                        "action_correct": match,
                    }
                )
                + "\n"
            )
            print(
                f"[{i}/{len(sample)}] {t['scenario_id']:<40} "
                f"{rec.action.value:<16} {'OK' if match else 'MISS'}"
            )
    print(f"\naction accuracy on sample: {correct}/{len(sample)} = {correct / len(sample):.1%}")


if __name__ == "__main__":
    main()
