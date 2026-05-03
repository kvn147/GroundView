"""Canonical topic IDs for Level 2b routing.

Single source of truth. Every other module in this package imports
``TOPICS`` from here — no literal topic strings allowed elsewhere.

Note: the spec in ``docs/AGENTIC_WORKFLOW.md`` references a 4-topic
taxonomy (``legislative`` / ``economy`` / ``historical_statements`` /
``policy_outcome``). The disk-state taxonomy used by the existing
agents (``backend/agents/sources.md``) is the 8 below. This module
follows disk state. The taxonomy conflict is tracked in
``docs/STRUCTURE.md`` (Known deltas, item 1).

Topic-expansion discipline rule
-------------------------------
A new topic earns a slot in this tuple ONLY if it has at least three
*authoritative* sources distinct from ``UNIVERSAL_FACT_CHECKERS`` and
distinct from every other topic's existing allowlist. The L3 agents'
job is to gate which sources may be queried — a topic without its own
authoritative source list is not a topic, it's a tag, and tags belong
in keyword tables, not in this taxonomy.

Concretely: ``personal_conduct`` failed this test (no authoritative
agency for "did the candidate ace a cognitive test"). ``legal_political``
passed (DOJ, U.S. Courts, FEC).
"""

from typing import Final

TOPICS: Final[tuple[str, ...]] = (
    "immigration",
    "healthcare",
    "crime",
    "economy",
    "education",
    "legal_political",
    "elections",
    "foreign_policy",
)
