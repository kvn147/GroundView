"""Legal/political domain agent (Level 3). See ``agent_economy.py`` for shape.

Covers convictions, indictments, pardons, lawsuits, court rulings,
sentencing of public figures, and federal prosecutions. Distinct from
``crime`` because the authoritative sources are court dockets and DOJ
press releases, not aggregate offense statistics.
"""

from __future__ import annotations

from .agent_economy import UNIVERSAL_FACT_CHECKERS
from .base import AllowlistedAgent
from .llm import get_default_llm_client


class LegalPoliticalAgent(AllowlistedAgent):
    DOMAIN_NAME = "legal_political"
    DOMAIN_DESCRIPTION = (
        "convictions, indictments, pardons, lawsuits, court rulings, "
        "sentencing of public figures, federal prosecutions"
    )
    ALLOWED_SOURCES = UNIVERSAL_FACT_CHECKERS | frozenset({
        "DOJ",
        "U.S. Courts",
        "PACER",
        "Federal Election Commission",
        "Office of Inspector General",
        "Congressional Research Service",
        "Supreme Court of the United States",
    })


_agent_singleton: LegalPoliticalAgent | None = None


def _get_agent() -> LegalPoliticalAgent:
    global _agent_singleton
    if _agent_singleton is None:
        _agent_singleton = LegalPoliticalAgent(llm=get_default_llm_client())
    return _agent_singleton


async def retrieve_evidence(claim: str) -> str:
    result = await _get_agent().verify(claim)
    return result.summary_markdown


async def verify(claim: str) -> str:
    return await retrieve_evidence(claim)
