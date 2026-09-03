"""LLM judge for rationale groundedness — the semantic complement to the
deterministic identifier check in harness.check_groundedness.

Replays each committed trace and asks Claude whether every material claim in the
rationale is supported by the evidence the agent actually saw (context + tool
results). Results are written next to the traces so the eval report and CI can
consume them without an API key.

Usage:
    ANTHROPIC_API_KEY=... uv run python -m evals.judge
"""

import argparse
import json
from pathlib import Path

from pydantic import BaseModel

from evals.harness import _evidence_text, load_traces

OUT = Path("evals/traces/judge_results.jsonl")

JUDGE_PROMPT = """\
You are auditing an AI claims-triage agent for grounding. Below is the EVIDENCE the
agent had (the rework request, claim record, fee schedule, and every tool result it
retrieved), followed by its RATIONALE for a recommendation.

Judge ONLY whether the rationale is grounded: every factual assertion (amounts, codes,
dates, claim identifiers, claim states, what the records show) must be supported by
the evidence. Rules of thumb:
- General adjudication policy (e.g. the 90-day filing limit) and standard industry
  code meanings (what a CARC/CPT/POS code denotes) are domain knowledge — they need
  no evidence.
- The requester's note is evidence of WHAT THE REQUESTER ASSERTED. "The request cites
  auth AUTH-123" is grounded; "auth AUTH-123 is verified/on file" is NOT grounded
  unless a tool result confirms it.
- The agent operates under written adjudication policy you cannot see. Statements of
  the form "per policy ..." are policy references, not factual assertions — never
  flag them for lacking evidence.
Do not judge whether the recommendation is correct.

EVIDENCE:
{evidence}

RATIONALE:
{rationale}
"""


class Verdict(BaseModel):
    grounded: bool
    unsupported_assertions: list[str]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()

    from langchain_anthropic import ChatAnthropic

    from pipeline.config import ANTHROPIC_MODEL

    judge = ChatAnthropic(model=ANTHROPIC_MODEL, max_tokens=800).with_structured_output(Verdict)

    traces = load_traces()
    grounded = 0
    with args.out.open("w") as out:
        for i, trace in enumerate(traces, 1):
            prompt = JUDGE_PROMPT.format(
                evidence=_evidence_text(trace),
                rationale=trace["recommendation"]["rationale"],
            )
            try:
                verdict = judge.invoke(prompt)
            except Exception:
                verdict = judge.invoke(prompt)  # one retry on parse/API hiccup
            assert isinstance(verdict, Verdict)
            grounded += verdict.grounded
            out.write(
                json.dumps(
                    {
                        "request_id": trace["request_id"],
                        "scenario_id": trace["scenario_id"],
                        "grounded": verdict.grounded,
                        "unsupported_assertions": verdict.unsupported_assertions,
                    }
                )
                + "\n"
            )
            print(
                f"[{i}/{len(traces)}] {trace['request_id']} "
                f"{'grounded' if verdict.grounded else 'UNSUPPORTED: ' + '; '.join(verdict.unsupported_assertions)}"
            )
    print(f"\nLLM-judge grounded: {grounded}/{len(traces)}")


if __name__ == "__main__":
    main()
