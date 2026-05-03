"""Immigration domain agent (Level 3). See ``agent_economy.py`` for shape."""

from __future__ import annotations

from .agent_economy import UNIVERSAL_FACT_CHECKERS
from .base import AllowlistedAgent
from .llm import get_default_llm_client


class ImmigrationAgent(AllowlistedAgent):
    DOMAIN_NAME = "immigration"
    DOMAIN_DESCRIPTION = (
        "border, asylum, visa, ICE, USCIS, deportation, refugees"
    )
    ALLOWED_SOURCES = UNIVERSAL_FACT_CHECKERS | frozenset({
        "USCIS",
        "Migration Policy Institute",
        "Pew Research Center",
        "UNHCR",
        "BLS",
        "Customs and Border Protection",
    })


_agent_singleton: ImmigrationAgent | None = None


def _get_agent() -> ImmigrationAgent:
    global _agent_singleton
    if _agent_singleton is None:
        _agent_singleton = ImmigrationAgent(llm=get_default_llm_client())
    return _agent_singleton


async def retrieve_evidence(claim: str) -> str:
    result = await _get_agent().verify(claim)
    return result.summary_markdown


async def verify(claim: str) -> str:
    return await retrieve_evidence(claim)
