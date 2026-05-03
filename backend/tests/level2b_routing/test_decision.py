"""Decision tree paths with a mocked classifier."""

from __future__ import annotations

from backend.app.level2b_routing.decision import decide
from backend.app.level2b_routing.topics import TOPICS


def _zero_scores() -> dict[str, float]:
    return {t: 0.0 for t in TOPICS}


def _zero_probs() -> dict[str, float]:
    return {t: 0.0 for t in TOPICS}


def _fail_classifier(_text: str) -> dict[str, float]:
    raise AssertionError("Classifier should not be called on the keyword path")


def test_keyword_strong_path_uses_keywords_only() -> None:
    scores = _zero_scores()
    scores["economy"] = 5.0  # one topic with a strong signal

    decision = decide(
        claim_text="dummy",
        keyword_scores=scores,
        classifier_predict_fn=_fail_classifier,
    )

    assert decision.routing_method == "keyword"
    assert decision.routed_topics == ["economy"]
    assert decision.classifier_probs == {}
    assert 0.0 < decision.routing_confidence <= 1.0


def test_classifier_path_routes_when_keyword_signal_weak() -> None:
    scores = _zero_scores()  # nothing strong

    probs = _zero_probs()
    probs["healthcare"] = 0.81
    probs["economy"] = 0.55

    def predict_fn(_text: str) -> dict[str, float]:
        return probs

    decision = decide(
        claim_text="dummy",
        keyword_scores=scores,
        classifier_predict_fn=predict_fn,
        threshold=0.5,
    )

    assert decision.routing_method == "classifier"
    assert decision.routed_topics == ["economy", "healthcare"]
    assert decision.classifier_probs == probs
    assert decision.routing_confidence > 0.5


def test_no_route_when_neither_path_fires() -> None:
    scores = _zero_scores()
    probs = _zero_probs()

    decision = decide(
        claim_text="dummy",
        keyword_scores=scores,
        classifier_predict_fn=lambda _t: probs,
        threshold=0.5,
    )

    assert decision.routing_method == "no_route"
    assert decision.routed_topics == []
    assert decision.routing_confidence == 0.0


def test_three_or_more_keyword_strong_falls_through_to_classifier() -> None:
    """If 3+ topics show strong keyword scores, treat the keyword pass as
    ambiguous and defer to the classifier (matches the documented tree)."""
    scores = _zero_scores()
    scores["immigration"] = 2.0
    scores["healthcare"] = 2.0
    scores["crime"] = 2.0

    probs = _zero_probs()
    probs["crime"] = 0.9

    decision = decide(
        claim_text="dummy",
        keyword_scores=scores,
        classifier_predict_fn=lambda _t: probs,
        threshold=0.5,
    )

    assert decision.routing_method == "classifier"
    assert decision.routed_topics == ["crime"]
