"""``AgentOrchestrator`` — L3 fan-out across topic agents.

Takes a claim and a list of routed topics (from L2b's ``RoutingDecision``
or any equivalent caller), instantiates the matching agents, and runs
them concurrently via ``asyncio.gather``. Returns a list of
``VerificationResult``s — one per topic that had an agent.

Topics with no registered agent are silently skipped; the
``unrouted_topics`` field of the return tracks them so callers can log
the gap. This is intentional: a hackathon-day topic taxonomy expansion
shouldn't crash the pipeline.

Failure handling: an individual agent may raise (it shouldn't —
``AllowlistedAgent.verify`` swallows all exceptions internally — but
defense in depth). The orchestrator catches any escaped exception,
logs it as a synthetic failed ``VerificationResult`` so the activity
panel still surfaces the failure, and lets the rest of the fan-out
complete.

Concurrency is bounded by ``max_concurrency`` (default 5). One agent
per topic, so for the 5-topic taxonomy this runs everything in
parallel by default.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Optional

from backend.contracts import (
    AgentActivityLog,
    VerificationResult,
)

from .agent_crime import CrimeAgent
from .agent_economy import EconomyAgent
from .agent_education import EducationAgent
from .agent_healthcare import HealthcareAgent
from .agent_immigration import ImmigrationAgent
from .base import AllowlistedAgent, Cache, LlmClient
from .llm import get_default_llm_client


# Topic -> Agent class. The single source of truth for which agent
# handles which topic. Add new topics here by adding a new agent class
# and an entry to this map; nothing else changes.
AGENT_REGISTRY: dict[str, type[AllowlistedAgent]] = {
    "crime": CrimeAgent,
    "economy": EconomyAgent,
    "education": EducationAgent,
    "healthcare": HealthcareAgent,
    "immigration": ImmigrationAgent,
}


@dataclass
class FanOutResult:
    """Output of one orchestrator invocation."""

    results: list[VerificationResult]
    unrouted_topics: list[str]


class AgentOrchestrator:
    """Fan-out coordinator. One instance per FastAPI process is fine —
    it caches agent singletons internally so each agent's own per-claim
    cache stays warm across requests."""

    def __init__(
        self,
        llm: Optional[LlmClient] = None,
        cache: Optional[Cache] = None,
        *,
        max_concurrency: int = 5,
        registry: Optional[dict[str, type[AllowlistedAgent]]] = None,
    ) -> None:
        self._llm = llm if llm is not None else get_default_llm_client()
        self._cache = cache  # may be None — agents construct InMemoryCache
        self._sem = asyncio.Semaphore(max_concurrency)
        self._registry = registry if registry is not None else AGENT_REGISTRY
        self._agents: dict[type[AllowlistedAgent], AllowlistedAgent] = {}

    def _get_agent(self, agent_cls: type[AllowlistedAgent]) -> AllowlistedAgent:
        """Lazy per-class singleton so each agent's cache and allowlist
        index are built once per orchestrator lifetime."""
        agent = self._agents.get(agent_cls)
        if agent is None:
            agent = agent_cls(llm=self._llm, cache=self._cache)
            self._agents[agent_cls] = agent
        return agent

    async def run(self, claim_text: str, routed_topics: list[str]) -> FanOutResult:
        """Fan out one claim across all matching agents."""
        unrouted: list[str] = []
        agents_to_run: list[AllowlistedAgent] = []
        for topic in routed_topics:
            agent_cls = self._registry.get(topic)
            if agent_cls is None:
                unrouted.append(topic)
                continue
            agents_to_run.append(self._get_agent(agent_cls))

        if not agents_to_run:
            return FanOutResult(results=[], unrouted_topics=unrouted)

        async def _bounded_verify(agent: AllowlistedAgent) -> VerificationResult:
            async with self._sem:
                try:
                    return await agent.verify(claim_text)
                except Exception as exc:  # noqa: BLE001 — defense in depth
                    # AllowlistedAgent.verify already catches its own
                    # errors, but if anything escapes (e.g. an OOM) we
                    # synthesize a failed result rather than tearing
                    # down the whole gather.
                    return _failed_result(
                        agent=type(agent).__name__,
                        claim_text=claim_text,
                        allowed_sources=sorted(agent.ALLOWED_SOURCES),
                        error=f"orchestrator_caught: {type(exc).__name__}: {exc}",
                    )

        results = await asyncio.gather(
            *(_bounded_verify(a) for a in agents_to_run)
        )
        return FanOutResult(results=list(results), unrouted_topics=unrouted)


def _failed_result(
    *,
    agent: str,
    claim_text: str,
    allowed_sources: list[str],
    error: str,
) -> VerificationResult:
    """Synthesize a ``VerificationResult`` whose activity log carries
    the failure reason. Used as a defense-in-depth fallback when an
    agent raises an exception that escaped its own ``try`` block."""
    return VerificationResult(
        agent=agent,
        claim_text=claim_text,
        allowed_sources=allowed_sources,
        queried_sources=[],
        evidence_items=[],
        activity_log=AgentActivityLog(
            agent=agent,
            claim_text=claim_text,
            allowed_sources=allowed_sources,
            error=error,
        ),
    )
