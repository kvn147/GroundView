"""Pure decision tree: turn keyword scores + classifier probs into a route.

Kept separate from ``router.py`` and ``classifier.predict`` so it is
trivially testable with a mocked classifier callable. ``decide`` does
not import the classifier; the caller injects a predict function.
"""

from __future__ import annotations

from typing import Callable

from .types import RoutingDecision, RoutingMethod

ClassifierPredictFn = Callable[[str], dict[str, float]]

_KEYWORD_STRONG_THRESHOLD: float = 2.0

# Per-topic decision thresholds, picked from the LIAR-eval sweep on
# the 8-topic retrain:
#
#   immigration peak F1 0.875 @ 0.45;  healthcare peak F1 0.818 @ 0.30
#   crime       peak F1 0.840 @ 0.50;  economy   peak F1 0.724 @ 0.70
#   education   peak F1 0.920 @ 0.20;  foreign_policy peak F1 0.898 @ 0.45
#   legal_political peak F1 0.585 @ 0.20  (low because of crime overlap;
#                                          model splits probability mass)
#   elections        peak F1 0.679 @ 0.35
#
# legal_political's threshold is intentionally aggressive: the per-class
# probability is diluted by overlap with ``crime`` (every criminal-justice
# claim counts as both), so a 0.5 cutoff misses 60% of true positives.
TOPIC_THRESHOLDS: dict[str, float] = {
    "immigration": 0.45,
    "healthcare": 0.30,
    "crime": 0.50,
    "economy": 0.70,
    "education": 0.20,
    "legal_political": 0.20,
    "elections": 0.35,
    "foreign_policy": 0.45,
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


# Default minimum margin between the lowest-probability *routed* topic
# and the highest-probability *non-routed* topic. When the model can't
# differentiate the routed class from the next-best class by at least
# this much, treat the prediction as confused and suppress it. Defends
# against the dominant-class failure where off-topic noise scrapes over
# a low per-topic threshold (e.g. legal_political at 0.20).
_DEFAULT_MARGIN: float = 0.20

# Higher absolute floor applied to classifier additions when the keyword
# path has already committed. Rationale: if keywords gave us a specific,
# deterministic routing, additive classifier topics should be confidently
# in (>= 0.50) — not borderline (just-cleared a low per-topic threshold).
# This avoids the felon-claim failure mode where the masked claim trips
# spurious classifier signals (immigration / elections) that get unioned
# into a clean keyword route.
_HYBRID_ADD_FLOOR: float = 0.50


def decide(
    claim_text: str,
    keyword_scores: dict[str, float],
    classifier_predict_fn: ClassifierPredictFn,
    threshold: float | None = None,
    *,
    margin: float = _DEFAULT_MARGIN,
    confidence_floor: float = 0.0,
) -> RoutingDecision:
    """Resolve a routing decision from keyword scores and a classifier.

    Tree:
      1. If 1–2 topics have keyword score >= 2, treat them as committed
         keyword routes. Then ALSO call the classifier and union any
         topics that clear their per-topic threshold (after margin gate).
         Method = ``hybrid`` when the union adds anything; ``keyword``
         when the classifier contributes nothing.
      2. If no strong keyword match, run the classifier alone; route to
         topics that clear their threshold + margin gate + confidence
         floor. Method = ``classifier``.
      3. Pass a scalar ``threshold`` to override per-topic cutoffs with a
         single global cutoff (used by tests and the eval sweep).
      4. ``margin=0.0`` disables the margin gate; ``confidence_floor=0.0``
         (default) disables the floor.
      5. If nothing routes, return ``no_route``.
    """
    strong_matches = sorted(
        t for t, s in keyword_scores.items() if s >= _KEYWORD_STRONG_THRESHOLD
    )
    keyword_committed = 1 <= len(strong_matches) <= 2

    # Always compute classifier probs — needed for the hybrid path's
    # union step and for the classifier-only path. The model is fast
    # (TF-IDF + LR), so calling it unconditionally is cheap.
    probs = classifier_predict_fn(claim_text)

    if threshold is None:
        clf_routed = sorted(
            t for t, p in probs.items() if p >= TOPIC_THRESHOLDS.get(t, 0.5)
        )
    else:
        clf_routed = sorted(t for t, p in probs.items() if p >= threshold)

    if clf_routed and confidence_floor > 0.0:
        clf_routed = [t for t in clf_routed if probs[t] >= confidence_floor]

    if clf_routed and margin > 0.0:
        routed_probs = [probs[t] for t in clf_routed]
        non_routed_probs = [p for t, p in probs.items() if t not in clf_routed]
        lowest_routed = min(routed_probs)
        highest_non_routed = max(non_routed_probs) if non_routed_probs else 0.0
        if lowest_routed - highest_non_routed < margin:
            clf_routed = []

    if keyword_committed:
        # Union keyword-committed topics with classifier topics that
        # exceed the hybrid-add floor. The floor is stricter than the
        # per-topic threshold because keywords already gave us a
        # specific, deterministic answer — additive classifier signals
        # need to be confident, not just barely-cleared.
        clf_additions = [
            t for t in clf_routed
            if t not in strong_matches and probs[t] >= _HYBRID_ADD_FLOOR
        ]
        union = sorted(set(strong_matches) | set(clf_additions))
        method: RoutingMethod = "hybrid" if clf_additions else "keyword"
        return RoutingDecision(
            claim_text=claim_text,
            routed_topics=union,
            routing_method=method,
            routing_confidence=_keyword_confidence(keyword_scores, strong_matches),
            keyword_scores=keyword_scores,
            classifier_probs=probs if method == "hybrid" else {},
        )

    if clf_routed:
        return RoutingDecision(
            claim_text=claim_text,
            routed_topics=clf_routed,
            routing_method="classifier",
            routing_confidence=_classifier_confidence(probs, clf_routed),
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
