"""Canonical topic IDs for Level 2b routing.

Single source of truth. Every other module in this package imports
``TOPICS`` from here — no literal topic strings allowed elsewhere.

Note: the spec in ``docs/AGENTIC_WORKFLOW.md`` references a 4-topic
taxonomy (``legislative`` / ``economy`` / ``historical_statements`` /
``policy_outcome``). The disk-state taxonomy used by the existing
agents (``backend/agents/sources.md``) is the 5 below. This module
follows disk state. The taxonomy conflict is tracked in
``docs/STRUCTURE.md`` (Known deltas, item 1).
"""

from typing import Final

TOPICS: Final[tuple[str, ...]] = (
    "immigration",
    "healthcare",
    "crime",
    "economy",
    "education",
)
