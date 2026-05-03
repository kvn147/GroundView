"""Healthcare domain agent (Level 3). See ``agent_economy.py`` for shape."""

from __future__ import annotations

from .agent_economy import UNIVERSAL_FACT_CHECKERS
from .base import AllowlistedAgent
from .llm import get_default_llm_client


class HealthcareAgent(AllowlistedAgent):
    DOMAIN_NAME = "healthcare"
    DOMAIN_DESCRIPTION = (
        "Medicare, Medicaid, ACA, hospitals, FDA, drug pricing, mental health"
    )
    ALLOWED_SOURCES = UNIVERSAL_FACT_CHECKERS | frozenset({
        "CDC",
        "NIH",
        "WHO",
        "BLS",
        "KFF",
    })


_agent_singleton: HealthcareAgent | None = None


def _get_agent() -> HealthcareAgent:
    global _agent_singleton
    if _agent_singleton is None:
        _agent_singleton = HealthcareAgent(llm=get_default_llm_client())
    return _agent_singleton


async def retrieve_evidence(claim: str) -> str:
    result = await _get_agent().verify(claim)
    return result.summary_markdown


async def verify(claim: str) -> str:
    return await retrieve_evidence(claim)
