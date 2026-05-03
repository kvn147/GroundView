"""Tests for ``backend/agents/aggregator.py`` — Level 4a/4b → Level 5
aggregation rules, lifted from the inline ``api/video.py`` impl.

These tests lock down the math so a future refactor doesn't silently
shift verdicts. They also confirm the L4b-rules-only invariant by
asserting the aggregator's import graph contains no LLM client.
"""

from __future__ import annotations

import importlib

import pytest

from backend.agents.aggregator import (
    _bias_to_lean,
    _score_to_trust,
    _summary_text,
    aggregate_annotations,
)
from backend.contracts import (
    AgentActivityLog,
    Annotation,
    Claim,
    EvidenceItem,
    Source,
    VerificationResult,
)


# ---------------------------------------------------------------------------
# Trust-score mapping — preserve Kevin's exact rounding behaviour
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("avg_score", "expected_trust"),
    [
        (-1.0, 1),
        (-0.6, 2),  # round((((-0.6)+1)/2)*4) + 1 = round(0.8) + 1 = 2
        (0.0, 3),
        (0.6, 4),
        (1.0, 5),
    ],
)
def test_score_to_trust_mapping(avg_score: float, expected_trust: int) -> None:
    score, _label = _score_to_trust(avg_score)
    assert score == expected_trust


def test_score_to_trust_clamps_out_of_range() -> None:
    """Even pathological inputs should clamp to 1..5."""
    score_low, _ = _score_to_trust(-99.0)
    score_high, _ = _score_to_trust(99.0)
    assert score_low == 1
    assert score_high == 5


def test_trust_labels_round_trip() -> None:
    for avg in [-0.9, -0.4, 0.0, 0.4, 0.9]:
        score, label = _score_to_trust(avg)
        assert isinstance(label, str)
        assert label  # non-empty


# ---------------------------------------------------------------------------
# Bias → political-lean mapping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("avg_bias", "expected_label"),
    [
        (-0.9, "Leans Left"),
        (-0.31, "Leans Left"),
        (-0.3, "Center / Neutral"),  # boundary: not strict less-than
        (0.0, "Center / Neutral"),
        (0.3, "Center / Neutral"),
        (0.31, "Leans Right"),
        (0.9, "Leans Right"),
    ],
)
def test_bias_to_lean_label(avg_bias: float, expected_label: str) -> None:
    label, _value = _bias_to_lean(avg_bias)
    assert label == expected_label


def test_bias_value_rescales_to_zero_one() -> None:
    """The UI uses ``value`` as a 0..1 progress-bar position."""
    _label, v_left = _bias_to_lean(-1.0)
    _label, v_mid = _bias_to_lean(0.0)
    _label, v_right = _bias_to_lean(1.0)
    assert v_left == 0.0
    assert v_mid == 0.5
    assert v_right == 1.0


# ---------------------------------------------------------------------------
# Summary text
# ---------------------------------------------------------------------------


def test_summary_text_zero_claims() -> None:
    assert "No verifiable" in _summary_text(0, "Mostly True", "Center / Neutral")


def test_summary_text_with_claims() -> None:
    text = _summary_text(3, "Mostly True", "Center / Neutral")
    assert "3 claims" in text
    assert "Mostly True" in text
    assert "center / neutral" in text  # lowercased


# ---------------------------------------------------------------------------
# Top-level aggregate
# ---------------------------------------------------------------------------


def _claim(text: str, start: float = 0.0, end: float = 5.0) -> Claim:
    return Claim(claim_text=text, raw_quote=text, start_time=start, end_time=end)


def _result(agent: str, sources: list[tuple[str, str]]) -> VerificationResult:
    return VerificationResult(
        agent=agent,
        claim_text="x",
        allowed_sources=[name for name, _ in sources],
        queried_sources=[name for name, _ in sources],
        evidence_items=[
            EvidenceItem(text="x", source=Source(name=name, url=url))
            for name, url in sources
        ],
    )


def test_aggregate_zero_annotations_returns_empty_response() -> None:
    response = aggregate_annotations([])
    assert response.claims == []
    assert response.aggregatedSources == []
    assert response.trustworthinessScore == 3  # avg_score=0 → trust=3
    assert "No verifiable" in response.summary


def test_aggregate_builds_one_frontend_claim_per_annotation() -> None:
    annotations = [
        Annotation(
            claim=_claim("Claim A"),
            results=[_result("EconomyAgent", [("BLS", "https://bls.gov")])],
            confidence_state="verified",
            final_score=0.8,
        ),
        Annotation(
            claim=_claim("Claim B"),
            results=[_result("CrimeAgent", [("FBI", "https://fbi.gov")])],
            confidence_state="contradicted",
            final_score=-0.7,
        ),
    ]
    response = aggregate_annotations(annotations)
    assert len(response.claims) == 2
    assert response.claims[0].text == "Claim A"
    assert response.claims[0].startTime == 0.0
    assert response.claims[0].endTime == 5.0
    assert response.claims[0].verdict == "True"
    assert response.claims[1].verdict == "False"
    # ID format preserves Kevin's "claim-N" convention:
    assert response.claims[0].id == "claim-1"
    assert response.claims[1].id == "claim-2"


def test_aggregate_averages_scores_across_claims() -> None:
    annotations = [
        Annotation(
            claim=_claim("A"),
            results=[_result("EconomyAgent", [("BLS", "")])],
            confidence_state="verified",
            final_score=1.0,
        ),
        Annotation(
            claim=_claim("B"),
            results=[_result("CrimeAgent", [("FBI", "")])],
            confidence_state="contradicted",
            final_score=-1.0,
        ),
    ]
    response = aggregate_annotations(annotations)
    # Avg score = 0.0 → trust = 3
    assert response.trustworthinessScore == 3


def test_aggregate_dedupes_aggregated_sources_with_counts() -> None:
    """One source cited across two claims should appear once with citedCount=2."""
    annotations = [
        Annotation(
            claim=_claim("A"),
            results=[_result("EconomyAgent", [("BLS", "https://bls.gov")])],
            confidence_state="verified",
            final_score=0.5,
        ),
        Annotation(
            claim=_claim("B"),
            results=[_result("EconomyAgent", [("BLS", "https://bls.gov")])],
            confidence_state="verified",
            final_score=0.5,
        ),
    ]
    response = aggregate_annotations(annotations)
    by_name = {s.name: s for s in response.aggregatedSources}
    assert "BLS" in by_name
    assert by_name["BLS"].citedCount == 2


def test_aggregate_preserves_bias_warning_in_explanation() -> None:
    annotation = Annotation(
        claim=_claim("X"),
        results=[_result("EconomyAgent", [("BLS", "")])],
        confidence_state="verified",
        final_score=0.5,
        bias_warning="High source bias detected.",
    )
    response = aggregate_annotations([annotation])
    assert "Fact-Checker Warning" in response.claims[0].explanation
    assert "High source bias detected" in response.claims[0].explanation


def test_aggregate_handles_empty_results_gracefully() -> None:
    """An annotation with no agent results (e.g. no_route case) should
    still produce a frontend claim with the 'no evidence' fallback."""
    annotation = Annotation(
        claim=_claim("Off-topic claim"),
        results=[],
        confidence_state="insufficient_coverage",
        final_score=0.0,
    )
    response = aggregate_annotations([annotation])
    assert len(response.claims) == 1
    assert response.claims[0].verdict == "Unverified"
    assert "No evidence" in response.claims[0].explanation


# ---------------------------------------------------------------------------
# Activity log propagation — the ConductorOne audit surface
# ---------------------------------------------------------------------------


def _result_with_log(
    agent: str,
    *,
    allowed: list[str],
    queried: list[str],
    denied: list[str],
    model: str = "google/gemini-2.5-flash",
) -> VerificationResult:
    return VerificationResult(
        agent=agent,
        claim_text="x",
        allowed_sources=allowed,
        queried_sources=queried,
        evidence_items=[
            EvidenceItem(text="x", source=Source(name=q)) for q in queried
        ],
        activity_log=AgentActivityLog(
            agent=agent,
            claim_text="x",
            allowed_sources=allowed,
            queried_sources=queried,
            denied_sources=denied,
            model_used=model,
            duration_ms=1200,
        ),
    )


def test_aggregate_propagates_activity_logs_to_frontend_claims() -> None:
    """Every per-agent ``AgentActivityLog`` must surface as a
    ``FrontendActivity`` row on the ``FrontendClaim`` — that's the
    chrome extension's activity-panel data."""
    annotation = Annotation(
        claim=_claim("Some claim"),
        results=[
            _result_with_log(
                "EconomyAgent",
                allowed=["BLS", "FRED"],
                queried=["BLS"],
                denied=["Random Blog"],
            ),
        ],
        confidence_state="verified",
        final_score=0.7,
    )
    response = aggregate_annotations([annotation])
    activity = response.claims[0].activity
    assert len(activity) == 1
    assert activity[0].agent == "EconomyAgent"
    assert activity[0].queried_sources == ["BLS"]
    assert activity[0].denied_sources == ["Random Blog"]
    assert activity[0].model_used == "google/gemini-2.5-flash"


def test_aggregate_one_activity_row_per_agent_in_multi_topic_claim() -> None:
    """A multi-label claim that fanned out to 2 agents produces 2
    activity rows under the same ``FrontendClaim``."""
    annotation = Annotation(
        claim=_claim("A claim about both economy and immigration."),
        results=[
            _result_with_log(
                "EconomyAgent",
                allowed=["BLS"],
                queried=["BLS"],
                denied=[],
            ),
            _result_with_log(
                "ImmigrationAgent",
                allowed=["USCIS"],
                queried=["USCIS"],
                denied=[],
            ),
        ],
        confidence_state="verified",
        final_score=0.5,
    )
    response = aggregate_annotations([annotation])
    activity_agents = {a.agent for a in response.claims[0].activity}
    assert activity_agents == {"EconomyAgent", "ImmigrationAgent"}


def test_aggregate_omits_activity_when_no_log_attached() -> None:
    """If a result somehow has no log (shouldn't happen in production
    but the contract allows it), the frontend claim's activity stays
    empty rather than crashing."""
    annotation = Annotation(
        claim=_claim("Some claim"),
        results=[
            VerificationResult(
                agent="EconomyAgent",
                claim_text="x",
                allowed_sources=["BLS"],
                # no activity_log set
            ),
        ],
        confidence_state="verified",
        final_score=0.5,
    )
    response = aggregate_annotations([annotation])
    assert response.claims[0].activity == []


def test_aggregate_response_is_json_serializable() -> None:
    """The chrome extension reads the response as JSON over HTTP. Adding
    new fields must not break serialization."""
    annotation = Annotation(
        claim=_claim("Some claim"),
        results=[
            _result_with_log(
                "EconomyAgent",
                allowed=["BLS"],
                queried=["BLS"],
                denied=["Random Blog"],
            ),
        ],
        confidence_state="verified",
        final_score=0.7,
    )
    response = aggregate_annotations([annotation])
    payload = response.model_dump_json()
    # Confirm the new fields are present in the wire format:
    assert "activity" in payload
    assert "denied_sources" in payload
    assert "model_used" in payload


# ---------------------------------------------------------------------------
# L4b invariant: rules-only, no LLM
# ---------------------------------------------------------------------------


def test_aggregator_does_not_import_an_llm_client() -> None:
    """AGENTIC_WORKFLOW.md mandates L4a/L4b are auditable Python rules
    with no LLM. The aggregator's import graph should reflect that."""
    aggregator = importlib.import_module("backend.agents.aggregator")
    # Walk the module's globals; no openai/AsyncOpenAI/httpx should appear.
    forbidden = {"openai", "AsyncOpenAI", "httpx", "OpenRouterLlmClient"}
    found = forbidden & set(dir(aggregator))
    assert not found, (
        f"Aggregator must not import any LLM client; found: {found}"
    )
