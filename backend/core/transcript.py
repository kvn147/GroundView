import asyncio
import json
import re
import os
import httpx
from youtube_transcript_api import YouTubeTranscriptApi
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
CHUNK_SECONDS = 15
OVERLAP_SECONDS = 3


def _extract_video_id(url: str) -> str:
    if "v=" in url:
        return url.split("v=")[1].split("&")[0]
    if "youtu.be/" in url:
        return url.split("youtu.be/")[1].split("?")[0]
    raise ValueError(f"Could not extract video ID from URL: {url}")


async def get_transcript(youtube_url: str) -> list[dict]:
    video_id = _extract_video_id(youtube_url)
    ytt = YouTubeTranscriptApi()
    raw = await asyncio.to_thread(ytt.fetch, video_id)
    normalized = [
        {"timestamp": round(s.start, 2), "text": s.text, "speaker": "unknown"}
        for s in raw
    ]
    return _chunk_segments(normalized)


async def get_transcript_with_speakers(
    youtube_url: str,
    known_speakers: list[str]
) -> list[dict]:
    """
    Full pipeline — transcript + speaker detection.
    known_speakers: e.g. ["Trump", "Biden", "Moderator"]
    """
    video_id = _extract_video_id(youtube_url)
    ytt = YouTubeTranscriptApi()
    raw = await asyncio.to_thread(ytt.fetch, video_id)
    normalized = [
        {"timestamp": round(s.start, 2), "text": s.text, "speaker": "unknown"}
        for s in raw
    ]

    # try caption-based detection first
    parsed = _parse_speaker_from_captions(normalized)
    has_labels = any(s["speaker"] != "unknown" for s in parsed)

    if has_labels:
        print("Speaker labels found in captions")
        return _chunk_segments(parsed)

    # fall back to LLM detection in batches
    print("No caption labels found — using LLM speaker detection")
    labeled = await _llm_speaker_detection(parsed, known_speakers)
    return _chunk_segments(labeled)


def _parse_speaker_from_captions(segments: list[dict]) -> list[dict]:
    """
    Parses speaker labels from caption formatting.
    Handles: >> SPEAKER:, [SPEAKER], SPEAKER:
    """
    current_speaker = "unknown"
    results = []

    for seg in segments:
        text = seg["text"]
        match = re.match(r'^(?:>>)?\s*\[?([A-Z][A-Z\s]+)\]?\s*:', text)
        if match:
            current_speaker = match.group(1).strip().title()
            text = re.sub(r'^(?:>>)?\s*\[?[A-Z][A-Z\s]+\]?\s*:\s*', '', text)

        results.append({
            **seg,
            "speaker": current_speaker,
            "text": text.strip()
        })

    return results


async def _llm_speaker_detection(
    segments: list[dict],
    known_speakers: list[str],
    batch_size: int = 30
) -> list[dict]:
    """
    Sends segments in batches to LLM for speaker labeling.
    """
    speakers_str = ", ".join(known_speakers)
    labeled = []

    # process in batches to stay within token limits
    for i in range(0, len(segments), batch_size):
        batch = segments[i:i + batch_size]

        chunk_text = "\n".join([
            f"[{s['timestamp']}s] {s['text']}"
            for s in batch
        ])

        prompt = f"""You are analyzing a political debate transcript.
Known speakers: {speakers_str}

Assign a speaker to each line based on context, speaking style, and content.
If you cannot determine the speaker, use "unknown".

Transcript:
{chunk_text}

Return ONLY a JSON array, no other text:
[{{"timestamp": 0.0, "speaker": "name"}}]

One entry per line above, in the same order."""

        try:
            async with httpx.AsyncClient(timeout=20) as client:
                r = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                        "HTTP-Referer": "https://clearview.app",
                        "X-Title": "ClearView",
                    },
                    json={
                        "model": "anthropic/claude-haiku-4-5",
                        "messages": [{"role": "user", "content": prompt}]
                    }
                )
                raw = r.json()["choices"][0]["message"]["content"]
                raw = raw.strip().replace("```json", "").replace("```", "")
                labels = json.loads(raw)
                ts_to_speaker = {l["timestamp"]: l["speaker"] for l in labels}

                for seg in batch:
                    labeled.append({
                        **seg,
                        "speaker": ts_to_speaker.get(seg["timestamp"], "unknown")
                    })

        except Exception:
            # if batch fails just append with unknown
            labeled.extend(batch)

    return labeled


def _chunk_segments(segments: list[dict]) -> list[dict]:
    if not segments:
        return []

    chunks = []
    chunk_start = segments[0]["timestamp"]
    chunk_texts = []
    chunk_ts = chunk_start
    chunk_speaker = segments[0].get("speaker", "unknown")

    for seg in segments:
        if seg["timestamp"] - chunk_start >= CHUNK_SECONDS:
            chunks.append({
                "timestamp": chunk_ts,
                "text": " ".join(chunk_texts),
                "speaker": chunk_speaker
            })
            overlap_ts = seg["timestamp"] - OVERLAP_SECONDS
            chunk_texts = [
                s["text"] for s in segments
                if overlap_ts <= s["timestamp"] <= seg["timestamp"]
            ]
            chunk_start = seg["timestamp"]
            chunk_ts = seg["timestamp"]
            chunk_speaker = seg.get("speaker", "unknown")
        else:
            chunk_texts.append(seg["text"])

    if chunk_texts:
        chunks.append({
            "timestamp": chunk_ts,
            "text": " ".join(chunk_texts),
            "speaker": chunk_speaker
        })

    return chunks


def get_segment_at_time(segments: list[dict], timestamp: float, window: float = 30.0) -> str:
    relevant = [
        s for s in segments
        if abs(s["timestamp"] - timestamp) <= window
    ]
    return " ".join([s["text"] for s in relevant])


def get_segments_in_range(segments: list[dict], start: float, end: float) -> list[dict]:
    return [
        s for s in segments
        if start <= s["timestamp"] <= end
    ]


def get_text_in_range(segments: list[dict], start: float, end: float) -> str:
    relevant = get_segments_in_range(segments, start, end)
    return " ".join([s["text"] for s in relevant])


def get_context_around_claim(segments: list[dict], timestamp: float, before: float = 30.0, after: float = 30.0) -> dict:
    before_text = get_text_in_range(segments, timestamp - before, timestamp)
    after_text = get_text_in_range(segments, timestamp, timestamp + after)
    full_text = get_text_in_range(segments, timestamp - before, timestamp + after)
    return {
        "before": before_text,
        "after": after_text,
        "full": full_text,
        "timestamp": timestamp,
        "window_start": timestamp - before,
        "window_end": timestamp + after,
    }


def search_transcript(segments: list[dict], keyword: str) -> list[dict]:
    keyword = keyword.lower()
    return [
        s for s in segments
        if keyword in s["text"].lower()
    ]


def get_speaker_segments(segments: list[dict], start: float, end: float) -> dict:
    relevant = get_segments_in_range(segments, start, end)
    full_text = " ".join([s["text"] for s in relevant])
    word_count = len(full_text.split())
    duration = end - start
    return {
        "segments": relevant,
        "text": full_text,
        "word_count": word_count,
        "duration_seconds": duration,
        "words_per_minute": round((word_count / duration) * 60) if duration > 0 else 0,
        "segment_count": len(relevant),
    }


def format_timestamp(seconds: float) -> str:
    seconds = int(seconds)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def find_claim_in_transcript(segments: list[dict], claim_text: str) -> list[dict]:
    claim_words = set(claim_text.lower().split())
    stop_words = {"the", "a", "an", "is", "was", "are", "were", "in", "of", "to", "and", "or"}
    claim_keywords = claim_words - stop_words
    scored = []
    for seg in segments:
        seg_words = set(seg["text"].lower().split())
        overlap = len(claim_keywords & seg_words)
        if overlap > 0:
            scored.append({
                **seg,
                "relevance": overlap,
                "formatted_time": format_timestamp(seg["timestamp"])
            })
    scored.sort(key=lambda x: x["relevance"], reverse=True)
    return scored[:5]