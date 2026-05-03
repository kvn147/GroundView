"""Deterministic keyword-pass scoring over the topic tables."""

from __future__ import annotations

from .keyword_tables import TABLES
from .topics import TOPICS


def score_keywords(claim_text: str) -> dict[str, float]:
    """Return per-topic keyword scores for ``claim_text``.

    Score = (count of distinct keyword hits) + 2 * (count of regex hits).
    Keyword matching is case-insensitive substring; regex patterns may
    encode their own casing rules. Every canonical topic appears in the
    output, with score 0.0 when nothing matched.
    """
    lowered = claim_text.lower()
    scores: dict[str, float] = {topic: 0.0 for topic in TOPICS}

    for topic, table in TABLES.items():
        keyword_hits = 0
        for kw in table["keywords"]:
            if kw in lowered:
                keyword_hits += 1

        regex_hits = 0
        for pattern in table["regex_patterns"]:
            if pattern.search(claim_text):
                regex_hits += 1

        scores[topic] = float(keyword_hits) + 2.0 * float(regex_hits)

    return scores
