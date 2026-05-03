"""Pipeline aggregator (Level 4a/4b → Level 5 prep).

Pure, no I/O, no LLM. Consumes a list of ``Annotation``s — one per
claim, each carrying its ``VerificationResult``s and judge-computed
``final_score`` / ``average_bias`` — and produces the
``AnalyzeVideoResponse`` shape the chrome extension expects.

The math (trust-score mapping, bias thresholds, label table) is
preserved verbatim from the inline implementation that previously
lived in ``backend/api/video.py``, so the user-visible output is
unchanged. Lifting it here means:

  * The route handler stays thin (orchestration, not arithmetic).
  * The aggregation rules are unit-testable in isolation.
  * AGENTIC_WORKFLOW.md's L4b "rules-only, no LLM, auditable"
    invariant is observable in code: this module imports nothing
    from any LLM client.
"""

from __future__ import annotations

from typing import Optional

from backend.contracts import (
    AnalyzeVideoResponse,
    Annotation,
    FrontendAggregatedSource,
    FrontendClaim,
    PoliticalLean,
    aggregate_frontend_sources,
    to_frontend_activity,
    to_frontend_sources,
)


# ---------------------------------------------------------------------------
# Per-claim adapter
# ---------------------------------------------------------------------------


def _claim_explanation(annotation: Annotation, idx: int) -> str:
    """Render the per-claim explanation. Concatenates the agent
    summaries (which themselves are computed from structured evidence,
    not free LLM prose) and appends a bias warning if present."""
    parts: list[str] = []
    for result in annotation.results:
        if result.summary_markdown:
            parts.append(result.summary_markdown)
    body = "\n\n".join(parts) if parts else "_No evidence retrieved._"
    if annotation.bias_warning:
        body = f"{body}\n\n**Fact-Checker Warning:** {annotation.bias_warning}"
    return body


def _claim_to_frontend(
    annotation: Annotation, idx: int
) -> FrontendClaim:
    sources_dedup: dict[str, dict[str, str]] = {}
    activity_rows = []
    for result in annotation.results:
        for fs in to_frontend_sources(result):
            sources_dedup.setdefault(fs.name, {"name": fs.name, "url": fs.url})
            # Prefer non-empty URL if a later occurrence has one:
            if not sources_dedup[fs.name]["url"] and fs.url:
                sources_dedup[fs.name]["url"] = fs.url
        activity = to_frontend_activity(result)
        if activity is not None:
            activity_rows.append(activity)
    return FrontendClaim(
        id=f"claim-{idx + 1}",
        text=annotation.claim.claim_text,
        verdict=_verdict_label_from_state(annotation),
        explanation=_claim_explanation(annotation, idx),
        sources=[
            {"name": s["name"], "url": s["url"]}  # type: ignore[arg-type]
            for s in sources_dedup.values()
        ],
        activity=activity_rows,
    )


def _verdict_label_from_state(annotation: Annotation) -> str:
    """Map the L4b confidence state to the user-visible verdict label."""
    if annotation.confidence_state == "verified":
        return "True"
    if annotation.confidence_state == "contradicted":
        return "False"
    if annotation.confidence_state == "sources_disagree":
        return "Mixed"
    # insufficient_coverage is the no-route / empty-evidence case:
    return "Unverified"


# ---------------------------------------------------------------------------
# Video-level aggregations — math preserved from previous inline impl
# ---------------------------------------------------------------------------


_TRUST_LABELS: dict[int, str] = {
    1: "Mostly False",
    2: "Mixed / Leans False",
    3: "Mixed Accuracy / Needs Context",
    4: "Mostly True",
    5: "Highly Accurate",
}


def _score_to_trust(avg_score: float) -> tuple[int, str]:
    """Map an L4b final_score in ``[-1, 1]`` to a 1–5 trust score and label.

    ``trust = round(((score + 1) / 2) * 4) + 1``, clamped to ``[1, 5]``.
    """
    raw = round(((avg_score + 1) / 2) * 4) + 1
    clamped = max(1, min(5, raw))
    return clamped, _TRUST_LABELS[clamped]


def _bias_to_lean(avg_bias: float) -> tuple[str, float]:
    """Map an avg_bias in ``[-1, 1]`` to (label, value).

    Labels: ``Leans Left`` (< -0.3), ``Leans Right`` (> +0.3),
    ``Center / Neutral`` otherwise. Value rescales bias to ``[0, 1]``
    for the UI's progress-bar marker.
    """
    if avg_bias < -0.3:
        label = "Leans Left"
    elif avg_bias > 0.3:
        label = "Leans Right"
    else:
        label = "Center / Neutral"
    value = round((avg_bias + 1) / 2, 2)
    return label, value


def _summary_text(num_claims: int, trust_label: str, lean_label: str) -> str:
    if num_claims == 0:
        return "No verifiable political claims were extracted from this video."
    return (
        f"Analyzed {num_claims} claims. Overall video reliability is "
        f"{trust_label} with a {lean_label.lower()} sourcing bias."
    )


# ---------------------------------------------------------------------------
# Top-level entry
# ---------------------------------------------------------------------------


def aggregate_annotations(annotations: list[Annotation]) -> AnalyzeVideoResponse:
    """Build the ``AnalyzeVideoResponse`` from a list of per-claim
    annotations. Pure function — no I/O, no LLM."""
    num_claims = len(annotations)

    if num_claims == 0:
        avg_score = 0.0
        avg_bias = 0.0
    else:
        avg_score = sum(a.final_score for a in annotations) / num_claims
        # ``Annotation`` doesn't carry avg_bias directly today; compute it
        # by averaging the trust/bias signals threaded through results.
        # For now we treat unknown bias as 0.0 (neutral).
        bias_values = [
            _annotation_bias(a)
            for a in annotations
        ]
        avg_bias = sum(bias_values) / len(bias_values) if bias_values else 0.0

    trust_score, trust_label = _score_to_trust(avg_score)
    lean_label, lean_value = _bias_to_lean(avg_bias)

    claims = [_claim_to_frontend(a, i) for i, a in enumerate(annotations)]
    aggregated_sources = aggregate_frontend_sources(annotations)

    return AnalyzeVideoResponse(
        summary=_summary_text(num_claims, trust_label, lean_label),
        trustworthinessScore=trust_score,
        maxScore=5,
        trustworthinessLabel=trust_label,
        politicalLean=PoliticalLean(label=lean_label, value=lean_value),
        claims=claims,
        aggregatedSources=aggregated_sources,
    )


def _annotation_bias(annotation: Annotation) -> float:
    """Extract a per-annotation bias signal. Today the judge attaches
    bias info via ``Annotation.bias_warning`` (a string) — for the
    numeric average we read from a private convention: any
    ``ScoredSource`` instances inside evidence items contribute their
    ``bias`` value, weighted equally. Falls back to 0.0 when no
    bias-scored sources are present."""
    biases: list[float] = []
    for result in annotation.results:
        for item in result.evidence_items:
            bias = getattr(item.source, "bias", None)
            if bias is not None:
                biases.append(float(bias))
    if not biases:
        return 0.0
    return sum(biases) / len(biases)
