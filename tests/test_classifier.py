import csv
import math
from pathlib import Path

from pipeline.classifier.features import FEATURE_NAMES, build_features
from pipeline.classifier.infer import NANClassifier
from pipeline.classifier.train import load_dataset, train

DATA = Path("data/demo")


def _rows():
    with (DATA / "claims.csv").open() as f:
        claims = {r["claim_id"]: r for r in csv.DictReader(f)}
    with (DATA / "ground_truth.csv").open() as f:
        truth = {r["request_id"]: r for r in csv.DictReader(f)}
    with (DATA / "rework_requests.csv").open() as f:
        requests = list(csv.DictReader(f))
    return claims, truth, requests


def test_features_complete_and_numeric():
    claims, _, requests = _rows()
    for request in requests[:200]:
        claim = claims[request["claim_id"]]
        original = claims.get(claim["original_claim_id"]) or None
        features = build_features(request, claim, original)
        assert list(features) == FEATURE_NAMES
        assert all(isinstance(v, float) and math.isfinite(v) for v in features.values())


def test_dataset_loads_with_provider_groups():
    X, y, groups = load_dataset(DATA)
    assert len(X) == len(y) == len(groups) == 5000
    assert set(y) == {0, 1}
    assert 1 < len(set(groups)) <= 20


def test_train_smoke_meets_quality_bar(tmp_path):
    metrics = train(DATA, tmp_path, n_estimators=60)
    assert metrics["pr_auc"] > 0.95
    assert metrics["precision_at_threshold"] >= 0.98
    assert (tmp_path / "model.json").exists() and (tmp_path / "metadata.json").exists()


def test_committed_artifacts_predict_sensibly():
    clf = NANClassifier()
    claims, truth, requests = _rows()

    def prob_for(scenario: str) -> float:
        request = next(r for r in requests if truth[r["request_id"]]["scenario_id"] == scenario)
        claim = claims[request["claim_id"]]
        original = claims.get(claim["original_claim_id"]) or None
        prob, _ = clf.predict(request, claim, original)
        assert 0.0 <= prob <= 1.0
        return prob

    # a correct payment under dispute is a textbook NAN; a fee-schedule
    # underpayment plainly needs an adjustment
    assert prob_for("correct_payment_dispute") > prob_for("underpaid_fee_schedule")


def test_decision_respects_threshold():
    clf = NANClassifier()
    claims, _, requests = _rows()
    for request in requests[:100]:
        claim = claims[request["claim_id"]]
        prob, decision = clf.predict(request, claim, claims.get(claim["original_claim_id"]))
        assert decision == (prob >= clf.threshold)
