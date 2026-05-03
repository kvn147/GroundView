"""Keyword matcher: one fixture per topic, expect that topic to win."""

from __future__ import annotations

import pytest

from backend.app.level2b_routing.keyword_matcher import score_keywords
from backend.app.level2b_routing.topics import TOPICS


# (claim_text, expected_dominant_topic)
CASES: list[tuple[str, str]] = [
    (
        "ICE deported 1,200 migrants under Title 42 last week at the border.",
        "immigration",
    ),
    (
        "Medicare and Medicaid spending on prescription drugs rose for the third year, "
        "the FDA said.",
        "healthcare",
    ),
    (
        "The FBI's UCR data show the violent crime rate fell, even as homicides rose "
        "in three cities.",
        "crime",
    ),
    (
        "Inflation hit 8% and the Federal Reserve raised interest rates; GDP grew "
        "$1.2 trillion.",
        "economy",
    ),
    (
        "Student loan forgiveness will reach 40 million borrowers, the Dept. of "
        "Education said about Pell Grant recipients at public universities.",
        "education",
    ),
]


@pytest.mark.parametrize(("claim", "expected_topic"), CASES)
def test_dominant_topic_wins(claim: str, expected_topic: str) -> None:
    scores = score_keywords(claim)
    assert set(scores.keys()) == set(TOPICS)
    winner = max(scores, key=lambda t: scores[t])
    assert winner == expected_topic, f"Expected {expected_topic} dominant, got {scores}"
    assert scores[expected_topic] >= 2.0, (
        f"Expected strong (>=2.0) score on {expected_topic}, got {scores[expected_topic]}"
    )


def test_empty_claim_scores_all_zero() -> None:
    scores = score_keywords("")
    assert all(v == 0.0 for v in scores.values())
    assert set(scores.keys()) == set(TOPICS)


def test_off_topic_claim_scores_low() -> None:
    scores = score_keywords("She wore a blue scarf to the wedding on Saturday.")
    assert max(scores.values()) < 2.0
