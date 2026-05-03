"""Tests for the OpinionAgent and the media_bias allowlist loader.

Mirrors the structure of ``test_allowlisted_agent.py`` — mock LLM client,
verify the agent fills in ``EvidenceItem.stance``, enforces the
``media_bias.csv`` allowlist, and skips Tier A entirely.
"""

from __future__ import annotations

import json
import sys
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

# Stub openai before agent imports — the OpinionAgent module-imports
# ``llm.get_default_llm_client`` which constructs an ``AsyncOpenAI``.
if "openai" not in sys.modules:
    openai_stub = ModuleType("openai")

    class AsyncOpenAI:
        def __init__(self, *args, **kwargs):
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=lambda *a, **kw: None)
            )

    openai_stub.AsyncOpenAI = AsyncOpenAI
    sys.modules["openai"] = openai_stub

from backend.agents.agent_opinion import OpinionAgent
from backend.agents.media_bias import (
    load_outlet_allowlist,
    resolve_alias,
)


# ---------------------------------------------------------------------------
# Fake LLM client
# ---------------------------------------------------------------------------


class FakeLlm:
    """Minimal mock of the ``LlmClient`` protocol.

    Records each ``complete`` call so tests can assert on prompts; returns
    a queued response (string).  ``raises`` short-circuits with the given
    exception type instead.
    """

    def __init__(
        self,
        response: str | list[str] = "[]",
        raises: type[BaseException] | None = None,
    ) -> None:
        if isinstance(response, str):
            self._responses = [response]
        else:
            self._responses = list(response)
        self._raises = raises
        self.calls: list[dict[str, Any]] = []

    async def complete(self, *, model: str, system: str, user: str) -> str:
        self.calls.append({"model": model, "system": system, "user": user})
        if self._raises is not None:
            raise self._raises("simulated failure")
        if not self._responses:
            return ""
        return self._responses.pop(0)


# ---------------------------------------------------------------------------
# media_bias loader / aliases
# ---------------------------------------------------------------------------


def test_allowlist_is_nonempty_frozenset() -> None:
    allowlist = load_outlet_allowlist()
    assert isinstance(allowlist, frozenset)
    assert len(allowlist) > 0


def test_allowlist_contains_known_anchors() -> None:
    """A handful of canonical entries we explicitly depend on."""
    allowlist = load_outlet_allowlist()
    for expected in (
        "The Atlantic",
        "The Daily Wire",
        "Reuters",
        "BBC News",
        "Wall Street Journal (News)",
        "Fox News Digital",
    ):
        assert expected in allowlist, f"Missing canonical entry: {expected}"


def test_allowlist_lru_cached_returns_same_object() -> None:
    a = load_outlet_allowlist()
    b = load_outlet_allowlist()
    assert a is b  # lru_cache returns the same frozenset


def test_alias_resolves_npr() -> None:
    assert resolve_alias("npr") == "NPR (Online News)"


def test_alias_resolves_wall_street_journal() -> None:
    assert resolve_alias("wallstreetjournal") == "Wall Street Journal (News)"
    assert resolve_alias("wsj") == "Wall Street Journal (News)"


def test_alias_resolves_fox() -> None:
    assert resolve_alias("foxnews") == "Fox News Digital"


def test_alias_returns_none_for_unknown() -> None:
    assert resolve_alias("randomunknownoutlet") is None


def test_alias_targets_are_in_csv_allowlist() -> None:
    """An alias that resolves to an outlet not in the CSV is a bug —
    every alias target must itself be a canonical entry."""
    allowlist = load_outlet_allowlist()
    # Probe a known set of aliases (don't iterate the private dict —
    # this test is a contract, not a structural check).
    for normalized in ("npr", "wsj", "foxnews", "cnn", "nbc", "bbc"):
        target = resolve_alias(normalized)
        assert target is not None
        assert target in allowlist, f"Alias {normalized!r} → {target!r} not in CSV"


# ---------------------------------------------------------------------------
# OpinionAgent — Tier A skip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tier_a_returns_none_no_llm_call() -> None:
    """The OpinionAgent overrides Tier A to a no-op. The LLM client
    should not be called for Tier A even with a non-trivial claim."""
    llm = FakeLlm(response="[]")  # only Tier B might fire
    agent = OpinionAgent(llm=llm)

    result = await agent._run_tier_a("We need stronger borders.")
    assert result is None
    # No LLM call recorded for Tier A
    tier_a_calls = [c for c in llm.calls if "fact-checked" in c["system"].lower()]
    assert tier_a_calls == []


@pytest.mark.asyncio
async def test_verify_skips_tier_a_calls_only_tier_b() -> None:
    llm = FakeLlm(response="[]")
    agent = OpinionAgent(llm=llm)

    await agent.verify("We need stronger borders.")
    # Exactly one LLM call total (Tier B), and it uses the Gemini model
    assert len(llm.calls) == 1
    assert llm.calls[0]["model"] == agent.TIER_B_MODEL


# ---------------------------------------------------------------------------
# OpinionAgent — Tier B happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tier_b_parses_stance_evidence() -> None:
    payload = json.dumps(
        [
            {
                "outlet": "The Atlantic",
                "stance": "disagree",
                "summary": "Atlantic editorial argues against tighter borders.",
                "url": "https://theatlantic.com/x",
            },
            {
                "outlet": "The Daily Wire",
                "stance": "agree",
                "summary": "Daily Wire op-ed endorses border enforcement.",
                "url": "https://dailywire.com/x",
            },
        ]
    )
    llm = FakeLlm(response=payload)
    agent = OpinionAgent(llm=llm)

    result = await agent.verify("We need stronger borders.")

    assert len(result.evidence_items) == 2
    stances = {item.source.name: item.stance for item in result.evidence_items}
    assert stances["The Atlantic"] == "disagree"
    assert stances["The Daily Wire"] == "agree"
    # NLI source is None — judge.calculate_lean_structured uses stance,
    # not NLI probabilities
    for item in result.evidence_items:
        assert item.nli_source is None


@pytest.mark.asyncio
async def test_tier_b_unverifiable_stance_preserved() -> None:
    payload = json.dumps(
        [
            {
                "outlet": "Reuters",
                "stance": "unverifiable",
                "summary": "Reuters covered the policy debate without endorsing.",
            }
        ]
    )
    llm = FakeLlm(response=payload)
    agent = OpinionAgent(llm=llm)
    result = await agent.verify("We need stronger borders.")
    assert len(result.evidence_items) == 1
    assert result.evidence_items[0].stance == "unverifiable"


@pytest.mark.asyncio
async def test_tier_b_queried_sources_recorded() -> None:
    payload = json.dumps(
        [
            {
                "outlet": "The Atlantic",
                "stance": "disagree",
                "summary": "X.",
            },
            {
                "outlet": "The Daily Wire",
                "stance": "agree",
                "summary": "Y.",
            },
        ]
    )
    llm = FakeLlm(response=payload)
    agent = OpinionAgent(llm=llm)
    result = await agent.verify("Opinion text.")
    assert sorted(result.queried_sources) == ["The Atlantic", "The Daily Wire"]
    assert result.activity_log is not None
    assert sorted(result.activity_log.queried_sources) == [
        "The Atlantic",
        "The Daily Wire",
    ]


# ---------------------------------------------------------------------------
# OpinionAgent — allowlist enforcement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_disallowed_outlet_dropped_and_logged() -> None:
    payload = json.dumps(
        [
            {
                "outlet": "RandomBlog.com",
                "stance": "agree",
                "summary": "A blog endorsing the position.",
            },
            {
                "outlet": "The Atlantic",
                "stance": "disagree",
                "summary": "Allowed evidence.",
            },
        ]
    )
    llm = FakeLlm(response=payload)
    agent = OpinionAgent(llm=llm)
    result = await agent.verify("Opinion text.")

    # Only the allowlisted outlet contributes evidence
    assert len(result.evidence_items) == 1
    assert result.evidence_items[0].source.name == "The Atlantic"

    # Denied outlet logged (raw name, for audit transparency)
    assert result.activity_log is not None
    assert "RandomBlog.com" in result.activity_log.denied_sources


@pytest.mark.asyncio
async def test_alias_resolves_npr_via_enforcement() -> None:
    """LLM emits "NPR" — the parenthetical-suffix CSV entry resolves via alias."""
    payload = json.dumps(
        [
            {
                "outlet": "NPR",
                "stance": "agree",
                "summary": "NPR coverage endorsing the position.",
            }
        ]
    )
    llm = FakeLlm(response=payload)
    agent = OpinionAgent(llm=llm)
    result = await agent.verify("Opinion text.")
    assert len(result.evidence_items) == 1
    assert result.evidence_items[0].source.name == "NPR (Online News)"


@pytest.mark.asyncio
async def test_alias_resolves_fox_via_enforcement() -> None:
    payload = json.dumps(
        [
            {
                "outlet": "Fox News",
                "stance": "agree",
                "summary": "Fox News opinion piece.",
            }
        ]
    )
    llm = FakeLlm(response=payload)
    agent = OpinionAgent(llm=llm)
    result = await agent.verify("Opinion text.")
    assert len(result.evidence_items) == 1
    assert result.evidence_items[0].source.name == "Fox News Digital"


# ---------------------------------------------------------------------------
# OpinionAgent — failure modes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_stance_value_dropped() -> None:
    """Stance must be one of agree/disagree/unverifiable — anything else dropped."""
    payload = json.dumps(
        [
            {
                "outlet": "The Atlantic",
                "stance": "maybe",
                "summary": "Shouldn't slip through.",
            }
        ]
    )
    llm = FakeLlm(response=payload)
    agent = OpinionAgent(llm=llm)
    result = await agent.verify("Opinion text.")
    assert result.evidence_items == []


@pytest.mark.asyncio
async def test_missing_summary_drops_item() -> None:
    payload = json.dumps(
        [
            {
                "outlet": "The Atlantic",
                "stance": "agree",
                # no summary
            }
        ]
    )
    llm = FakeLlm(response=payload)
    agent = OpinionAgent(llm=llm)
    result = await agent.verify("Opinion text.")
    assert result.evidence_items == []


@pytest.mark.asyncio
async def test_parse_failure_logged_no_evidence() -> None:
    llm = FakeLlm(response="not valid JSON at all")
    agent = OpinionAgent(llm=llm)
    result = await agent.verify("Opinion text.")
    assert result.evidence_items == []
    assert result.activity_log is not None
    assert result.activity_log.error == "parse_failure"


@pytest.mark.asyncio
async def test_llm_error_logged_no_evidence() -> None:
    llm = FakeLlm(raises=RuntimeError)
    agent = OpinionAgent(llm=llm)
    result = await agent.verify("Opinion text.")
    assert result.evidence_items == []
    assert result.activity_log is not None
    assert result.activity_log.error is not None
    assert result.activity_log.error.startswith("llm_error:")


@pytest.mark.asyncio
async def test_non_list_top_level_is_parse_failure() -> None:
    """Tier B must return a JSON array. Object-at-root → parse_failure."""
    llm = FakeLlm(response='{"outlet": "X"}')
    agent = OpinionAgent(llm=llm)
    result = await agent.verify("Opinion text.")
    assert result.evidence_items == []
    assert result.activity_log.error == "parse_failure"


# ---------------------------------------------------------------------------
# OpinionAgent — caching + activity log shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_hit_skips_second_llm_call() -> None:
    payload = json.dumps(
        [{"outlet": "The Atlantic", "stance": "agree", "summary": "X."}]
    )
    llm = FakeLlm(response=[payload, payload])
    agent = OpinionAgent(llm=llm)

    first = await agent.verify("Same opinion.")
    second = await agent.verify("Same opinion.")

    assert len(llm.calls) == 1, "second call should hit cache"
    assert first.evidence_items == second.evidence_items
    assert second.cache_hit is True


@pytest.mark.asyncio
async def test_activity_log_carries_model_and_prompt_hash() -> None:
    payload = json.dumps(
        [{"outlet": "The Atlantic", "stance": "agree", "summary": "X."}]
    )
    llm = FakeLlm(response=payload)
    agent = OpinionAgent(llm=llm)
    result = await agent.verify("Some opinion.")
    log = result.activity_log
    assert log is not None
    assert log.model_used == agent.TIER_B_MODEL
    assert log.prompt_hash != ""
    assert log.allowed_sources == sorted(agent.ALLOWED_SOURCES)
