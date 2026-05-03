"""Foreign policy domain agent (Level 3). See ``agent_economy.py`` for shape.

Covers wars, treaties, sanctions, NATO, foreign aid, military
deployments, foreign leaders' actions, and intelligence findings.
Authoritative sources are U.S. national-security agencies plus
nonpartisan foreign-policy research institutions.
"""

from __future__ import annotations

from .agent_economy import UNIVERSAL_FACT_CHECKERS
from .base import AllowlistedAgent
from .llm import get_default_llm_client


class ForeignPolicyAgent(AllowlistedAgent):
    DOMAIN_NAME = "foreign_policy"
    DOMAIN_DESCRIPTION = (
        "wars, treaties, sanctions, NATO, foreign aid, military "
        "deployments, foreign leaders' actions, intelligence findings"
    )
    ALLOWED_SOURCES = UNIVERSAL_FACT_CHECKERS | frozenset({
        "State Department",
        "Department of Defense",
        "CIA World Factbook",
        "Council on Foreign Relations",
        "SIPRI",
        "NATO",
        "RAND Corporation",
        "Congressional Research Service",
    })


_agent_singleton: ForeignPolicyAgent | None = None


def _get_agent() -> ForeignPolicyAgent:
    global _agent_singleton
    if _agent_singleton is None:
        _agent_singleton = ForeignPolicyAgent(llm=get_default_llm_client())
    return _agent_singleton


async def retrieve_evidence(claim: str) -> str:
    result = await _get_agent().verify(claim)
    return result.summary_markdown


async def verify(claim: str) -> str:
    return await retrieve_evidence(claim)
