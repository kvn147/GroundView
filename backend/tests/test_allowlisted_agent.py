"""Tests for ``AllowlistedAgent`` — the L3 enforcement layer.

These tests are the demo's proof that the ConductorOne thesis is
implemented in code, not handwaved in a prompt:

  * Tier B drops non-allowlisted citations.
  * Activity log records every denial with the raw requested source.
  * Cache hit short-circuits all LLM calls.
  * Tier A short-circuits Tier B when a fact-checker verdict exists.
  * Tier A populates ``nli_source="agent"`` so judge skips NLI.
  * Parse failures and LLM errors do not crash; they show up in the log.
  * An empty allowlist refuses to instantiate (fail fast, not silent).

Tests use a fake LLM client — no network, no API key.
"""

from __future__ import annotations

import json
from typing import Optional

import pytest

from backend.agents.base import (
    AllowlistedAgent,
    InMemoryCache,
    LlmClient,
    _normalize_source,
)


# ---------------------------------------------------------------------------
# Fake LLM client
# ---------------------------------------------------------------------------


class FakeLLM:
    """Records calls and returns scripted responses keyed by model.

    ``responses[model]`` may be:
      * a string (returned every call to that model),
      * a list of strings (returned in order; raises StopIteration after),
      * an Exception (raised),
      * a sync callable (called with kwargs, returns a string),
      * an async callable (awaited, returns a string).
    """

    def __init__(self, responses: Optional[dict] = None) -> None:
        self.responses: dict = responses or {}
        self.calls: list[dict] = []
        self._iters: dict = {}

    async def complete(self, *, model: str, system: str, user: str) -> str:
        import inspect
        self.calls.append({"model": model, "system": system, "user": user})
        spec = self.responses.get(model)
        if spec is None:
            return "[]"
        if isinstance(spec, Exception):
            raise spec
        if callable(spec):
            value = spec(model=model, system=system, user=user)
            if inspect.isawaitable(value):
                return await value
            return value
        if isinstance(spec, list):
            it = self._iters.setdefault(model, iter(spec))
            return next(it)
        return spec


# ---------------------------------------------------------------------------
# Concrete agent for tests
# ---------------------------------------------------------------------------


class _EconomyAgent(AllowlistedAgent):
    DOMAIN_NAME = "economy"
    DOMAIN_DESCRIPTION = "macroeconomic indicators, fiscal policy, jobs"
    ALLOWED_SOURCES = frozenset({
        "BLS", "FRED", "BEA",
        "PolitiFact", "FactCheck.org", "Snopes",
    })


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def test_normalize_source_collapses_punctuation_and_case() -> None:
    assert _normalize_source("BLS") == "bls"
    assert _normalize_source("bls") == "bls"
    # FactCheck.org variants all collapse to the same key:
    assert _normalize_source("FactCheck.org") == "factcheckorg"
    assert _normalize_source("factcheck.org") == "factcheckorg"
    assert _normalize_source("FACT-CHECK ORG") == "factcheckorg"


# ---------------------------------------------------------------------------
# Construction guards
# ---------------------------------------------------------------------------


def test_empty_allowlist_refuses_to_construct() -> None:
    """An empty allowlist would silently drop every citation. That is
    never intentional; refuse to construct."""

    class BadAgent(AllowlistedAgent):
        DOMAIN_NAME = "bad"
        ALLOWED_SOURCES = frozenset()  # empty

    with pytest.raises(ValueError, match="ALLOWED_SOURCES"):
        BadAgent(llm=FakeLLM())


def test_missing_domain_name_refuses_to_construct() -> None:
    class BadAgent(AllowlistedAgent):
        ALLOWED_SOURCES = frozenset({"BLS"})

    with pytest.raises(ValueError, match="DOMAIN_NAME"):
        BadAgent(llm=FakeLLM())


# ---------------------------------------------------------------------------
# Tier B — the allowlist enforcement moneyshot
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tier_b_keeps_allowlisted_evidence() -> None:
    tier_a_miss = json.dumps({"checked": False})
    tier_b_payload = json.dumps([
        {"source_name": "BLS", "url": "https://bls.gov", "text": "Stat A"},
        {"source_name": "FRED", "url": "https://fred.stlouisfed.org", "text": "Stat B"},
    ])
    llm = FakeLLM(responses={
        "anthropic/claude-haiku-4-5": tier_a_miss,
        "google/gemini-2.5-flash": tier_b_payload,
    })
    agent = _EconomyAgent(llm=llm)

    result = await agent.verify("Inflation hit 9% last year.")

    assert {item.source.name for item in result.evidence_items} == {"BLS", "FRED"}
    assert set(result.queried_sources) == {"BLS", "FRED"}
    assert result.activity_log is not None
    assert result.activity_log.denied_sources == []


@pytest.mark.asyncio
async def test_tier_b_drops_non_allowlisted_citations() -> None:
    """The demo invariant: an LLM that tries to cite a source outside
    the agent's allowlist has that citation DROPPED, and the attempt
    is logged in ``denied_sources`` for the activity panel."""
    tier_a_miss = json.dumps({"checked": False})
    tier_b_payload = json.dumps([
        {"source_name": "BLS", "url": "", "text": "Allowed."},
        {"source_name": "Random Blog", "url": "", "text": "Should be dropped."},
        {"source_name": "New York Times", "url": "", "text": "Should also drop."},
    ])
    llm = FakeLLM(responses={
        "anthropic/claude-haiku-4-5": tier_a_miss,
        "google/gemini-2.5-flash": tier_b_payload,
    })
    agent = _EconomyAgent(llm=llm)

    result = await agent.verify("Some claim.")

    # Only the allowlisted item survived:
    assert len(result.evidence_items) == 1
    assert result.evidence_items[0].source.name == "BLS"

    # The two non-allowlisted requests are recorded in the audit log:
    assert result.activity_log is not None
    assert result.activity_log.denied_sources == ["Random Blog", "New York Times"]
    assert result.activity_log.queried_sources == ["BLS"]


@pytest.mark.asyncio
async def test_tier_b_normalizes_source_name_variants() -> None:
    """Gemini may return ``"factcheck.org"`` or ``"FactCheck.Org"`` —
    both must resolve to the canonical ``"FactCheck.org"`` allowlist
    entry. (Allowlist matching is normalization-aware to avoid false
    rejections from cosmetic differences.)"""
    tier_a_miss = json.dumps({"checked": False})
    tier_b_payload = json.dumps([
        {"source_name": "factcheck.org", "url": "", "text": "Stat."},
    ])
    llm = FakeLLM(responses={
        "anthropic/claude-haiku-4-5": tier_a_miss,
        "google/gemini-2.5-flash": tier_b_payload,
    })
    agent = _EconomyAgent(llm=llm)

    result = await agent.verify("Some claim.")
    assert len(result.evidence_items) == 1
    assert result.evidence_items[0].source.name == "FactCheck.org"  # canonical


@pytest.mark.asyncio
async def test_tier_b_handles_parse_failure_without_crashing() -> None:
    """If Gemini returns non-JSON garbage, the agent must log
    ``error="parse_failure"`` and return an empty result — not crash
    the pipeline."""
    tier_a_miss = json.dumps({"checked": False})
    llm = FakeLLM(responses={
        "anthropic/claude-haiku-4-5": tier_a_miss,
        "google/gemini-2.5-flash": "Sorry, I can't help with that.",
    })
    agent = _EconomyAgent(llm=llm)

    result = await agent.verify("Some claim.")
    assert result.evidence_items == []
    assert result.activity_log is not None
    assert result.activity_log.error == "parse_failure"


@pytest.mark.asyncio
async def test_tier_b_handles_llm_error_without_crashing() -> None:
    tier_a_miss = json.dumps({"checked": False})
    llm = FakeLLM(responses={
        "anthropic/claude-haiku-4-5": tier_a_miss,
        "google/gemini-2.5-flash": ConnectionError("simulated"),
    })
    agent = _EconomyAgent(llm=llm)

    result = await agent.verify("Some claim.")
    assert result.evidence_items == []
    assert result.activity_log is not None
    assert result.activity_log.error is not None
    assert "llm_error" in result.activity_log.error


@pytest.mark.asyncio
async def test_tier_b_strips_markdown_code_fences() -> None:
    tier_a_miss = json.dumps({"checked": False})
    fenced = '```json\n[{"source_name":"BLS","url":"","text":"x"}]\n```'
    llm = FakeLLM(responses={
        "anthropic/claude-haiku-4-5": tier_a_miss,
        "google/gemini-2.5-flash": fenced,
    })
    agent = _EconomyAgent(llm=llm)

    result = await agent.verify("Some claim.")
    assert len(result.evidence_items) == 1
    assert result.evidence_items[0].source.name == "BLS"


# ---------------------------------------------------------------------------
# Tier A — short-circuit + nli_source="agent"
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tier_a_hit_short_circuits_tier_b() -> None:
    tier_a_payload = json.dumps({
        "checked": True,
        "fact_checker": "PolitiFact",
        "verdict_text": "PolitiFact rated this Mostly False.",
        "url": "https://politifact.com/abc",
        "p_entail": 0.10,
        "p_contradict": 0.85,
    })
    llm = FakeLLM(responses={
        "anthropic/claude-haiku-4-5": tier_a_payload,
        "google/gemini-2.5-flash": "[]",  # would be returned if called
    })
    agent = _EconomyAgent(llm=llm)

    result = await agent.verify("Some claim.")

    # Tier A short-circuits — only the Haiku call happened:
    assert [c["model"] for c in llm.calls] == ["anthropic/claude-haiku-4-5"]
    # The evidence item is sourced from PolitiFact and pre-filled NLI:
    item = result.evidence_items[0]
    assert item.source.name == "PolitiFact"
    assert item.p_entail == 0.10
    assert item.p_contradict == 0.85
    assert item.nli_source == "agent"


@pytest.mark.asyncio
async def test_tier_a_miss_falls_through_to_tier_b() -> None:
    tier_a_miss = json.dumps({"checked": False})
    tier_b_payload = json.dumps([
        {"source_name": "BLS", "url": "", "text": "Stat."},
    ])
    llm = FakeLLM(responses={
        "anthropic/claude-haiku-4-5": tier_a_miss,
        "google/gemini-2.5-flash": tier_b_payload,
    })
    agent = _EconomyAgent(llm=llm)

    result = await agent.verify("Some claim.")
    # Both models were called:
    assert [c["model"] for c in llm.calls] == [
        "anthropic/claude-haiku-4-5",
        "google/gemini-2.5-flash",
    ]
    # And the evidence is from Tier B (BLS), with NLI unfilled:
    assert result.evidence_items[0].source.name == "BLS"
    assert result.evidence_items[0].nli_source is None


@pytest.mark.asyncio
async def test_tier_a_error_falls_through_silently() -> None:
    """If Tier A errors out, Tier B must still run — we don't fail the
    whole agent because the cheap probe was unreachable."""
    tier_b_payload = json.dumps([
        {"source_name": "BLS", "url": "", "text": "Stat."},
    ])
    llm = FakeLLM(responses={
        "anthropic/claude-haiku-4-5": ConnectionError("simulated"),
        "google/gemini-2.5-flash": tier_b_payload,
    })
    agent = _EconomyAgent(llm=llm)

    result = await agent.verify("Some claim.")
    assert len(result.evidence_items) == 1
    assert result.evidence_items[0].source.name == "BLS"


@pytest.mark.asyncio
async def test_tier_a_with_non_allowlisted_fact_checker_falls_through() -> None:
    """Tier A claims a fact-check by a source NOT in this agent's
    allowlist (e.g. ``Truthsayer Daily``). Treat as a miss — Tier B
    runs."""
    tier_a_payload = json.dumps({
        "checked": True,
        "fact_checker": "Truthsayer Daily",
        "verdict_text": "...",
        "p_entail": 0.5,
        "p_contradict": 0.5,
    })
    tier_b_payload = json.dumps([
        {"source_name": "BLS", "url": "", "text": "Stat."},
    ])
    llm = FakeLLM(responses={
        "anthropic/claude-haiku-4-5": tier_a_payload,
        "google/gemini-2.5-flash": tier_b_payload,
    })
    agent = _EconomyAgent(llm=llm)

    result = await agent.verify("Some claim.")
    # Tier B was hit (Tier A "hit" was rejected):
    assert [c["model"] for c in llm.calls] == [
        "anthropic/claude-haiku-4-5",
        "google/gemini-2.5-flash",
    ]
    assert result.evidence_items[0].source.name == "BLS"


# ---------------------------------------------------------------------------
# Cache behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_hit_skips_all_llm_calls() -> None:
    cache = InMemoryCache()
    tier_a_miss = json.dumps({"checked": False})
    tier_b_payload = json.dumps([
        {"source_name": "BLS", "url": "", "text": "Stat."},
    ])
    llm = FakeLLM(responses={
        "anthropic/claude-haiku-4-5": tier_a_miss,
        "google/gemini-2.5-flash": tier_b_payload,
    })
    agent = _EconomyAgent(llm=llm, cache=cache)

    first = await agent.verify("Some claim.")
    initial_call_count = len(llm.calls)
    second = await agent.verify("Some claim.")

    # Second call did NOT hit the LLM:
    assert len(llm.calls) == initial_call_count
    # And the second result reports cache_hit=True:
    assert first.cache_hit is False
    assert second.cache_hit is True
    # Same evidence either way:
    assert [(i.source.name, i.text) for i in first.evidence_items] == [
        (i.source.name, i.text) for i in second.evidence_items
    ]


@pytest.mark.asyncio
async def test_cache_does_not_poison_on_failure() -> None:
    """Parse failures must NOT be cached. A retry should re-attempt
    the LLM call instead of returning the bad cached result forever."""
    cache = InMemoryCache()
    tier_a_miss = json.dumps({"checked": False})
    llm = FakeLLM(responses={
        "anthropic/claude-haiku-4-5": [tier_a_miss, tier_a_miss],
        "google/gemini-2.5-flash": [
            "garbage",
            json.dumps([{"source_name": "BLS", "url": "", "text": "ok"}]),
        ],
    })
    agent = _EconomyAgent(llm=llm, cache=cache)

    first = await agent.verify("Some claim.")
    second = await agent.verify("Some claim.")

    assert first.evidence_items == []
    assert first.activity_log.error == "parse_failure"
    # Second call retried (would otherwise have returned the empty result):
    assert len(second.evidence_items) == 1
    assert second.cache_hit is False


# ---------------------------------------------------------------------------
# Activity log content
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_activity_log_records_model_used_and_prompt_hash() -> None:
    tier_a_miss = json.dumps({"checked": False})
    tier_b_payload = json.dumps([
        {"source_name": "BLS", "url": "", "text": "Stat."},
    ])
    llm = FakeLLM(responses={
        "anthropic/claude-haiku-4-5": tier_a_miss,
        "google/gemini-2.5-flash": tier_b_payload,
    })
    agent = _EconomyAgent(llm=llm)

    result = await agent.verify("Some claim.")
    log = result.activity_log
    assert log is not None
    assert log.model_used == "google/gemini-2.5-flash"
    # SHA-256 hex string — 64 chars:
    assert len(log.prompt_hash) == 64
    assert all(c in "0123456789abcdef" for c in log.prompt_hash)
    # Allowlist is sorted-deterministic so the activity panel renders consistently:
    assert log.allowed_sources == sorted(_EconomyAgent.ALLOWED_SOURCES)


@pytest.mark.asyncio
async def test_activity_log_duration_ms_is_non_negative() -> None:
    tier_a_miss = json.dumps({"checked": False})
    tier_b_payload = json.dumps([
        {"source_name": "BLS", "url": "", "text": "Stat."},
    ])
    llm = FakeLLM(responses={
        "anthropic/claude-haiku-4-5": tier_a_miss,
        "google/gemini-2.5-flash": tier_b_payload,
    })
    agent = _EconomyAgent(llm=llm)

    result = await agent.verify("Some claim.")
    assert result.duration_ms >= 0
    assert result.activity_log is not None
    assert result.activity_log.duration_ms >= 0
