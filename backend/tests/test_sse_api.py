"""Tests for the SSE analysis pipeline.

The stream is now the source of truth for analysis progress. These
tests mock the expensive L1/L2/L3/L4 calls and lock down the event
contract that the Chrome extension consumes.
"""

from __future__ import annotations

import sys
from types import ModuleType
from types import SimpleNamespace

import pytest

if "openai" not in sys.modules:
    openai_stub = ModuleType("openai")

    class AsyncOpenAI:
        def __init__(self, *args, **kwargs) -> None:
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self._create)
            )

        async def _create(self, *args, **kwargs):
            raise AssertionError("OpenAI should be mocked out in SSE API tests")

    openai_stub.AsyncOpenAI = AsyncOpenAI
    sys.modules["openai"] = openai_stub

if "youtube_transcript_api" not in sys.modules:
    transcript_stub = ModuleType("youtube_transcript_api")

    class YouTubeTranscriptApi:
        @staticmethod
        def get_transcript(video_id: str):
            raise AssertionError("Transcript fetch should be mocked in SSE tests")

    transcript_stub.YouTubeTranscriptApi = YouTubeTranscriptApi
    sys.modules["youtube_transcript_api"] = transcript_stub

from backend.api import video
from backend.app.level2b_routing.types import RoutingDecision
from backend.contracts import EvidenceItem, Source, VerificationResult


class FakeOrchestrator:
    async def run(self, claim_text: str, routed_topics: list[str]):
        return SimpleNamespace(
            results=[
                VerificationResult(
                    agent="EconomyAgent",
                    claim_text=claim_text,
                    allowed_sources=["BLS"],
                    queried_sources=["BLS"],
                    evidence_items=[
                        EvidenceItem(
                            text="The evidence supports the claim.",
                            source=Source(name="BLS", url="https://bls.gov"),
                            p_entail=0.9,
                            p_contradict=0.1,
                            nli_source="agent",
                        )
                    ],
                )
            ],
            unrouted_topics=[],
        )


@pytest.fixture
def mocked_pipeline(monkeypatch):
    async def fake_get_transcript(url: str):
        return [{"text": "Inflation was 3 percent.", "timestamp": 12.0}]

    async def fake_extract_claims(text: str, timestamp: float):
        return [
            {
                "claim": "Inflation was 3 percent.",
                "raw_quote": "Inflation was 3 percent.",
                "timestamp": timestamp,
            }
        ]

    def fake_route(claim_text: str):
        return RoutingDecision(
            claim_text=claim_text,
            routed_topics=["economy"],
            routing_method="keyword",
            routing_confidence=0.9,
        )

    async def fake_confidence(claim_text: str, evidence_items: list[EvidenceItem]):
        return {
            "final_score": 0.8,
            "verdict": "True",
            "warning": "",
        }

    monkeypatch.setattr(video, "get_transcript", fake_get_transcript)
    monkeypatch.setattr(video, "extract_claims", fake_extract_claims)
    monkeypatch.setattr(video, "l2b_route", fake_route)
    monkeypatch.setattr(video, "calculate_confidence_structured", fake_confidence)
    monkeypatch.setattr(video, "_orchestrator", FakeOrchestrator())


@pytest.mark.asyncio
async def test_analyze_video_events_emit_incremental_contract(mocked_pipeline) -> None:
    events = [event async for event in video.analyze_video_events("https://youtu.be/x")]
    names = [event["event"] for event in events]

    assert names == [
        "run_started",
        "transcript_ready",
        "claim_extracted",
        "claim_routed",
        "agent_result",
        "claim_final",
        "summary_updated",
        "done",
    ]

    claim_final = next(event for event in events if event["event"] == "claim_final")
    assert claim_final["payload"]["claim"]["text"] == "Inflation was 3 percent."
    assert claim_final["payload"]["claim"]["startTime"] == 12.0
    assert claim_final["payload"]["claim"]["endTime"] == 12.0
    assert claim_final["payload"]["claim"]["verdict"] == "True"

    done = events[-1]
    assert done["payload"]["result"]["claims"][0]["text"] == "Inflation was 3 percent."
    assert done["payload"]["result"]["claims"][0]["startTime"] == 12.0
    assert done["payload"]["result"]["claims"][0]["endTime"] == 12.0
    assert done["payload"]["result"]["trustworthinessScore"] == 5


@pytest.mark.asyncio
async def test_analyze_video_events_process_all_transcript_chunks(
    mocked_pipeline,
    monkeypatch,
) -> None:
    async def fake_get_transcript(url: str):
        return [
            {"text": f"Claim from minute {idx}.", "timestamp": float(idx * 60)}
            for idx in range(6)
        ]

    async def fake_extract_claims(text: str, timestamp: float):
        return [
            {
                "claim": text,
                "raw_quote": text,
                "timestamp": timestamp,
            }
        ]

    monkeypatch.setattr(video, "get_transcript", fake_get_transcript)
    monkeypatch.setattr(video, "extract_claims", fake_extract_claims)

    events = [event async for event in video.analyze_video_events("https://youtu.be/x")]
    transcript_ready = next(
        event for event in events if event["event"] == "transcript_ready"
    )
    claim_final_events = [
        event for event in events if event["event"] == "claim_final"
    ]

    assert transcript_ready["payload"]["chunkCount"] == 6
    assert transcript_ready["payload"]["processedChunkLimit"] == 6
    assert len(claim_final_events) == 6
    assert events[-1]["payload"]["result"]["claims"][-1]["text"] == "Claim from minute 5."


@pytest.mark.asyncio
async def test_sync_video_endpoint_consumes_stream_result(mocked_pipeline) -> None:
    response = await video.analyze_video(
        video.AnalyzeVideoRequest(url="https://youtu.be/x")
    )

    assert response["claims"][0]["text"] == "Inflation was 3 percent."
    assert response["claims"][0]["verdict"] == "True"


@pytest.mark.asyncio
async def test_analyze_clip_events_emit_done_response(mocked_pipeline) -> None:
    req = video.AnalyzeClipRequest(
        url="https://youtu.be/x",
        startTime=10.0,
        endTime=20.0,
        captions="Inflation was 3 percent.",
    )
    events = [event async for event in video.analyze_clip_events(req)]

    assert events[-1]["event"] == "done"
    result = events[-1]["payload"]["result"]
    assert result["claim"] == "Inflation was 3 percent."
    assert result["verdict"] == "True"
    assert result["sources"] == [{"name": "BLS", "url": "https://bls.gov"}]


@pytest.mark.asyncio
async def test_analyze_video_claim_timestamps_match_underlying_segments(
    mocked_pipeline,
    monkeypatch,
) -> None:
    async def fake_extract_claims(text: str, timestamp: float):
        return [
            {
                "claim": "Claim one.",
                "raw_quote": "Claim one happened first.",
                "timestamp": timestamp,
            },
            {
                "claim": "Claim two.",
                "raw_quote": "Claim two happened later.",
                "timestamp": timestamp,
            },
        ]

    monkeypatch.setattr(video, "extract_claims", fake_extract_claims)

    transcript = [
        {"text": "Claim one happened first.", "timestamp": 5.0},
        {"text": "Claim two happened later.", "timestamp": 19.0},
    ]
    events = [
        event
        async for event in video.analyze_video_events(
            "https://youtu.be/x",
            transcript=transcript,
        )
    ]

    claim_final_events = [
        event["payload"]["claim"]
        for event in events
        if event["event"] == "claim_final"
    ]

    assert claim_final_events[0]["startTime"] == 5.0
    assert claim_final_events[0]["endTime"] == 5.0
    assert claim_final_events[1]["startTime"] == 19.0
    assert claim_final_events[1]["endTime"] == 19.0
