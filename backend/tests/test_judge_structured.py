"""Tests for ``calculate_confidence_structured`` — the contract-aware
variant of ``calculate_confidence`` that consumes ``EvidenceItem``s
directly and skips NLI calls when the agent pre-filled probabilities.

The math is identical to ``calculate_confidence``, so these tests
focus on the *plumbing differences*:

  * NLI is NOT called when ``nli_source == "agent"``.
  * NLI IS called when ``nli_source is None``.
  * The output shape matches the legacy function so callers can swap.
"""

from __future__ import annotations

import pytest

from backend.agents import judge as judge_mod
from backend.agents.judge import (
    NLIResult,
    calculate_confidence_structured,
)
from backend.contracts import EvidenceItem, Source


# ---------------------------------------------------------------------------
# NLI call-count instrumentation
# ---------------------------------------------------------------------------


@pytest.fixture
def stubbed_nli(monkeypatch):
    """Replace ``get_nli_probabilities`` with a counter-fake."""
    state = {"calls": 0}

    async def fake(claim, evidence, *args, **kwargs):
        state["calls"] += 1
        # Default neutral output; tests can monkeypatch further if needed.
        return NLIResult(p_entail=0.5, p_contradict=0.5)

    monkeypatch.setattr(judge_mod, "get_nli_probabilities", fake)
    return state


# ---------------------------------------------------------------------------
# Skip-on-agent-NLI invariant
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_skips_nli_when_agent_already_provided(stubbed_nli) -> None:
    items = [
        EvidenceItem(
            text="PolitiFact rated this Mostly False.",
            source=Source(name="PolitiFact"),
            p_entail=0.10,
            p_contradict=0.85,
            nli_source="agent",
        ),
    ]
    result = await calculate_confidence_structured("X", items)
    assert stubbed_nli["calls"] == 0  # zero LLM calls
    # The agent-provided probabilities flowed through:
    detail = result["details"][0]
    assert detail["p_entail"] == 0.10
    assert detail["p_contradict"] == 0.85
    assert detail["nli_origin"] == "agent"


@pytest.mark.asyncio
async def test_calls_nli_when_agent_did_not_provide(stubbed_nli) -> None:
    items = [
        EvidenceItem(
            text="Some statistic.",
            source=Source(name="BLS"),
            nli_source=None,
        ),
    ]
    await calculate_confidence_structured("X", items)
    assert stubbed_nli["calls"] == 1


@pytest.mark.asyncio
async def test_mixed_items_only_calls_nli_for_unfilled(stubbed_nli) -> None:
    items = [
        EvidenceItem(
            text="PolitiFact verdict",
            source=Source(name="PolitiFact"),
            p_entail=0.1,
            p_contradict=0.8,
            nli_source="agent",
        ),
        EvidenceItem(
            text="BLS stat",
            source=Source(name="BLS"),
            nli_source=None,
        ),
        EvidenceItem(
            text="FRED stat",
            source=Source(name="FRED"),
            nli_source=None,
        ),
    ]
    await calculate_confidence_structured("X", items)
    # 1 agent-filled (skipped) + 2 unfilled (called) = 2 NLI calls
    assert stubbed_nli["calls"] == 2


# ---------------------------------------------------------------------------
# Output shape parity with calculate_confidence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_output_has_same_keys_as_legacy(stubbed_nli) -> None:
    """Callers should be able to swap ``calculate_confidence`` for
    ``calculate_confidence_structured`` without changing key access."""
    items = [
        EvidenceItem(
            text="x",
            source=Source(name="BLS"),
            p_entail=0.5,
            p_contradict=0.5,
            nli_source="agent",
        ),
    ]
    result = await calculate_confidence_structured("X", items)
    expected_keys = {
        "final_score",
        "verdict",
        "wes",
        "average_bias",
        "bias_penalty",
        "warning",
        "details",
    }
    assert expected_keys <= set(result.keys())


@pytest.mark.asyncio
async def test_empty_evidence_returns_unverified(stubbed_nli) -> None:
    result = await calculate_confidence_structured("X", [])
    assert result["verdict"] == "Unverified"
    assert result["final_score"] == 0.0
    assert stubbed_nli["calls"] == 0


# ---------------------------------------------------------------------------
# Verdict thresholds (preserves legacy behaviour)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_strong_entailment_yields_true_verdict(stubbed_nli, monkeypatch) -> None:
    items = [
        EvidenceItem(
            text="x",
            source=Source(name="BLS"),
            p_entail=0.95,
            p_contradict=0.05,
            nli_source="agent",
        ),
    ]
    result = await calculate_confidence_structured("X", items)
    # final_score is in (0.6, 1.0] → verdict "True"
    assert result["final_score"] > 0.6
    assert result["verdict"] == "True"


@pytest.mark.asyncio
async def test_strong_contradiction_yields_false_verdict(stubbed_nli) -> None:
    items = [
        EvidenceItem(
            text="x",
            source=Source(name="BLS"),
            p_entail=0.05,
            p_contradict=0.95,
            nli_source="agent",
        ),
    ]
    result = await calculate_confidence_structured("X", items)
    assert result["final_score"] < -0.6
    assert result["verdict"] == "False"
