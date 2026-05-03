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

import json
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.agents.aggregator import aggregate_annotations
from backend.agents.judge import calculate_confidence_structured
from backend.agents.orchestrator import AgentOrchestrator
from backend.app.level2b_routing.router import route as l2b_route
from backend.contracts import (
    AnalyzeClipResponse,
    AnalyzeVideoResponse,
    Annotation,
    Claim,
    ConfidenceState,
    FrontendSource,
)
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


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sse(event: str, payload: dict, event_id: str | None = None) -> str:
    lines = [f"event: {event}"]
    if event_id:
        lines.append(f"id: {event_id}")
    lines.append(f"data: {json.dumps(payload, default=str)}")
    return "\n".join(lines) + "\n\n"


def _event_payload(
    event_type: str,
    run_id: str,
    seq: int,
    **data,
) -> dict:
    return {
        "type": event_type,
        "runId": run_id,
        "seq": seq,
        "timestamp": _utc_now(),
        **data,
    }


def _stream_response(events: AsyncIterator[dict]) -> StreamingResponse:
    async def body() -> AsyncIterator[str]:
        async for event in events:
            yield _sse(
                event["event"],
                event["payload"],
                event_id=f"{event['payload']['runId']}:{event['payload']['seq']}",
            )

    return StreamingResponse(
        body(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


async def _emit(
    event_type: str,
    run_id: str,
    seq: int,
    **data,
) -> tuple[dict, int]:
    return {
        "event": event_type,
        "payload": _event_payload(event_type, run_id, seq, **data),
    }, seq + 1


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


async def _annotation_for_claim(
    claim_info: dict,
    chunk_timestamp: float,
) -> tuple[Annotation, dict, object, list]:
    claim_text = claim_info["claim"]
    decision = l2b_route(claim_text)

    fanout = await _orchestrator.run(
        claim_text=claim_text,
        routed_topics=decision.routed_topics,
    )
    all_evidence = [
        item
        for result in fanout.results
        for item in result.evidence_items
    ]
    judge_result = await calculate_confidence_structured(claim_text, all_evidence)

    annotation = Annotation(
        claim=Claim(
            claim_text=claim_text,
            raw_quote=claim_info.get("raw_quote", claim_text),
            start_time=claim_info.get("timestamp", chunk_timestamp),
            end_time=claim_info.get("timestamp", chunk_timestamp),
            topics=decision.routed_topics,
        ),
        results=fanout.results,
        confidence_state=_confidence_state_from_score(
            judge_result.get("final_score", 0.0)
        ),
        final_score=judge_result.get("final_score", 0.0),
        bias_warning=judge_result.get("warning") or None,
    )
    return annotation, judge_result, decision, fanout.results


def _clip_response_from_annotation(
    req: AnalyzeClipRequest,
    annotation: Annotation,
    judge_result: dict,
) -> AnalyzeClipResponse:
    explanation_parts = [
        r.summary_markdown for r in annotation.results if r.summary_markdown
    ]
    explanation = "\n\n".join(explanation_parts) or "_No evidence retrieved._"
    if judge_result.get("warning"):
        explanation = f"{explanation}\n\n**Fact-Checker Warning:** {judge_result['warning']}"

    sources = []
    seen: set[str] = set()
    for result in annotation.results:
        for item in result.evidence_items:
            name = item.source.name
            if name in seen:
                continue
            seen.add(name)
            sources.append(FrontendSource(name=name, url=item.source.url or ""))

    return AnalyzeClipResponse(
        startTime=req.startTime,
        endTime=req.endTime,
        claim=annotation.claim.claim_text,
        verdict=judge_result.get("verdict", "Unverified"),
        explanation=explanation,
        sources=sources,
    )


def _empty_clip_response(req: AnalyzeClipRequest) -> AnalyzeClipResponse:
    return AnalyzeClipResponse(
        startTime=req.startTime,
        endTime=req.endTime,
        claim="No verifiable claim detected in this clip.",
        verdict="Unverified",
        explanation="",
        sources=[],
    )


async def analyze_video_events(
    url: str,
    request: Request | None = None,
    run_id: str | None = None,
) -> AsyncIterator[dict]:
    run_id = run_id or f"run-{uuid4().hex}"
    seq = 1

    event, seq = await _emit("run_started", run_id, seq, mode="video", url=url)
    yield event

    chunks = await get_transcript(url)
    processed_limit = min(5, len(chunks))
    event, seq = await _emit(
        "transcript_ready",
        run_id,
        seq,
        chunkCount=len(chunks),
        processedChunkLimit=processed_limit,
    )
    yield event

    annotations: list[Annotation] = []
    claim_index = 0

    for chunk in chunks[:5]:
        if request is not None and await request.is_disconnected():
            break

        extracted = await extract_claims(chunk["text"], chunk["timestamp"])
        for claim_info in extracted:
            if request is not None and await request.is_disconnected():
                break

            event, seq = await _emit(
                "claim_extracted",
                run_id,
                seq,
                claimIndex=claim_index,
                claim={
                    "claim_text": claim_info["claim"],
                    "raw_quote": claim_info.get("raw_quote", claim_info["claim"]),
                    "start_time": claim_info.get("timestamp", chunk["timestamp"]),
                    "end_time": claim_info.get("timestamp", chunk["timestamp"]),
                    "topics": [],
                },
            )
            yield event

            try:
                annotation, _judge_result, decision, results = await _annotation_for_claim(
                    claim_info, chunk["timestamp"]
                )
            except Exception as exc:
                event, seq = await _emit(
                    "error",
                    run_id,
                    seq,
                    stage="claim_final",
                    message=str(exc),
                    recoverable=True,
                )
                yield event
                claim_index += 1
                continue

            event, seq = await _emit(
                "claim_routed",
                run_id,
                seq,
                claimIndex=claim_index,
                routedTopics=decision.routed_topics,
                routingMethod=decision.routing_method,
                routingConfidence=decision.routing_confidence,
            )
            yield event

            for result in results:
                event, seq = await _emit(
                    "agent_result",
                    run_id,
                    seq,
                    claimIndex=claim_index,
                    agent=result.agent,
                    result=result.model_dump(),
                )
                yield event

            annotations.append(annotation)
            partial = aggregate_annotations(annotations)
            frontend_claim = partial.claims[-1]

            event, seq = await _emit(
                "claim_final",
                run_id,
                seq,
                claimIndex=claim_index,
                claim=frontend_claim.model_dump(),
            )
            yield event

            event, seq = await _emit(
                "summary_updated",
                run_id,
                seq,
                summary=partial.summary,
                trustworthinessScore=partial.trustworthinessScore,
                maxScore=partial.maxScore,
                trustworthinessLabel=partial.trustworthinessLabel,
                politicalLean=partial.politicalLean.model_dump(),
                aggregatedSources=[
                    source.model_dump() for source in partial.aggregatedSources
                ],
            )
            yield event
            claim_index += 1

    response = aggregate_annotations(annotations)
    event, _seq = await _emit(
        "done",
        run_id,
        seq,
        result=response.model_dump(),
    )
    yield event


async def analyze_clip_events(
    req: AnalyzeClipRequest,
    request: Request | None = None,
    run_id: str | None = None,
) -> AsyncIterator[dict]:
    run_id = run_id or f"run-{uuid4().hex}"
    seq = 1

    event, seq = await _emit("run_started", run_id, seq, mode="clip", url=req.url)
    yield event

    chunks = (
        [{"text": req.captions, "timestamp": req.startTime}]
        if req.captions
        else (await get_transcript(req.url))
    )

    event, seq = await _emit(
        "transcript_ready",
        run_id,
        seq,
        chunkCount=len(chunks),
        processedChunkLimit=1,
    )
    yield event

    if request is not None and await request.is_disconnected():
        return

    selected = chunks[0]
    for chunk in chunks:
        ts = chunk.get("timestamp", 0)
        if req.startTime <= ts <= req.endTime:
            selected = chunk
            break

    extracted = await extract_claims(selected["text"], selected["timestamp"])
    if not extracted:
        response = _empty_clip_response(req)
        event, _seq = await _emit("done", run_id, seq, result=response.model_dump())
        yield event
        return

    claim_info = extracted[0]
    event, seq = await _emit(
        "claim_extracted",
        run_id,
        seq,
        claimIndex=0,
        claim={
            "claim_text": claim_info["claim"],
            "raw_quote": claim_info.get("raw_quote", claim_info["claim"]),
            "start_time": claim_info.get("timestamp", selected["timestamp"]),
            "end_time": claim_info.get("timestamp", selected["timestamp"]),
            "topics": [],
        },
    )
    yield event

    try:
        annotation, judge_result, decision, results = await _annotation_for_claim(
            claim_info, selected["timestamp"]
        )
    except Exception as exc:
        event, seq = await _emit(
            "error",
            run_id,
            seq,
            stage="claim_final",
            message=str(exc),
            recoverable=False,
        )
        yield event
        response = _empty_clip_response(req)
        event, _seq = await _emit("done", run_id, seq, result=response.model_dump())
        yield event
        return

    event, seq = await _emit(
        "claim_routed",
        run_id,
        seq,
        claimIndex=0,
        routedTopics=decision.routed_topics,
        routingMethod=decision.routing_method,
        routingConfidence=decision.routing_confidence,
    )
    yield event

    for result in results:
        event, seq = await _emit(
            "agent_result",
            run_id,
            seq,
            claimIndex=0,
            agent=result.agent,
            result=result.model_dump(),
        )
        yield event

    frontend_claim = aggregate_annotations([annotation]).claims[0]
    event, seq = await _emit(
        "claim_final",
        run_id,
        seq,
        claimIndex=0,
        claim=frontend_claim.model_dump(),
    )
    yield event

    response = _clip_response_from_annotation(req, annotation, judge_result)
    event, _seq = await _emit("done", run_id, seq, result=response.model_dump())
    yield event


@api_router.post("/analyze-video")
async def analyze_video(req: AnalyzeVideoRequest):
    response = AnalyzeVideoResponse()
    async for event in analyze_video_events(req.url):
        if event["event"] == "done":
            response = AnalyzeVideoResponse.model_validate(event["payload"]["result"])
    return response.model_dump()


@api_router.get("/analyze-video/stream")
async def analyze_video_stream(request: Request, url: str = Query(...)):
    return _stream_response(analyze_video_events(url, request=request))


@api_router.post("/analyze-clip")
async def analyze_clip(req: AnalyzeClipRequest):
    response = _empty_clip_response(req)
    async for event in analyze_clip_events(req):
        if event["event"] == "done":
            response = AnalyzeClipResponse.model_validate(event["payload"]["result"])
    return response.model_dump()


@api_router.get("/analyze-clip/stream")
async def analyze_clip_stream(
    request: Request,
    url: str = Query(...),
    startTime: float = Query(...),
    endTime: float = Query(...),
    captions: str = Query(""),
):
    req = AnalyzeClipRequest(
        url=url,
        startTime=startTime,
        endTime=endTime,
        captions=captions,
    )
    return _stream_response(analyze_clip_events(req, request=request))
