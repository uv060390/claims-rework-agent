#!/usr/bin/env python
"""CLI for the synthetic claims-rework dataset generator.

Usage:
    uv run python data/generate_rework.py --n-requests 5000 --seed 42 --out data/demo

Writes claims.csv, rework_requests.csv, and ground_truth.csv. Ground truth is a
separate file on purpose: pipeline code reads claims + requests only.
"""

import argparse
from collections import Counter
from pathlib import Path

from pipeline.datagen.generator import SynthGenerator, write_csvs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n-requests", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, default=Path("data/demo"))
    args = parser.parse_args()

    cases = SynthGenerator(seed=args.seed).generate(args.n_requests)
    counts = write_csvs(cases, args.out)

    scenarios = Counter(c.truth.scenario_id for c in cases)
    nan_share = sum(c.truth.no_adjustment_needed for c in cases) / len(cases)
    clear_share = sum(c.truth.clear_cut for c in cases) / len(cases)
    fav_share = sum(c.truth.favorable_to_provider for c in cases) / len(cases)

    print(f"wrote {counts} to {args.out} (seed={args.seed})")
    print(
        f"no_adjustment_needed: {nan_share:.1%} | clear_cut: {clear_share:.1%} "
        f"| favorable: {fav_share:.1%}"
    )
    for name, n in scenarios.most_common():
        print(f"  {name:<40} {n:>5}  ({n / len(cases):.1%})")


if __name__ == "__main__":
    main()
