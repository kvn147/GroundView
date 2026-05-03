"""Transcript normalization and chunking.

YouTube blocks the server-side transcript API often enough that the
backend now expects the Chrome extension to extract captions in the
browser and send them along with the analysis request.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

CHUNK_SECONDS = 60
OVERLAP_SECONDS = 10


TranscriptInput = str | Sequence[Mapping[str, Any]]


def _coerce_timestamp(segment: Mapping[str, Any]) -> float:
    for key in ("timestamp", "start", "startTime", "offset"):
        value = segment.get(key)
        if value is None:
            continue
        try:
            return round(float(value), 2)
        except (TypeError, ValueError):
            continue
    return 0.0


def _normalize_segments(transcript: TranscriptInput) -> list[dict]:
    if isinstance(transcript, str):
        text = transcript.strip()
        return [{"timestamp": 0.0, "text": text}] if text else []

    normalized = []
    for segment in transcript:
        text = str(segment.get("text", "")).strip()
        if not text:
            continue
        normalized.append(
            {
                "timestamp": _coerce_timestamp(segment),
                "text": " ".join(text.split()),
            }
        )

    return sorted(normalized, key=lambda item: item["timestamp"])


def normalize_transcript(transcript: TranscriptInput) -> list[dict]:
    return _chunk_segments(_normalize_segments(transcript))


async def get_transcript(
    youtube_url: str,
    transcript: TranscriptInput | None = None,
) -> list[dict]:
    if transcript is None:
        raise RuntimeError(
            "No transcript was supplied. The Chrome extension must send "
            "caption text extracted from the YouTube page."
        )

    return normalize_transcript(transcript)


def _chunk_segments(segments: list[dict]) -> list[dict]:
    if not segments:
        return []

    chunks = []
    chunk_start = segments[0]["timestamp"]
    chunk_texts = []
    chunk_ts = chunk_start

    for seg in segments:
        if seg["timestamp"] - chunk_start >= CHUNK_SECONDS:
            chunks.append({"timestamp": chunk_ts, "text": " ".join(chunk_texts)})
            overlap_ts = seg["timestamp"] - OVERLAP_SECONDS
            chunk_texts = [
                s["text"]
                for s in segments
                if overlap_ts <= s["timestamp"] <= seg["timestamp"]
            ]
            chunk_start = seg["timestamp"]
            chunk_ts = seg["timestamp"]
        else:
            chunk_texts.append(seg["text"])

    if chunk_texts:
        chunks.append({"timestamp": chunk_ts, "text": " ".join(chunk_texts)})

    return chunks
