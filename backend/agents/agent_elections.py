"""Elections domain agent (Level 3). See ``agent_economy.py`` for shape.

Covers vote counts, voter registration, election fraud claims, turnout,
ballot rules, electoral college, gerrymandering, and voter ID laws.
Authoritative sources are election administrators (federal and state)
plus reputable nonpartisan election researchers.
"""

from __future__ import annotations

from .agent_economy import UNIVERSAL_FACT_CHECKERS
from .base import AllowlistedAgent
from .llm import get_default_llm_client


class ElectionsAgent(AllowlistedAgent):
    DOMAIN_NAME = "elections"
    DOMAIN_DESCRIPTION = (
        "vote counts, voter registration, election fraud, turnout, "
        "ballot rules, electoral college, gerrymandering, voter ID"
    )
    ALLOWED_SOURCES = UNIVERSAL_FACT_CHECKERS | frozenset({
        "Federal Election Commission",
        "U.S. Election Assistance Commission",
        "Brennan Center for Justice",
        "Cook Political Report",
        "MIT Election Lab",
        "Ballotpedia",
        "National Association of Secretaries of State",
    })


_agent_singleton: ElectionsAgent | None = None


def _get_agent() -> ElectionsAgent:
    global _agent_singleton
    if _agent_singleton is None:
        _agent_singleton = ElectionsAgent(llm=get_default_llm_client())
    return _agent_singleton


async def retrieve_evidence(claim: str) -> str:
    result = await _get_agent().verify(claim)
    return result.summary_markdown


async def verify(claim: str) -> str:
    return await retrieve_evidence(claim)
