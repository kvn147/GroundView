"""Structured outputs for Level 2b routing."""

from dataclasses import dataclass, field
from typing import Literal


RoutingMethod = Literal["keyword", "classifier", "no_route"]


@dataclass
class RoutingDecision:
    """Outcome of routing a single claim through Level 2b.

    ``routed_topics`` carries the canonical IDs (see ``topics.TOPICS``)
    the claim was routed to — empty list means ``no_route`` and the
    claim should flow to ``insufficient_coverage`` at Level 4b.
    """

    claim_text: str
    routed_topics: list[str]
    routing_method: RoutingMethod
    routing_confidence: float
    keyword_scores: dict[str, float] = field(default_factory=dict)
    classifier_probs: dict[str, float] = field(default_factory=dict)
