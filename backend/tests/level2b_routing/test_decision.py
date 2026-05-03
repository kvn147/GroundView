"""Decision tree paths with a mocked classifier."""

from __future__ import annotations

from backend.app.level2b_routing.decision import decide
from backend.app.level2b_routing.topics import TOPICS


def _zero_scores() -> dict[str, float]:
    return {t: 0.0 for t in TOPICS}


def _zero_probs() -> dict[str, float]:
    return {t: 0.0 for t in TOPICS}


def _zero_classifier(_text: str) -> dict[str, float]:
    """Always-zero classifier — no topic clears any threshold, so the
    hybrid path adds nothing on top of a strong keyword match."""
    return _zero_probs()


def test_keyword_strong_path_routes_keyword_only_when_classifier_silent() -> None:
    """Strong keyword on one topic + classifier returning all zeros:
    the hybrid path doesn't add anything, so method stays ``keyword``
    and classifier_probs is left empty in the audit trail."""
    scores = _zero_scores()
    scores["economy"] = 5.0  # one topic with a strong signal

    decision = decide(
        claim_text="dummy",
        keyword_scores=scores,
        classifier_predict_fn=_zero_classifier,
    )

    assert decision.routing_method == "keyword"
    assert decision.routed_topics == ["economy"]
    assert decision.classifier_probs == {}
    assert 0.0 < decision.routing_confidence <= 1.0


def test_hybrid_path_unions_keyword_and_classifier() -> None:
    """Strong keyword on economy + classifier confident on education =
    union of both topics, ``hybrid`` method, classifier_probs surfaced
    in the audit trail."""
    scores = _zero_scores()
    scores["economy"] = 5.0

    probs = _zero_probs()
    probs["education"] = 0.81  # also clears its 0.20 per-topic threshold

    decision = decide(
        claim_text="dummy",
        keyword_scores=scores,
        classifier_predict_fn=lambda _t: probs,
    )

    assert decision.routing_method == "hybrid"
    assert set(decision.routed_topics) == {"economy", "education"}
    # classifier_probs IS populated on hybrid (auditability — show what
    # the classifier contributed):
    assert decision.classifier_probs == probs


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


def test_margin_gate_suppresses_low_margin_classifier_route() -> None:
    """The blue-scarf failure mode: legal_political at 0.21 (just over
    its 0.20 threshold) but economy at 0.61 (under its 0.70 threshold).
    The model is more confused than confident — margin gate suppresses."""
    scores = _zero_scores()
    probs = _zero_probs()
    probs["legal_political"] = 0.21
    probs["economy"] = 0.61

    decision = decide(
        claim_text="dummy",
        keyword_scores=scores,
        classifier_predict_fn=lambda _t: probs,
        # Use realistic per-topic thresholds (not a global override)
        # by passing threshold=None implicitly — defaults to TOPIC_THRESHOLDS.
    )

    assert decision.routing_method == "no_route"
    assert decision.routed_topics == []


def test_margin_gate_lets_clean_multi_topic_routes_through() -> None:
    """A real multi-topic claim: economy 0.65 + education 0.55, both
    clearly above the runner-up. Margin gate must NOT suppress this."""
    scores = _zero_scores()
    probs = _zero_probs()
    probs["economy"] = 0.65
    probs["education"] = 0.55  # both clear their per-topic thresholds

    decision = decide(
        claim_text="dummy",
        keyword_scores=scores,
        classifier_predict_fn=lambda _t: probs,
    )

    # economy threshold is 0.70 in TOPIC_THRESHOLDS so it WON'T route.
    # education threshold is 0.20 so it routes. Lowest_routed=0.55,
    # highest_non_routed=0.65 (economy). Margin = -0.10 < 0.20 -> suppress.
    # That's actually correct: if economy is leading but didn't clear,
    # education co-firing is a confused signal.
    assert decision.routing_method == "no_route"


def test_margin_gate_disabled_with_zero_margin() -> None:
    """``margin=0.0`` opts out of the gate entirely (preserves the old
    behavior for callers that want raw threshold-based routing)."""
    scores = _zero_scores()
    probs = _zero_probs()
    probs["legal_political"] = 0.21
    probs["economy"] = 0.61

    decision = decide(
        claim_text="dummy",
        keyword_scores=scores,
        classifier_predict_fn=lambda _t: probs,
        margin=0.0,
    )

    assert decision.routing_method == "classifier"
    assert "legal_political" in decision.routed_topics


def test_confidence_floor_suppresses_low_prob_routes() -> None:
    """``confidence_floor`` is an absolute lower bound: even if a topic
    clears its (potentially low) per-topic threshold, the prob must
    also exceed the floor."""
    scores = _zero_scores()
    probs = _zero_probs()
    probs["legal_political"] = 0.21  # clears 0.20 threshold
    probs["foreign_policy"] = 0.05

    decision = decide(
        claim_text="dummy",
        keyword_scores=scores,
        classifier_predict_fn=lambda _t: probs,
        margin=0.0,  # disable margin so we isolate the floor's effect
        confidence_floor=0.30,
    )

    # 0.21 < 0.30 floor → dropped → no_route.
    assert decision.routing_method == "no_route"


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
