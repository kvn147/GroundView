import json
import asyncio
from youtube_transcript_api import YouTubeTranscriptApi

CHUNK_SECONDS = 60
OVERLAP_SECONDS = 10


def _extract_video_id(url: str) -> str:
    if "v=" in url:
        return url.split("v=")[1].split("&")[0]
    if "youtu.be/" in url:
        return url.split("youtu.be/")[1].split("?")[0]
    raise ValueError(f"Could not extract video ID from URL: {url}")


from youtube_transcript_api import YouTubeTranscriptApi

async def get_transcript(youtube_url: str) -> list[dict]:
    video_id = _extract_video_id(youtube_url)
    transcript = await asyncio.to_thread(
        YouTubeTranscriptApi.get_transcript, video_id
    )
    normalized = [
        {"timestamp": round(s["start"], 2), "text": s["text"]}
        for s in transcript
    ]
    return _chunk_segments(normalized)

def _chunk_segments(segments: list[dict]) -> list[dict]:
    if not segments:
        return []

    chunks = []
    chunk_start = segments[0]["timestamp"]
    chunk_texts = []
    chunk_ts = chunk_start

    for seg in segments:
        if seg["timestamp"] - chunk_start >= CHUNK_SECONDS:
            chunks.append({
                "timestamp": chunk_ts,
                "text": " ".join(chunk_texts)
            })
            overlap_ts = seg["timestamp"] - OVERLAP_SECONDS
            chunk_texts = [
                s["text"] for s in segments
                if overlap_ts <= s["timestamp"] <= seg["timestamp"]
            ]
            chunk_start = seg["timestamp"]
            chunk_ts = seg["timestamp"]
        else:
            chunk_texts.append(seg["text"])

    if chunk_texts:
        chunks.append({
            "timestamp": chunk_ts,
            "text": " ".join(chunk_texts)
        })

    return chunks