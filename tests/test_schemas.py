from decimal import Decimal

import pytest
from pydantic import ValidationError

from pipeline.schemas import Action, Recommendation, Source


def test_recommendation_roundtrip():
    rec = Recommendation(
        action=Action.ADJUST_UP,
        adjustment_amount=Decimal("42.50"),
        rationale="Fee schedule shows contracted rate above paid amount.",
        confidence=0.91,
        favorable_to_provider=True,
        source=Source.AGENT,
    )
    assert Recommendation.model_validate_json(rec.model_dump_json()) == rec


def test_confidence_bounds_enforced():
    with pytest.raises(ValidationError):
        Recommendation(
            action=Action.NO_CHANGE,
            rationale="x",
            confidence=1.5,
            favorable_to_provider=False,
            source=Source.CLASSIFIER,
        )
