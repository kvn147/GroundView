"""Pure decision tree: turn keyword scores + classifier probs into a route.

Kept separate from ``router.py`` and ``classifier.predict`` so it is
trivially testable with a mocked classifier callable. ``decide`` does
not import the classifier; the caller injects a predict function.
"""

from __future__ import annotations

from typing import Callable

from .types import RoutingDecision

ClassifierPredictFn = Callable[[str], dict[str, float]]

_KEYWORD_STRONG_THRESHOLD: float = 2.0

# Per-topic decision thresholds, picked from the LIAR-eval sweep:
# economy is over-predicted at 0.5 (precision 0.56), so push it up;
# healthcare and education peak below 0.5. immigration and crime peak
# at 0.5. Topics absent from this map fall back to ``threshold``.
TOPIC_THRESHOLDS: dict[str, float] = {
    "immigration": 0.50,
    "healthcare": 0.30,
    "crime": 0.50,
    "economy": 0.70,
    "education": 0.30,
}


def _keyword_confidence(scores: dict[str, float], routed: list[str]) -> float:
    """Average score across the routed topics, scaled into [0, 1]."""
    if not routed:
        return 0.0
    avg = sum(scores[t] for t in routed) / len(routed)
    # 4.0 is "two regex hits" — treat that as fully confident for the
    # keyword branch. Anything beyond clamps.
    return min(avg / 4.0, 1.0)


def _classifier_confidence(probs: dict[str, float], routed: list[str]) -> float:
    if not routed:
        return 0.0
    return sum(probs[t] for t in routed) / len(routed)


def decide(
    claim_text: str,
    keyword_scores: dict[str, float],
    classifier_predict_fn: ClassifierPredictFn,
    threshold: float | None = None,
) -> RoutingDecision:
    """Resolve a routing decision from keyword scores and a classifier.

    Tree:
      1. If 1–2 topics have keyword score >= 2, return them as ``keyword``.
      2. Otherwise call the classifier; route to all topics whose prob
         clears their per-topic threshold from ``TOPIC_THRESHOLDS``.
         Pass a scalar ``threshold`` to override with a single global
         cutoff (used by tests and the eval sweep).
      3. If neither path yields a topic, return ``no_route``.
    """
    strong_matches = sorted(
        t for t, s in keyword_scores.items() if s >= _KEYWORD_STRONG_THRESHOLD
    )

    if 1 <= len(strong_matches) <= 2:
        return RoutingDecision(
            claim_text=claim_text,
            routed_topics=strong_matches,
            routing_method="keyword",
            routing_confidence=_keyword_confidence(keyword_scores, strong_matches),
            keyword_scores=keyword_scores,
            classifier_probs={},
        )

    probs = classifier_predict_fn(claim_text)
    if threshold is None:
        routed = sorted(t for t, p in probs.items() if p >= TOPIC_THRESHOLDS.get(t, 0.5))
    else:
        routed = sorted(t for t, p in probs.items() if p >= threshold)

    if routed:
        return RoutingDecision(
            claim_text=claim_text,
            routed_topics=routed,
            routing_method="classifier",
            routing_confidence=_classifier_confidence(probs, routed),
            keyword_scores=keyword_scores,
            classifier_probs=probs,
        )

    return RoutingDecision(
        claim_text=claim_text,
        routed_topics=[],
        routing_method="no_route",
        routing_confidence=0.0,
        keyword_scores=keyword_scores,
        classifier_probs=probs,
    )
