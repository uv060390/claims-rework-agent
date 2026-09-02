"""Train the No-Adjustment-Needed XGBoost classifier.

Usage:
    uv run python -m pipeline.classifier.train --data data/demo --out pipeline/classifier/artifacts

Split is grouped by provider NPI (no provider in both train and test). The
operating threshold is chosen on the held-out set for high PRECISION on the NAN
class: a false "no adjustment needed" silently closes a legitimate dispute, so
the classifier only auto-closes what it is nearly certain about.
"""

import argparse
import csv
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, precision_recall_curve, roc_auc_score
from sklearn.model_selection import GroupShuffleSplit
from xgboost import XGBClassifier

from pipeline.classifier.features import FEATURE_NAMES, build_features

ARTIFACTS_DIR = Path(__file__).parent / "artifacts"


def load_dataset(data_dir: Path) -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    """Returns (features, labels, provider groups) for every rework request."""
    with (data_dir / "claims.csv").open() as f:
        claims = {row["claim_id"]: row for row in csv.DictReader(f)}
    with (data_dir / "ground_truth.csv").open() as f:
        truth = {row["request_id"]: row for row in csv.DictReader(f)}

    rows, labels, groups = [], [], []
    with (data_dir / "rework_requests.csv").open() as f:
        for request in csv.DictReader(f):
            claim = claims[request["claim_id"]]
            original = claims.get(claim["original_claim_id"]) or None
            rows.append(build_features(request, claim, original))
            labels.append(int(truth[request["request_id"]]["no_adjustment_needed"] == "True"))
            groups.append(claim["provider_npi"])
    return pd.DataFrame(rows, columns=FEATURE_NAMES), np.array(labels), np.array(groups)


def pick_threshold(y_true: np.ndarray, probs: np.ndarray, target_precision: float) -> float:
    """Smallest threshold reaching the target precision on the NAN class."""
    precision, _, thresholds = precision_recall_curve(y_true, probs)
    ok = np.where(precision[:-1] >= target_precision)[0]
    if len(ok) == 0:
        return float(thresholds[np.argmax(precision[:-1])])
    return float(thresholds[ok[0]])


def train(
    data_dir: Path,
    out_dir: Path = ARTIFACTS_DIR,
    *,
    n_estimators: int = 200,
    seed: int = 42,
    target_precision: float = 0.99,
) -> dict:
    X, y, groups = load_dataset(data_dir)
    splitter = GroupShuffleSplit(n_splits=1, test_size=0.25, random_state=seed)
    train_idx, test_idx = next(splitter.split(X, y, groups))

    model = XGBClassifier(
        n_estimators=n_estimators,
        max_depth=4,
        learning_rate=0.1,
        eval_metric="aucpr",
        random_state=seed,
    )
    model.fit(X.iloc[train_idx], y[train_idx])
    probs = model.predict_proba(X.iloc[test_idx])[:, 1]
    y_test = y[test_idx]

    threshold = pick_threshold(y_test, probs, target_precision)
    decisions = probs >= threshold
    metrics = {
        "n_train": int(len(train_idx)),
        "n_test": int(len(test_idx)),
        "nan_base_rate": float(y.mean()),
        "pr_auc": float(average_precision_score(y_test, probs)),
        "roc_auc": float(roc_auc_score(y_test, probs)),
        "threshold": threshold,
        "target_precision": target_precision,
        "precision_at_threshold": float((y_test[decisions] == 1).mean())
        if decisions.any()
        else 0.0,
        "recall_at_threshold": float(decisions[y_test == 1].mean()),
        "auto_close_share": float(decisions.mean()),
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    model.save_model(out_dir / "model.json")
    (out_dir / "metadata.json").write_text(
        json.dumps({"feature_names": FEATURE_NAMES, **metrics}, indent=2)
    )
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("data/demo"))
    parser.add_argument("--out", type=Path, default=ARTIFACTS_DIR)
    parser.add_argument("--target-precision", type=float, default=0.99)
    args = parser.parse_args()
    metrics = train(args.data, args.out, target_precision=args.target_precision)
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
