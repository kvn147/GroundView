"""Bifurcated video-level aggregation (Level 4b → Level 5).

Two annotation streams feed this module:

  * ``Annotation``        — a *fact* claim verified by domain agents + judge.
  * ``OpinionAnnotation`` — a *subjective* claim scored by the opinion-bias
                            engine (``calculate_lean_structured`` in judge.py).

Separation rule (enforced by the top-level ``aggregate`` function):

  trustworthinessScore / trustworthinessLabel  ←  facts only
  politicalLean                                ←  opinions only
  claims                                       ←  facts only  (FrontendClaim list)
  opinions                                     ←  opinions only (FrontendOpinion list)

This module is pure: no I/O, no LLM, no async.
"""

from __future__ import annotations

from backend.contracts import (
    AnalyzeVideoResponse,
    Annotation,
    FrontendActivity,
    FrontendAggregatedSource,
    FrontendClaim,
    FrontendOpinion,
    FrontendOpinionEvidence,
    FrontendOpinionLean,
    OpinionAnnotation,
    PoliticalLean,
    aggregate_frontend_sources,
    to_frontend_activity,
    to_frontend_sources,
)


# ---------------------------------------------------------------------------
# Trust-score helpers (facts only)
# ---------------------------------------------------------------------------


_TRUST_LABELS: dict[int, str] = {
    1: "Mostly False",
    2: "Mixed / Leans False",
    3: "Mixed Accuracy / Needs Context",
    4: "Mostly True",
    5: "Highly Accurate",
}


def score_to_trust(avg_score: float) -> tuple[int, str]:
    """Map an average judge final_score in ``[-1, 1]`` to a 1–5 trust
    integer and its human-readable label.

    Formula: ``trust = round(((score + 1) / 2) * 4) + 1``, clamped [1, 5].
    """
    raw = round(((avg_score + 1) / 2) * 4) + 1
    clamped = max(1, min(5, raw))
    return clamped, _TRUST_LABELS[clamped]


def trustworthiness_from_facts(annotations: list[Annotation]) -> tuple[int, str]:
    """Return ``(score, label)`` derived *only* from fact annotations.

    Falls back to the neutral midpoint when the list is empty.
    """
    if not annotations:
        return 3, _TRUST_LABELS[3]
    avg = sum(a.final_score for a in annotations) / len(annotations)
    return score_to_trust(avg)


# ---------------------------------------------------------------------------
# Political-lean helpers (opinions only)
# ---------------------------------------------------------------------------


def bias_to_lean(avg_bias: float) -> tuple[str, float]:
    """Map an average bias in ``[-1, 1]`` to ``(label, value)``.

    ``value`` rescales bias to ``[0, 1]`` for the UI progress bar.
    Thresholds: < -0.3 → Left, > +0.3 → Right, else Center.
    """
    if avg_bias < -0.3:
        label = "Leans Left"
    elif avg_bias > 0.3:
        label = "Leans Right"
    else:
        label = "Center / Neutral"
    value = round((avg_bias + 1) / 2, 2)
    return label, value


def political_lean_from_opinions(
    opinion_annotations: list[OpinionAnnotation],
) -> PoliticalLean:
    """Return a ``PoliticalLean`` derived *only* from opinion annotations.

    Falls back to ``PoliticalLean(label='Unknown', value=0.5)`` when empty.

    Only opinions where the OpinionAgent's outlets actually staked a
    position contribute to the average. Opinions where every outlet
    came back ``unverifiable`` (``confidence == 0``) carry no signal,
    so including their ``lean_value=0.0`` would dilute clear leans
    toward the center — labeling a 4-opinion video as "Center" when
    two opinions clearly lean right and two were unscoreable.
    """
    if not opinion_annotations:
        return PoliticalLean(label="Unknown", value=0.5)
    contributing = [o for o in opinion_annotations if o.confidence > 0.0]
    if not contributing:
        return PoliticalLean(label="Unknown", value=0.5)
    avg_lean = sum(o.lean_value for o in contributing) / len(contributing)
    label, value = bias_to_lean(avg_lean)
    return PoliticalLean(label=label, value=value)


# ---------------------------------------------------------------------------
# Per-fact-claim adapter
# ---------------------------------------------------------------------------


def _verdict_from_state(annotation: Annotation) -> str:
    if annotation.confidence_state == "verified":
        return "True"
    if annotation.confidence_state == "contradicted":
        return "False"
    if annotation.confidence_state == "sources_disagree":
        return "Mixed"
    # ``insufficient_coverage`` lands here. We deliberately distinguish
    # this from "Unverified" — the system tried to fact-check the claim
    # and our allowlisted sources had no coverage. That's a different
    # signal from "we found contradictory evidence" (which is "Mixed").
    # The honest framing is "Unable to verify": the claim might still
    # be true, we just can't ground it in our allowlist. Pairs with the
    # tighter L2a extractor that now drops most non-fact-shaped items
    # before they reach this branch.
    return "Unable to verify"


def _fact_claim_to_frontend(annotation: Annotation, idx: int) -> FrontendClaim:
    sources_dedup: dict[str, dict[str, str]] = {}
    activity_rows: list[FrontendActivity] = []

    for result in annotation.results:
        for fs in to_frontend_sources(result):
            sources_dedup.setdefault(fs.name, {"name": fs.name, "url": fs.url})
            if not sources_dedup[fs.name]["url"] and fs.url:
                sources_dedup[fs.name]["url"] = fs.url
        activity = to_frontend_activity(result)
        if activity is not None:
            activity_rows.append(activity)

    parts = [r.summary_markdown for r in annotation.results if r.summary_markdown]
    body = "\n\n".join(parts) if parts else "_No evidence retrieved._"
    if annotation.bias_warning:
        body = f"{body}\n\n**Fact-Checker Warning:** {annotation.bias_warning}"

    return FrontendClaim(
        id=f"fact-{idx + 1}",
        text=annotation.claim.claim_text,
        startTime=annotation.claim.start_time,
        endTime=annotation.claim.end_time,
        verdict=_verdict_from_state(annotation),
        explanation=body,
        sources=[
            {"name": s["name"], "url": s["url"]}  # type: ignore[arg-type]
            for s in sources_dedup.values()
        ],
        activity=activity_rows,
    )


# ---------------------------------------------------------------------------
# Per-opinion adapter  →  FrontendOpinion
# ---------------------------------------------------------------------------


def _opinion_to_frontend(annotation: OpinionAnnotation) -> FrontendOpinion:
    """Convert an ``OpinionAnnotation`` to the ``FrontendOpinion`` shape."""
    result = annotation.results[0] if annotation.results else None
    activity = to_frontend_activity(result) if result else None

    evidence: list[FrontendOpinionEvidence] = []
    if result:
        for item in result.evidence_items:
            if item.stance is not None:
                evidence.append(
                    FrontendOpinionEvidence(
                        outlet=item.source.name if item.source else "Unknown",
                        stance=item.stance,
                        summary=item.text,
                    )
                )

    return FrontendOpinion(
        statement=annotation.opinion.statement,
        raw_quote=annotation.opinion.raw_quote,
        startTime=annotation.opinion.start_time,
        endTime=annotation.opinion.end_time,
        lean=FrontendOpinionLean(
            value=annotation.lean_value,
            label=annotation.lean_label,
            reasoning=annotation.reasoning,
            confidence=annotation.confidence,
        ),
        evidence=evidence,
        activity=activity,
    )


# ---------------------------------------------------------------------------
# Summary line
# ---------------------------------------------------------------------------


def _summary_text(
    num_facts: int,
    num_opinions: int,
    trust_label: str,
    lean_label: str,
) -> str:
    if num_facts == 0 and num_opinions == 0:
        return "No verifiable or opinion-bearing political claims were extracted from this video."
    parts: list[str] = []
    if num_facts:
        parts.append(f"{num_facts} factual claim{'s' if num_facts != 1 else ''} rated {trust_label}")
    if num_opinions:
        parts.append(
            f"{num_opinions} opinion statement{'s' if num_opinions != 1 else ''} "
            f"leaning {lean_label.lower()}"
        )
    return "Analyzed: " + " and ".join(parts) + "."


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------


def aggregate(
    fact_annotations: list[Annotation],
    opinion_annotations: list[OpinionAnnotation],
) -> AnalyzeVideoResponse:
    """Build the full ``AnalyzeVideoResponse`` from the two annotation streams.

    Separation rules
    ----------------
    * ``trustworthinessScore`` / ``trustworthinessLabel``  ← facts only
    * ``politicalLean``                                    ← opinions only
    * ``claims``                                           ← facts only
    * ``opinions``                                         ← opinions only
    * ``aggregatedSources``                                ← facts only

    Both lists may be empty independently.
    """
    trust_score, trust_label = trustworthiness_from_facts(fact_annotations)
    lean = political_lean_from_opinions(opinion_annotations)

    fact_claims = [_fact_claim_to_frontend(a, i) for i, a in enumerate(fact_annotations)]
    frontend_opinions = [_opinion_to_frontend(o) for o in opinion_annotations]

    summary = _summary_text(
        num_facts=len(fact_annotations),
        num_opinions=len(opinion_annotations),
        trust_label=trust_label,
        lean_label=lean.label,
    )

    return AnalyzeVideoResponse(
        summary=summary,
        trustworthinessScore=trust_score,
        maxScore=5,
        trustworthinessLabel=trust_label,
        politicalLean=lean,
        claims=fact_claims,
        aggregatedSources=aggregate_frontend_sources(fact_annotations),
        opinions=frontend_opinions,
    )
