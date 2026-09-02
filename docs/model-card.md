# Model card — No-Adjustment-Needed (NAN) classifier

## Intended use

First gate of the Recommend-then-Release pipeline. Predicts whether a rework request
needs **no adjustment** (the payment or denial already stands correctly). Requests
clearing a high-precision threshold auto-close with action `no_change`; everything
else flows to the rules engine and, if still unresolved, the LLM triage agent. The
classifier can only ever produce `no_change` — it cannot trigger an adjustment
(see `AGENTS.md`).

**This model is trained on synthetic data** (`data/demo/`, see the
[data dictionary](data-dictionary.md)) and exists to demonstrate the production
architecture. Its metrics describe performance on that synthetic distribution only.

## Model

- XGBoost binary classifier (`XGBClassifier`, 200 trees, depth 4, lr 0.1).
- Label: `no_adjustment_needed` — derived as `correct_action ∈ {no_change, uphold_denial}`.
- 44 features from the request row, the disputed claim, and the referenced original
  claim (`pipeline/classifier/features.py`): amount relationships (paid vs allowed
  deltas/ratios), denial CARC one-hots, claim status, timely-filing lag, telehealth
  POS/modifier signals, requester type, resubmission count, attachment flag, and
  original-claim disposition. **Never** the free-text note, and nothing label-derived.

## Evaluation protocol

- Split grouped by `provider_npi` (`GroupShuffleSplit`, 25% held out): no provider
  appears in both train and test, so provider-specific patterns cannot leak.
- Operating threshold chosen on the held-out set as the smallest threshold reaching
  **≥99% precision** on the NAN class. The cost asymmetry drives this: a false
  "no adjustment needed" silently closes a legitimate dispute (money owed to a
  provider disappears), while a false "needs work" merely costs one rules/agent pass.

## Results (seed 42, frozen demo set: 3,716 train / 1,284 test)

| Metric | Value |
|---|---|
| PR-AUC (NAN class) | 0.989 |
| ROC-AUC | 0.991 |
| Operating threshold | 0.892 |
| Precision @ threshold | 99.1% |
| Recall @ threshold | 77.8% |
| Share of ALL requests auto-closed | 34.7% |

Reading: the classifier auto-closes about a third of total queue volume at ~99%
precision. The ~22% of true NAN cases it declines to auto-close are the genuinely
ambiguous ones (e.g., a timely-filing appeal where only the note text reveals whether
proof of timely submission exists) — exactly the cases the downstream agent reads.

## Known failure modes & limitations

- **Attachment-flag ambiguity is irreducible here by design**: hopeless appeals
  sometimes carry (irrelevant) attachments and valid exceptions sometimes lack them,
  so structurally identical timely-filing/authorization cases have opposite labels.
  The model correctly expresses uncertainty on these instead of guessing.
- Only 20 synthetic providers exist, so provider-level aggregate features
  (denial-rate history) were deliberately omitted; in production they were among the
  stronger signals.
- Fee-schedule amounts are a single global schedule; contract-specific pricing would
  make underpayment detection materially harder than it is here.
- Retraining reproduces byte-identical artifacts only with the same seed, dataset,
  and xgboost version (pinned in `uv.lock`).

## Reproduce

```bash
uv run python -m pipeline.classifier.train --data data/demo --out pipeline/classifier/artifacts
```
