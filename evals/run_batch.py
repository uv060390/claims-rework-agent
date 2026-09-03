"""Run a batch of demo requests through the full pipeline and export a snapshot.

The snapshot powers the dashboard's demo mode (and the Vercel deployment): real
tickets, real recommendations (Claude for agent-bound cases), real ledger trails
and executed jobs — frozen as one JSON file.

Usage:
    ANTHROPIC_API_KEY=... uv run python -m evals.run_batch --n 200 \
        --out dashboard/lib/demo-snapshot.json
"""

import argparse
import csv
import json
import random
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from starlette.testclient import TestClient

from mocks.servicenow.app import TICKETS
from mocks.servicenow.app import app as servicenow_app
from mocks.uipath.app import JOBS
from mocks.uipath.app import app as uipath_app
from mocks.unet.app import app as unet_app
from pipeline.config import ANTHROPIC_MODEL
from pipeline.ledger import Ledger
from pipeline.orchestrator import Orchestrator


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=200)
    parser.add_argument("--seed", type=int, default=11)
    parser.add_argument("--out", type=Path, default=Path("dashboard/lib/demo-snapshot.json"))
    args = parser.parse_args()

    with open("data/demo/rework_requests.csv") as f:
        requests = list(csv.DictReader(f))
    by_request_id = {r["request_id"]: r for r in requests}
    sample = random.Random(args.seed).sample(requests, args.n)

    with (
        TemporaryDirectory() as tmp,
        TestClient(unet_app) as unet,
        TestClient(servicenow_app) as servicenow,
        TestClient(uipath_app) as uipath,
    ):
        uipath_app.state.unet = unet
        ledger = Ledger(f"sqlite:///{tmp}/ledger.db")
        orch = Orchestrator(unet=unet, servicenow=servicenow, uipath=uipath, ledger=ledger)

        outcomes = []
        for i, request in enumerate(sample, 1):
            outcome = orch.process(request)
            outcomes.append(outcome)
            print(
                f"[{i}/{args.n}] {outcome['request_id']} "
                f"{outcome['resolved_by']:<10} {outcome['action']:<17}"
                f"{'STP' if outcome['stp_released'] else ''}"
            )

        tickets = []
        for ticket in TICKETS.values():
            claim = unet.get(f"/claims/{ticket['claim_id']}").json()
            recommendation = None
            for note in reversed(ticket["work_notes"]):
                try:
                    recommendation = json.loads(note["note"])
                    break
                except (json.JSONDecodeError, TypeError):
                    continue
            job = next((j for j in JOBS.values() if j["ticket_id"] == ticket["sys_id"]), None)
            source_request = by_request_id[ticket["request_id"]]
            tickets.append(
                {
                    **ticket,
                    "request_note": source_request["note"],
                    "requester_type": source_request["requester_type"],
                    "has_attachment": source_request["has_attachment"],
                    "claim": claim,
                    "recommendation": recommendation,
                    "ledger": [
                        {"layer": e["layer"], "decision": e["decision"], "at": str(e["created_at"])}
                        for e in ledger.for_request(ticket["request_id"])
                    ],
                    "job": job,
                }
            )

    by_source: dict[str, int] = {}
    by_action: dict[str, int] = {}
    for o in outcomes:
        by_source[o["resolved_by"]] = by_source.get(o["resolved_by"], 0) + 1
        by_action[o["action"]] = by_action.get(o["action"], 0) + 1
    snapshot = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "model": ANTHROPIC_MODEL,
        "n": args.n,
        "metrics": {
            "by_source": by_source,
            "by_action": by_action,
            "stp_released": sum(o["stp_released"] for o in outcomes),
            "jobs_succeeded": sum(o["job_status"] == "succeeded" for o in outcomes),
            "pending_approval": sum(t["state"] == "pending_approval" for t in tickets),
        },
        "tickets": tickets,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(snapshot, indent=1))
    print(f"\nsnapshot -> {args.out}")
    print(json.dumps(snapshot["metrics"], indent=2))


if __name__ == "__main__":
    main()
