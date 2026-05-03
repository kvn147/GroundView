"""Economy domain agent (Level 3).

Migrated to ``AllowlistedAgent`` for hard permission enforcement.
The legacy ``retrieve_evidence`` / ``verify`` functions remain as
backward-compat shims so ``backend/api/video.py`` keeps working
unchanged until it opts into the structured ``VerificationResult``
return type.
"""

from __future__ import annotations

from .base import AllowlistedAgent
from .llm import get_default_llm_client

UNIVERSAL_FACT_CHECKERS = frozenset({
    "PolitiFact",
    "FactCheck.org",
    "Snopes",
    "Associated Press Fact Check",
    "Reuters Fact Check",
    "Washington Post Fact Checker",
})


class EconomyAgent(AllowlistedAgent):
    DOMAIN_NAME = "economy"
    DOMAIN_DESCRIPTION = (
        "macroeconomic indicators, fiscal/monetary policy, jobs, taxes, trade"
    )
    ALLOWED_SOURCES = UNIVERSAL_FACT_CHECKERS | frozenset({
        "BEA",
        "FRED",
        "Census Bureau",
        "BLS",
        "OECD",
        "CBO",
        "IMF",
        "Treasury Department",
        "Tax Policy Center",
    })


# ---------------------------------------------------------------------------
# Backward-compat shims for ``backend/api/video.py``.
# Once Kevin's pipeline migrates to structured ``VerificationResult``s,
# these can be removed.
# ---------------------------------------------------------------------------


_agent_singleton: EconomyAgent | None = None


def _get_agent() -> EconomyAgent:
    global _agent_singleton
    if _agent_singleton is None:
        _agent_singleton = EconomyAgent(llm=get_default_llm_client())
    return _agent_singleton


async def retrieve_evidence(claim: str) -> str:
    result = await _get_agent().verify(claim)
    return result.summary_markdown


async def verify(claim: str) -> str:
    return await retrieve_evidence(claim)
