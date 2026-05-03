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
import logging
import re
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request
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
from backend.core.transcript import (
    chunk_transcript_segments,
    get_transcript,
    normalize_transcript_segments,
)

api_router = APIRouter()
logger = logging.getLogger("uvicorn.error")

# Single orchestrator instance per process — keeps each agent's
# in-memory cache warm across requests.
_orchestrator = AgentOrchestrator()
_transcript_store: dict[str, dict] = {}


def _transcript_debug(message: str, *args: object) -> None:
    rendered = message % args if args else message
    print(f"[Transcript] {rendered}", flush=True)
    logger.info("[Transcript] " + message, *args)


class PoliticalCheckRequest(BaseModel):
    title: Optional[str] = ""
    description: Optional[str] = ""
    tags: Optional[str] = ""
    aiDescription: Optional[str] = ""


class AnalyzeVideoRequest(BaseModel):
    url: str
    transcript: Optional[Any] = None
    transcriptId: Optional[str] = None


class AnalyzeClipRequest(BaseModel):
    url: str
    startTime: float
    endTime: float
    captions: Optional[str] = ""
    transcript: Optional[Any] = None
    transcriptId: Optional[str] = None


class TranscriptUploadRequest(BaseModel):
    url: str
    transcript: Any


class TranscriptUploadResponse(BaseModel):
    transcriptId: str
    chunkCount: int
    totalCharacters: int


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


def _store_transcript(url: str, transcript: Any) -> dict:
    segments = normalize_transcript_segments(transcript)
    chunks = chunk_transcript_segments(segments)
    transcript_id = f"tr-{uuid4().hex}"
    total_characters = sum(len(chunk["text"]) for chunk in chunks)
    preview = chunks[0]["text"][:160] if chunks else ""
    record = {
        "transcriptId": transcript_id,
        "url": url,
        "segments": segments,
        "chunks": chunks,
        "chunkCount": len(chunks),
        "totalCharacters": total_characters,
        "preview": preview,
        "createdAt": _utc_now(),
    }
    _transcript_store[transcript_id] = record
    _transcript_debug(
        "uploaded id=%s chunks=%s chars=%s url=%s preview=%r",
        transcript_id,
        len(chunks),
        total_characters,
        url,
        preview,
    )
    return record


def _get_stored_transcript(transcript_id: str) -> dict:
    record = _transcript_store.get(transcript_id)
    if record is None:
        _transcript_debug("lookup miss id=%s", transcript_id)
        raise HTTPException(status_code=404, detail="Transcript not found")
    _transcript_debug(
        "lookup hit id=%s chunks=%s chars=%s preview=%r",
        transcript_id,
        record["chunkCount"],
        record["totalCharacters"],
        record.get("preview", ""),
    )
    return record


def _build_transcript_record(url: str, transcript: Any) -> dict:
    segments = normalize_transcript_segments(transcript)
    chunks = chunk_transcript_segments(segments)
    return {
        "url": url,
        "segments": segments,
        "chunks": chunks,
    }


async def _resolve_transcript_chunks(
    url: str,
    transcript: Any | None = None,
    transcript_id: str | None = None,
) -> dict:
    if transcript_id:
        _transcript_debug("resolving from transcriptId=%s url=%s", transcript_id, url)
        return _get_stored_transcript(transcript_id)
    if transcript is not None:
        _transcript_debug("resolving from inline request body url=%s", url)
        return _build_transcript_record(url, transcript)
    if transcript is None:
        _transcript_debug("no transcript supplied for url=%s", url)
        chunks = await get_transcript(url)
        return {"url": url, "segments": chunks, "chunks": chunks}
    return {"url": url, "segments": [], "chunks": []}


def _canonicalize_text(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def _claim_time_bounds(
    claim_info: dict,
    chunk_timestamp: float,
    transcript_segments: list[dict],
) -> tuple[float, float]:
    fallback = float(claim_info.get("timestamp", chunk_timestamp))
    raw_quote = str(claim_info.get("raw_quote", "")).strip()
    if not raw_quote or not transcript_segments:
        return fallback, fallback

    quote_canon = _canonicalize_text(raw_quote)
    if not quote_canon:
        return fallback, fallback

    chunk_floor = chunk_timestamp
    chunk_ceiling = chunk_timestamp + 70.0
    candidate_segments = [
        seg for seg in transcript_segments
        if chunk_floor - 10.0 <= float(seg["timestamp"]) <= chunk_ceiling
    ] or transcript_segments

    best_match: tuple[float, float] | None = None
    best_score = -1.0
    max_window = min(8, len(candidate_segments))

    for start_idx in range(len(candidate_segments)):
        combined_parts: list[str] = []
        for end_idx in range(start_idx, min(len(candidate_segments), start_idx + max_window)):
            combined_parts.append(candidate_segments[end_idx]["text"])
            combined_canon = _canonicalize_text(" ".join(combined_parts))
            if not combined_canon:
                continue

            score = 0.0
            if quote_canon == combined_canon:
                score = len(quote_canon) + 1000.0
            elif quote_canon in combined_canon:
                score = len(quote_canon)
            elif combined_canon in quote_canon:
                score = len(combined_canon) * 0.95
            else:
                quote_tokens = set(quote_canon.split())
                combined_tokens = set(combined_canon.split())
                overlap = len(quote_tokens & combined_tokens)
                if overlap:
                    score = overlap / max(1, len(quote_tokens))
            if score > best_score:
                best_score = score
                best_match = (
                    float(candidate_segments[start_idx]["timestamp"]),
                    float(candidate_segments[end_idx]["timestamp"]),
                )

    if best_match is None or best_score <= 0:
        return fallback, fallback
    return best_match


@api_router.post("/check-political")
async def check_political(req: PoliticalCheckRequest):
    # Mock for now — always returns true so the rest of the pipeline runs.
    return {"isPolitical": True}


@api_router.post("/transcripts", response_model=TranscriptUploadResponse)
async def upload_transcript(req: TranscriptUploadRequest):
    _transcript_debug(
        "upload request url=%s type=%s",
        req.url,
        type(req.transcript).__name__,
    )
    record = _store_transcript(req.url, req.transcript)
    return TranscriptUploadResponse(
        transcriptId=record["transcriptId"],
        chunkCount=record["chunkCount"],
        totalCharacters=record["totalCharacters"],
    )


@api_router.get("/transcripts/{transcript_id}")
async def inspect_transcript(transcript_id: str):
    record = _transcript_store.get(transcript_id)
    if record is None:
        _transcript_debug("inspect miss id=%s", transcript_id)
        raise HTTPException(status_code=404, detail="Transcript not found")
    _transcript_debug(
        "inspect id=%s chunks=%s chars=%s",
        transcript_id,
        record["chunkCount"],
        record["totalCharacters"],
    )

    first_chunk = record["chunks"][0]["text"] if record["chunks"] else ""
    return {
        "transcriptId": record["transcriptId"],
        "url": record["url"],
        "chunkCount": record["chunkCount"],
        "totalCharacters": record["totalCharacters"],
        "preview": first_chunk[:240],
        "createdAt": record["createdAt"],
    }


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
    transcript_segments: list[dict],
) -> tuple[Annotation, dict, object, list]:
    claim_text = claim_info["claim"]
    claim_start_time, claim_end_time = _claim_time_bounds(
        claim_info,
        chunk_timestamp,
        transcript_segments,
    )
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
            start_time=claim_start_time,
            end_time=claim_end_time,
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
    transcript: Any | None = None,
    transcript_id: str | None = None,
) -> AsyncIterator[dict]:
    run_id = run_id or f"run-{uuid4().hex}"
    seq = 1

    event, seq = await _emit("run_started", run_id, seq, mode="video", url=url)
    yield event
    _transcript_debug(
        "analyze-video start run_id=%s transcriptId=%s inlineTranscript=%s url=%s",
        run_id,
        transcript_id or "",
        transcript is not None,
        url,
    )

    try:
        transcript_record = await _resolve_transcript_chunks(
            url,
            transcript,
            transcript_id,
        )
    except Exception as exc:
        event, seq = await _emit(
            "error",
            run_id,
            seq,
            stage="transcript",
            message=str(exc),
            recoverable=False,
        )
        yield event
        response = AnalyzeVideoResponse()
        event, _seq = await _emit(
            "done",
            run_id,
            seq,
            result=response.model_dump(),
        )
        yield event
        return
    chunks = transcript_record["chunks"]
    transcript_segments = transcript_record["segments"]
    _transcript_debug(
        "analyze-video ready run_id=%s chunks=%s chars=%s firstTimestamp=%s preview=%r",
        run_id,
        len(chunks),
        sum(len(chunk["text"]) for chunk in chunks),
        chunks[0]["timestamp"] if chunks else None,
        chunks[0]["text"][:160] if chunks else "",
    )
    event, seq = await _emit(
        "transcript_ready",
        run_id,
        seq,
        chunkCount=len(chunks),
        processedChunkLimit=len(chunks),
    )
    yield event

    annotations: list[Annotation] = []
    claim_index = 0

    for chunk in chunks:
        if request is not None and await request.is_disconnected():
            break

        extracted = await extract_claims(chunk["text"], chunk["timestamp"])
        # NOTE: extracted.opinions is currently dropped here; opinion-pipeline
        # wiring lands in the api/video.py integration commit.
        for claim_info in extracted.facts:
            if request is not None and await request.is_disconnected():
                break
            claim_start_time, claim_end_time = _claim_time_bounds(
                claim_info,
                chunk["timestamp"],
                transcript_segments,
            )

            event, seq = await _emit(
                "claim_extracted",
                run_id,
                seq,
                claimIndex=claim_index,
                claim={
                    "claim_text": claim_info["claim"],
                    "raw_quote": claim_info.get("raw_quote", claim_info["claim"]),
                    "start_time": claim_start_time,
                    "end_time": claim_end_time,
                    "topics": [],
                },
            )
            yield event

            try:
                annotation, _judge_result, decision, results = await _annotation_for_claim(
                    claim_info,
                    chunk["timestamp"],
                    transcript_segments,
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

    if req.captions:
        chunks = [{"text": req.captions, "timestamp": req.startTime}]
        transcript_segments = chunks
    else:
        try:
            transcript_record = await _resolve_transcript_chunks(
                req.url,
                req.transcript,
                req.transcriptId,
            )
            chunks = transcript_record["chunks"]
            transcript_segments = transcript_record["segments"]
        except Exception as exc:
            event, seq = await _emit(
                "error",
                run_id,
                seq,
                stage="transcript",
                message=str(exc),
                recoverable=False,
            )
            yield event
            response = _empty_clip_response(req)
            event, _seq = await _emit("done", run_id, seq, result=response.model_dump())
            yield event
            return

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
    # Clip path verifies the first FACT only. Opinions in the clip are
    # currently ignored here; opinion-pipeline wiring lands in the
    # integration commit.
    if not extracted.facts:
        response = _empty_clip_response(req)
        event, _seq = await _emit("done", run_id, seq, result=response.model_dump())
        yield event
        return

    claim_info = extracted.facts[0]
    claim_start_time, claim_end_time = _claim_time_bounds(
        claim_info,
        selected["timestamp"],
        transcript_segments,
    )
    event, seq = await _emit(
        "claim_extracted",
        run_id,
        seq,
        claimIndex=0,
        claim={
            "claim_text": claim_info["claim"],
            "raw_quote": claim_info.get("raw_quote", claim_info["claim"]),
            "start_time": claim_start_time,
            "end_time": claim_end_time,
            "topics": [],
        },
    )
    yield event

    try:
        annotation, judge_result, decision, results = await _annotation_for_claim(
            claim_info,
            selected["timestamp"],
            transcript_segments,
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
    _transcript_debug(
        "POST /analyze-video url=%s transcriptId=%s inlineTranscript=%s",
        req.url,
        req.transcriptId or "",
        req.transcript is not None,
    )
    response = AnalyzeVideoResponse()
    async for event in analyze_video_events(
        req.url,
        transcript=req.transcript,
        transcript_id=req.transcriptId,
    ):
        if event["event"] == "done":
            response = AnalyzeVideoResponse.model_validate(event["payload"]["result"])
    return response.model_dump()


@api_router.get("/analyze-video/stream")
async def analyze_video_stream(
    request: Request,
    url: str = Query(...),
    transcriptId: str | None = Query(None),
):
    _transcript_debug(
        "GET /analyze-video/stream url=%s transcriptId=%s",
        url,
        transcriptId or "",
    )
    return _stream_response(
        analyze_video_events(url, request=request, transcript_id=transcriptId)
    )


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
    transcriptId: str | None = Query(None),
):
    req = AnalyzeClipRequest(
        url=url,
        startTime=startTime,
        endTime=endTime,
        captions=captions,
        transcriptId=transcriptId,
    )
    return _stream_response(analyze_clip_events(req, request=request))
