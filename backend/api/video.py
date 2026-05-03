"""FastAPI routes for the fact-check pipeline.

The full pipeline that ``/analyze-video`` runs:

  L1  transcript fetch     — backend/core/transcript.py
  L2a claim extraction     — backend/core/extract.py (Haiku)
  L2b topic routing        — backend/app/level2b_routing/router.py (local)
  L3  agent fan-out        — backend/agents/orchestrator.py
       └─ allowlist enforce — backend/agents/base.py (the moneyshot)
  L4a aggregation          — backend/agents/aggregator.py (rules-only)
  L4b confidence rules     — backend/agents/judge.py (calculate_confidence_structured)
  L5  rendering            — backend/contracts.py shapes the response

The route handler stays thin: it composes those modules and returns
the ``AnalyzeVideoResponse`` shape the chrome extension expects.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

from backend.agents.aggregator import aggregate_annotations
from backend.agents.judge import calculate_confidence_structured
from backend.agents.orchestrator import AgentOrchestrator
from backend.app.level2b_routing.router import route as l2b_route
from backend.contracts import Annotation, Claim, ConfidenceState
from backend.core.extract import extract_claims
from backend.core.transcript import get_transcript

api_router = APIRouter()

# Single orchestrator instance per process — keeps each agent's
# in-memory cache warm across requests.
_orchestrator = AgentOrchestrator()


class PoliticalCheckRequest(BaseModel):
    title: Optional[str] = ""
    description: Optional[str] = ""
    tags: Optional[str] = ""
    aiDescription: Optional[str] = ""


class AnalyzeVideoRequest(BaseModel):
    url: str


class AnalyzeClipRequest(BaseModel):
    url: str
    startTime: float
    endTime: float
    captions: Optional[str] = ""


@api_router.post("/check-political")
async def check_political(req: PoliticalCheckRequest):
    # Mock for now — always returns true so the rest of the pipeline runs.
    return {"isPolitical": True}


def _confidence_state_from_score(final_score: float) -> ConfidenceState:
    """Map judge's numeric score onto the L4b state enum from
    AGENTIC_WORKFLOW.md. Threshold-based, deterministic."""
    if final_score > 0.6:
        return "verified"
    if final_score < -0.6:
        return "contradicted"
    if final_score == 0.0:
        return "insufficient_coverage"
    return "sources_disagree"


@api_router.post("/analyze-video")
async def analyze_video(req: AnalyzeVideoRequest):
    chunks = await get_transcript(req.url)

    annotations: list[Annotation] = []

    # MVP cap: 5 chunks is enough for the demo and avoids HTTP timeout.
    for chunk in chunks[:5]:
        extracted = await extract_claims(chunk["text"], chunk["timestamp"])
        for claim_info in extracted:
            claim_text = claim_info["claim"]

            # L2b routing — local classifier, multi-label, no LLM.
            decision = l2b_route(claim_text)

            # L3 fan-out — concurrent across routed topics, with hard
            # allowlist enforcement inside each agent.
            fanout = await _orchestrator.run(
                claim_text=claim_text,
                routed_topics=decision.routed_topics,
            )

            # L4b — score and aggregate evidence across all agents that
            # ran. Each agent's evidence is unioned; the judge sees one
            # flat list of EvidenceItems for the claim.
            all_evidence = [
                item
                for result in fanout.results
                for item in result.evidence_items
            ]
            judge_result = await calculate_confidence_structured(
                claim_text, all_evidence
            )

            annotations.append(
                Annotation(
                    claim=Claim(
                        claim_text=claim_text,
                        raw_quote=claim_info.get("raw_quote", claim_text),
                        start_time=claim_info.get("timestamp", chunk["timestamp"]),
                        end_time=claim_info.get("timestamp", chunk["timestamp"]),
                        topics=decision.routed_topics,
                    ),
                    results=fanout.results,
                    confidence_state=_confidence_state_from_score(
                        judge_result.get("final_score", 0.0)
                    ),
                    final_score=judge_result.get("final_score", 0.0),
                    bias_warning=judge_result.get("warning") or None,
                )
            )

    # L4a + L5 prep — pure-Python aggregation into the response shape.
    response = aggregate_annotations(annotations)
    return response.model_dump()


@api_router.post("/analyze-clip")
async def analyze_clip(req: AnalyzeClipRequest):
    # Same pipeline as /analyze-video but bounded to one chunk; the
    # frontend supplies caption text directly so we can skip the
    # transcript fetch.
    chunks = (
        [{"text": req.captions, "timestamp": req.startTime}]
        if req.captions
        else (await get_transcript(req.url))
    )

    # Find the chunk that overlaps the requested window. Fall back to
    # the first chunk if nothing matches.
    selected = chunks[0]
    for chunk in chunks:
        ts = chunk.get("timestamp", 0)
        if req.startTime <= ts <= req.endTime:
            selected = chunk
            break

    extracted = await extract_claims(selected["text"], selected["timestamp"])
    if not extracted:
        return {
            "startTime": req.startTime,
            "endTime": req.endTime,
            "claim": "No verifiable claim detected in this clip.",
            "verdict": "Unverified",
            "explanation": "",
            "sources": [],
        }

    claim_info = extracted[0]
    claim_text = claim_info["claim"]
    decision = l2b_route(claim_text)
    fanout = await _orchestrator.run(claim_text, decision.routed_topics)
    all_evidence = [
        item for result in fanout.results for item in result.evidence_items
    ]
    judge_result = await calculate_confidence_structured(claim_text, all_evidence)

    explanation_parts = [r.summary_markdown for r in fanout.results if r.summary_markdown]
    explanation = "\n\n".join(explanation_parts) or "_No evidence retrieved._"
    if judge_result.get("warning"):
        explanation = f"{explanation}\n\n**Fact-Checker Warning:** {judge_result['warning']}"

    sources = []
    seen: set[str] = set()
    for result in fanout.results:
        for item in result.evidence_items:
            name = item.source.name
            if name in seen:
                continue
            seen.add(name)
            sources.append({"name": name, "url": item.source.url or ""})

    return {
        "startTime": req.startTime,
        "endTime": req.endTime,
        "claim": claim_text,
        "verdict": judge_result.get("verdict", "Unverified"),
        "explanation": explanation,
        "sources": sources,
    }
