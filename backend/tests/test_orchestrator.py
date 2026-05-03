"""Tests for ``AgentOrchestrator`` — L3 fan-out behaviour.

These cover:

  * Multi-topic fan-out produces one ``VerificationResult`` per topic.
  * Concurrency: agents run in parallel via ``asyncio.gather``.
  * Topics without a registered agent flow into ``unrouted_topics``,
    not into a crash.
  * Defense-in-depth: an agent that escapes its own try/except yields
    a synthesized failed result, not a torn-down gather.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from backend.agents.base import AllowlistedAgent
from backend.agents.orchestrator import AgentOrchestrator, AGENT_REGISTRY
from backend.tests.test_allowlisted_agent import FakeLLM


@pytest.mark.asyncio
async def test_single_topic_runs_one_agent() -> None:
    fake = FakeLLM(responses={
        "anthropic/claude-haiku-4-5": json.dumps({"checked": False}),
        "google/gemini-2.5-flash": json.dumps([
            {"source_name": "BLS", "url": "", "text": "Stat."},
        ]),
    })
    orch = AgentOrchestrator(llm=fake)

    out = await orch.run("Some claim.", routed_topics=["economy"])

    assert len(out.results) == 1
    assert out.results[0].agent == "EconomyAgent"
    assert out.unrouted_topics == []


@pytest.mark.asyncio
async def test_multi_topic_runs_one_agent_per_topic() -> None:
    fake = FakeLLM(responses={
        "anthropic/claude-haiku-4-5": json.dumps({"checked": False}),
        "google/gemini-2.5-flash": json.dumps([
            {"source_name": "BLS", "url": "", "text": "Stat."},
        ]),
    })
    orch = AgentOrchestrator(llm=fake)

    out = await orch.run(
        "Claim that touches both economy and immigration.",
        routed_topics=["economy", "immigration"],
    )

    assert len(out.results) == 2
    agents = {r.agent for r in out.results}
    assert agents == {"EconomyAgent", "ImmigrationAgent"}


@pytest.mark.asyncio
async def test_unrouted_topic_is_recorded_not_crashed() -> None:
    """A topic that doesn't map to a registered agent (e.g. a future
    addition like ``environment``) must not crash the pipeline."""
    fake = FakeLLM(responses={
        "anthropic/claude-haiku-4-5": json.dumps({"checked": False}),
        "google/gemini-2.5-flash": json.dumps([
            {"source_name": "BLS", "url": "", "text": "Stat."},
        ]),
    })
    orch = AgentOrchestrator(llm=fake)

    out = await orch.run("X.", routed_topics=["economy", "environment"])

    assert len(out.results) == 1
    assert out.results[0].agent == "EconomyAgent"
    assert out.unrouted_topics == ["environment"]


@pytest.mark.asyncio
async def test_empty_routed_topics_returns_empty() -> None:
    """No-route from L2b means no agents to run — return cleanly."""
    orch = AgentOrchestrator(llm=FakeLLM())
    out = await orch.run("Claim with no topics.", routed_topics=[])
    assert out.results == []
    assert out.unrouted_topics == []


@pytest.mark.asyncio
async def test_agents_run_concurrently_not_serially() -> None:
    """Sanity check: with two slow agents and ``max_concurrency >= 2``,
    total wall time should be ~slow_time, not ~2 * slow_time."""

    async def slow_responder(*, model, system, user):
        await asyncio.sleep(0.1)
        if "economy" in system or "macroeconomic" in system:
            return json.dumps([{"source_name": "BLS", "url": "", "text": "x"}])
        if "immigration" in system or "border" in system:
            return json.dumps([{"source_name": "USCIS", "url": "", "text": "x"}])
        return json.dumps({"checked": False})

    fake = FakeLLM(responses={
        "anthropic/claude-haiku-4-5": slow_responder,
        "google/gemini-2.5-flash": slow_responder,
    })
    orch = AgentOrchestrator(llm=fake, max_concurrency=5)

    start = asyncio.get_event_loop().time()
    out = await orch.run("X.", routed_topics=["economy", "immigration"])
    elapsed = asyncio.get_event_loop().time() - start

    assert len(out.results) == 2
    # Each agent must have actually produced evidence (proves the slow
    # path executed end-to-end, not the synthesized-failure fallback):
    assert all(len(r.evidence_items) >= 1 for r in out.results)
    # Each agent makes ≥2 LLM calls × 0.1s each. Serial would be ≥0.8s;
    # concurrent should be roughly half that. Generous bound for CI noise:
    assert elapsed < 0.6, f"Expected concurrent execution; took {elapsed:.2f}s"


@pytest.mark.asyncio
async def test_orchestrator_catches_unexpected_agent_exceptions() -> None:
    """Defense-in-depth: even if an agent's own try/except is bypassed
    somehow, the orchestrator must not let the exception tear down the
    fan-out."""

    class ExplodingAgent(AllowlistedAgent):
        DOMAIN_NAME = "exploding"
        ALLOWED_SOURCES = frozenset({"BLS"})

        async def verify(self, claim_text):  # type: ignore[override]
            raise RuntimeError("agent imploded")

    custom_registry = {"exploding": ExplodingAgent, "economy": AGENT_REGISTRY["economy"]}
    fake = FakeLLM(responses={
        "anthropic/claude-haiku-4-5": json.dumps({"checked": False}),
        "google/gemini-2.5-flash": json.dumps([
            {"source_name": "BLS", "url": "", "text": "x"},
        ]),
    })
    orch = AgentOrchestrator(llm=fake, registry=custom_registry)

    out = await orch.run("X.", routed_topics=["exploding", "economy"])

    # Both ran — one exploded, one succeeded:
    assert len(out.results) == 2
    by_agent = {r.agent: r for r in out.results}
    assert by_agent["ExplodingAgent"].evidence_items == []
    assert by_agent["ExplodingAgent"].activity_log is not None
    assert by_agent["ExplodingAgent"].activity_log.error is not None
    assert "orchestrator_caught" in by_agent["ExplodingAgent"].activity_log.error
    # The healthy agent still produced evidence:
    assert len(by_agent["EconomyAgent"].evidence_items) == 1


@pytest.mark.asyncio
async def test_orchestrator_caches_agent_instances_per_class() -> None:
    """Same agent class invoked twice in different orchestrator calls
    should reuse the same instance (so its in-memory cache survives)."""
    fake = FakeLLM(responses={
        "anthropic/claude-haiku-4-5": json.dumps({"checked": False}),
        "google/gemini-2.5-flash": json.dumps([
            {"source_name": "BLS", "url": "", "text": "x"},
        ]),
    })
    orch = AgentOrchestrator(llm=fake)

    await orch.run("Claim A.", routed_topics=["economy"])
    initial_calls = len(fake.calls)

    # Same claim, same agent, second call — cache hits inside the agent:
    await orch.run("Claim A.", routed_topics=["economy"])

    # No new LLM calls on the second invocation (cache hit at agent level):
    assert len(fake.calls) == initial_calls
