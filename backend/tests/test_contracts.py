"""Locks down the cross-level data contracts.

Three groups of tests:

  1. Round-trip serialization — the contract survives JSON.
  2. Adapter shape — the legacy consumers (``judge.py`` and the chrome
     extension) get the dict shapes they expect.
  3. Permission-audit invariants — ``allowed_sources`` /
     ``queried_sources`` semantics are stable so the L3 base class
     can enforce them.
"""

from __future__ import annotations

import pytest

from backend.contracts import (
    AgentActivityLog,
    Annotation,
    AnalyzeVideoResponse,
    Claim,
    EvidenceItem,
    FrontendActivity,
    FrontendAggregatedSource,
    FrontendClaim,
    FrontendSource,
    ScoredSource,
    Source,
    VerificationResult,
    aggregate_frontend_sources,
    render_evidence_markdown,
    to_frontend_activity,
    to_frontend_sources,
    to_judge_evidence_items,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _bls_source() -> Source:
    return Source(
        name="Bureau of Labor Statistics",
        url="https://www.bls.gov/news.release/empsit.nr0.htm",
    )


def _factcheck_source() -> Source:
    return Source(
        name="FactCheck.org",
        url="https://www.factcheck.org",
    )


def _sample_claim() -> Claim:
    return Claim(
        claim_text="The unemployment rate has doubled under the current administration.",
        raw_quote="…the unemployment rate has doubled under the current administration…",
        speaker="Speaker A",
        start_time=12.0,
        end_time=18.5,
        topics=["economy"],
        verifiability="structured_data",
        extraction_confidence=0.9,
    )


def _sample_result() -> VerificationResult:
    return VerificationResult(
        agent="EconomyAgent",
        claim_text=_sample_claim().claim_text,
        allowed_sources=["Bureau of Labor Statistics", "FactCheck.org"],
        queried_sources=["Bureau of Labor Statistics", "FactCheck.org"],
        evidence_items=[
            EvidenceItem(
                text="The unemployment rate increased by 0.8 percentage points, not 100%.",
                source=_bls_source(),
                p_entail=0.05,
                p_contradict=0.85,
                nli_source="judge",
            ),
            EvidenceItem(
                text="FactCheck.org rates the doubling claim as exaggerated.",
                source=_factcheck_source(),
                p_entail=0.10,
                p_contradict=0.75,
                nli_source="agent",
            ),
        ],
        cache_hit=False,
        duration_ms=1240,
    )


# ---------------------------------------------------------------------------
# 1. Round-trip serialization
# ---------------------------------------------------------------------------


def test_verification_result_round_trips_through_json() -> None:
    original = _sample_result()
    rebuilt = VerificationResult.model_validate_json(original.model_dump_json())
    assert rebuilt == original


def test_annotation_round_trips_through_json() -> None:
    annotation = Annotation(
        claim=_sample_claim(),
        results=[_sample_result()],
        confidence_state="contradicted",
        final_score=-0.7,
    )
    rebuilt = Annotation.model_validate_json(annotation.model_dump_json())
    assert rebuilt == annotation


def test_analyze_video_response_uses_frontend_field_names() -> None:
    """The chrome extension reads `trustworthinessScore`, `politicalLean`,
    etc. The Pydantic model must serialize with those exact keys."""
    response = AnalyzeVideoResponse()
    payload = response.model_dump()
    expected_keys = {
        "summary",
        "trustworthinessScore",
        "maxScore",
        "trustworthinessLabel",
        "politicalLean",
        "claims",
        "aggregatedSources",
    }
    assert expected_keys <= set(payload.keys())


def test_frontend_claim_serializes_timestamp_fields() -> None:
    claim = FrontendClaim(
        id="claim-1",
        text="Example claim",
        startTime=12.0,
        endTime=18.5,
        verdict="True",
        explanation="Example explanation",
    )
    payload = claim.model_dump()
    assert payload["startTime"] == 12.0
    assert payload["endTime"] == 18.5


# ---------------------------------------------------------------------------
# 2. Adapter shape
# ---------------------------------------------------------------------------


def test_judge_adapter_emits_legacy_shape() -> None:
    """``judge.calculate_confidence`` expects ``[{source, text}]``."""
    items = to_judge_evidence_items(_sample_result())
    assert items == [
        {
            "source": "Bureau of Labor Statistics",
            "text": "The unemployment rate increased by 0.8 percentage points, not 100%.",
        },
        {
            "source": "FactCheck.org",
            "text": "FactCheck.org rates the doubling claim as exaggerated.",
        },
    ]


def test_judge_adapter_handles_empty_evidence() -> None:
    result = VerificationResult(
        agent="EconomyAgent",
        claim_text="x",
        allowed_sources=["BLS"],
    )
    assert to_judge_evidence_items(result) == []


def test_frontend_sources_dedupe_by_name() -> None:
    """Two evidence items from the same source should produce one
    ``FrontendSource`` — the chrome extension renders ``sources``
    as a deduped list."""
    bls = _bls_source()
    result = VerificationResult(
        agent="EconomyAgent",
        claim_text="x",
        allowed_sources=["BLS"],
        evidence_items=[
            EvidenceItem(text="first stat", source=bls),
            EvidenceItem(text="second stat", source=bls),
        ],
    )
    fs = to_frontend_sources(result)
    assert len(fs) == 1
    assert fs[0].name == "Bureau of Labor Statistics"
    assert fs[0].url == "https://www.bls.gov/news.release/empsit.nr0.htm"


def test_frontend_sources_prefers_non_empty_url() -> None:
    bls_no_url = Source(name="BLS", url=None)
    bls_with_url = Source(name="BLS", url="https://bls.gov")
    result = VerificationResult(
        agent="EconomyAgent",
        claim_text="x",
        allowed_sources=["BLS"],
        evidence_items=[
            EvidenceItem(text="a", source=bls_no_url),
            EvidenceItem(text="b", source=bls_with_url),
        ],
    )
    fs = to_frontend_sources(result)
    assert len(fs) == 1
    assert fs[0].url == "https://bls.gov"


def test_aggregated_sources_count_across_annotations() -> None:
    """``aggregatedSources`` is the cross-claim citation tally rendered
    at the top of the extension card."""
    ann1 = Annotation(claim=_sample_claim(), results=[_sample_result()])
    ann2 = Annotation(claim=_sample_claim(), results=[_sample_result()])

    aggregated = aggregate_frontend_sources([ann1, ann2])
    by_name = {a.name: a for a in aggregated}
    assert by_name["Bureau of Labor Statistics"].citedCount == 2
    assert by_name["FactCheck.org"].citedCount == 2


# ---------------------------------------------------------------------------
# 3. Permission-audit invariants (the ConductorOne lever)
# ---------------------------------------------------------------------------


def test_allowed_and_queried_sources_default_to_lists() -> None:
    """Defaults must be safe to iterate without ``None`` checks."""
    log = AgentActivityLog(
        agent="EconomyAgent",
        claim_text="x",
        allowed_sources=["BLS"],
    )
    assert log.queried_sources == []
    assert log.denied_sources == []
    assert log.cache_hit is False


def test_activity_log_records_denial() -> None:
    log = AgentActivityLog(
        agent="LegislativeAgent",
        claim_text="x",
        allowed_sources=["ProPublica Congress API"],
        queried_sources=["ProPublica Congress API"],
        denied_sources=["PolitiFact"],
        cache_hit=False,
        duration_ms=120,
    )
    assert "PolitiFact" in log.denied_sources
    # Round-trip through JSON because the activity panel reads JSON.
    rebuilt = AgentActivityLog.model_validate_json(log.model_dump_json())
    assert rebuilt.denied_sources == ["PolitiFact"]


def test_verification_result_carries_audit_fields() -> None:
    result = _sample_result()
    # The L3 base class will check this invariant: every queried source
    # must be in the allowlist. The model itself doesn't enforce it
    # (the base class does), but the fields exist so it can.
    assert set(result.queried_sources) <= set(result.allowed_sources)


def test_activity_log_carries_replay_fields() -> None:
    """``model_used`` + ``prompt_hash`` together make every verdict
    replayable: same hash, same model, same call."""
    log = AgentActivityLog(
        agent="EconomyAgent",
        claim_text="x",
        allowed_sources=["BLS"],
        queried_sources=["BLS"],
        cache_hit=False,
        duration_ms=1180,
        model_used="google/gemini-2.5-flash",
        prompt_hash="a3c8f1...",
    )
    assert log.model_used == "google/gemini-2.5-flash"
    assert log.prompt_hash == "a3c8f1..."
    assert log.error is None


def test_activity_log_records_errors() -> None:
    log = AgentActivityLog(
        agent="EconomyAgent",
        claim_text="x",
        allowed_sources=["BLS"],
        error="parse_failure: Gemini returned non-JSON",
    )
    assert log.error is not None
    rebuilt = AgentActivityLog.model_validate_json(log.model_dump_json())
    assert rebuilt.error == log.error


# ---------------------------------------------------------------------------
# Derived markdown — agents cannot author free prose
# ---------------------------------------------------------------------------


def test_summary_markdown_is_computed_from_evidence() -> None:
    """Agents fill ``evidence_items``; ``summary_markdown`` is derived.
    No LLM in the rendering path — every word ties to a structured item."""
    result = _sample_result()
    md = result.summary_markdown
    assert "Bureau of Labor Statistics" in md
    assert "FactCheck.org" in md
    # The exact stat from the structured evidence appears verbatim:
    assert "0.8 percentage points" in md


def test_summary_markdown_handles_empty_evidence() -> None:
    result = VerificationResult(
        agent="EconomyAgent",
        claim_text="x",
        allowed_sources=["BLS"],
    )
    assert "_No evidence retrieved._" in result.summary_markdown


def test_render_evidence_markdown_includes_urls_when_present() -> None:
    items = [
        EvidenceItem(text="stat A", source=Source(name="BLS", url="https://bls.gov")),
        EvidenceItem(text="stat B", source=Source(name="Anonymous Outlet")),
    ]
    md = render_evidence_markdown(items)
    assert "[source](https://bls.gov)" in md
    assert "Anonymous Outlet" in md
    # Bare-source line should not have a broken markdown link:
    assert "[source]()" not in md


def test_summary_markdown_serializes_in_json_dump() -> None:
    """Computed fields must appear in JSON output — the chrome
    extension reads ``summary_markdown`` over the wire."""
    result = _sample_result()
    payload = result.model_dump()
    assert "summary_markdown" in payload
    assert "Bureau of Labor Statistics" in payload["summary_markdown"]


def test_summary_markdown_is_not_writable() -> None:
    """``computed_field`` is a read-only property. Even after
    construction an agent can't overwrite the rendered prose with
    free text — Pydantic raises on assignment."""
    result = _sample_result()
    with pytest.raises(Exception):
        result.summary_markdown = "### Handcrafted prose"  # type: ignore[misc]


def test_summary_markdown_input_is_ignored_at_construction() -> None:
    """An agent that *passes* ``summary_markdown=...`` at construction
    has it silently dropped. The output reflects the structured
    evidence, not the agent's free text. (Pydantic's default behavior
    is to ignore unknown inputs; the computed property always wins.)"""
    result = VerificationResult(
        agent="EconomyAgent",
        claim_text="x",
        allowed_sources=["BLS"],
        evidence_items=[
            EvidenceItem(text="real stat", source=Source(name="BLS")),
        ],
        summary_markdown="### Hostile free prose with no source",  # type: ignore[call-arg]
    )
    # The hostile string was discarded; the rendered output references
    # the actual structured source.
    assert "Hostile free prose" not in result.summary_markdown
    assert "BLS" in result.summary_markdown
    assert "real stat" in result.summary_markdown


# ---------------------------------------------------------------------------
# NLI source discriminator — the LLM-call-saving lever
# ---------------------------------------------------------------------------


def test_nli_source_defaults_to_none() -> None:
    """When the agent doesn't pre-fill NLI, the field is None and the
    judge knows to compute it."""
    item = EvidenceItem(text="x", source=Source(name="BLS"))
    assert item.nli_source is None


def test_nli_source_agent_means_judge_should_skip() -> None:
    """Agents pre-fill NLI when the source is verdict-bearing
    (PolitiFact, FactCheck.org). The judge sees this flag and skips
    the NLI Gemini call — saving an LLM round-trip per item."""
    item = EvidenceItem(
        text="PolitiFact rated this Mostly False.",
        source=Source(name="PolitiFact"),
        p_entail=0.10,
        p_contradict=0.85,
        nli_source="agent",
    )
    assert item.nli_source == "agent"
    assert item.p_entail is not None and item.p_contradict is not None


def test_nli_source_only_accepts_known_values() -> None:
    """Literal type — only ``agent`` or ``judge`` allowed."""
    with pytest.raises(Exception):
        EvidenceItem(
            text="x",
            source=Source(name="BLS"),
            nli_source="hacker",  # not in the literal
        )


# ---------------------------------------------------------------------------
# Activity log → frontend adapter
# ---------------------------------------------------------------------------


def test_to_frontend_activity_omits_internal_fields() -> None:
    """``FrontendActivity`` is the slim shape the chrome extension renders.
    Internal fields (``prompt_hash``, ``timestamp``) stay backend-side."""
    log = AgentActivityLog(
        agent="EconomyAgent",
        claim_text="x",
        allowed_sources=["BLS"],
        queried_sources=["BLS"],
        denied_sources=["NYTimes"],
        cache_hit=False,
        duration_ms=1180,
        model_used="google/gemini-2.5-flash",
        prompt_hash="a3c8f1...",
    )
    result = VerificationResult(
        agent="EconomyAgent",
        claim_text="x",
        allowed_sources=["BLS"],
        activity_log=log,
    )
    fa = to_frontend_activity(result)
    assert fa is not None
    fields = set(fa.model_dump().keys())
    # User-facing audit fields are present:
    assert {
        "agent", "allowed_sources", "queried_sources", "denied_sources",
        "cache_hit", "model_used", "duration_ms", "error",
    } <= fields
    # Internal fields are NOT serialized to the frontend:
    assert "prompt_hash" not in fields
    assert "timestamp" not in fields
    assert "claim_text" not in fields


def test_to_frontend_activity_returns_none_when_no_log() -> None:
    result = VerificationResult(
        agent="EconomyAgent",
        claim_text="x",
        allowed_sources=["BLS"],
        # no activity_log
    )
    assert to_frontend_activity(result) is None


def test_frontend_claim_activity_defaults_to_empty_list() -> None:
    """Adding the ``activity`` field must not break callers that don't
    populate it. Default is empty list, not None."""
    fc = FrontendClaim(id="claim-1", text="x", verdict="True", explanation="y")
    assert fc.activity == []
    # JSON serialization includes the new field with the empty default:
    payload = fc.model_dump()
    assert payload["activity"] == []


def test_frontend_claim_activity_round_trips() -> None:
    activity = [
        FrontendActivity(
            agent="EconomyAgent",
            allowed_sources=["BLS", "FRED"],
            queried_sources=["BLS"],
            denied_sources=["Random Blog"],
            cache_hit=False,
            model_used="google/gemini-2.5-flash",
            duration_ms=1240,
        ),
    ]
    fc = FrontendClaim(
        id="claim-1",
        text="x",
        verdict="True",
        explanation="y",
        activity=activity,
    )
    rebuilt = FrontendClaim.model_validate_json(fc.model_dump_json())
    assert rebuilt == fc


def test_agent_source_has_no_trust_or_bias_fields() -> None:
    """Agents physically cannot self-attest trust/bias scores. Those
    fields belong on ``ScoredSource``, which only the judge produces."""
    fields = set(Source.model_fields.keys())
    assert "trust" not in fields
    assert "bias" not in fields
    assert fields == {"name", "url"}


def test_scored_source_carries_trust_and_bias() -> None:
    """``ScoredSource`` is the judge-side enriched shape."""
    ss = ScoredSource(name="BLS", url="https://bls.gov", trust=1.0, bias=0.0)
    assert ss.trust == 1.0
    assert ss.bias == 0.0
    # ScoredSource IS-A Source: anywhere a Source is expected, a
    # ScoredSource works (Liskov substitution).
    assert isinstance(ss, Source)


def test_scored_source_requires_trust_and_bias() -> None:
    """Trust and bias are mandatory on ``ScoredSource`` — the judge's
    registry resolves them, so it's never legitimate to leave blank."""
    with pytest.raises(Exception):
        ScoredSource(name="BLS", url="https://bls.gov")  # missing fields
