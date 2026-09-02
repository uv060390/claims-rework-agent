"""Inference wrapper the orchestrator calls: predict(request, claim) -> (prob, decision).

Loads the committed artifacts so the pipeline runs without retraining. The
decision is True only when P(no_adjustment_needed) clears the high-precision
operating threshold chosen at training time (see docs/model-card.md).
"""

import json
from pathlib import Path

import pandas as pd
from xgboost import XGBClassifier

from pipeline.classifier.features import FEATURE_NAMES, build_features
from pipeline.classifier.train import ARTIFACTS_DIR


class NANClassifier:
    def __init__(self, artifacts_dir: Path = ARTIFACTS_DIR):
        meta = json.loads((artifacts_dir / "metadata.json").read_text())
        self.threshold: float = meta["threshold"]
        self.feature_names: list[str] = meta["feature_names"]
        self.model = XGBClassifier()
        self.model.load_model(artifacts_dir / "model.json")

    def predict(
        self, request: dict, claim: dict, original_claim: dict | None = None
    ) -> tuple[float, bool]:
        """Returns (P(no_adjustment_needed), auto_close_decision)."""
        features = build_features(request, claim, original_claim)
        frame = pd.DataFrame([features], columns=FEATURE_NAMES)
        prob = float(self.model.predict_proba(frame)[0, 1])
        return prob, prob >= self.threshold
