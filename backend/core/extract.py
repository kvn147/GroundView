import json
import httpx
import os
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

SYSTEM_PROMPT = """You are a claim detection system for political speech.
Your job is to identify specific, verifiable factual assertions only.
You never extract opinions, predictions, promises, or rhetoric."""

EXTRACT_PROMPT = """Given this transcript segment, extract ONLY specific verifiable factual assertions.

A valid claim MUST contain at least one of:
- A specific number, percentage, or statistic
- A named policy, bill, or legislation
- A historical assertion with a timeframe ("in 2020", "last year", "since 1969")
- A comparative assertion ("more than any", "highest ever", "lowest in 50 years")
- A named entity + specific action ("we passed X", "X country did Y")

Return ONLY a JSON array, no other text, no markdown:
[
  {{
    "claim": "the clean verifiable assertion",
    "timestamp": {timestamp_offset},
    "raw_quote": "the exact words from the transcript"
  }}
]

If no valid claims exist, return an empty array: []

DO NOT extract:
- Opinions ("I believe...", "I think...")
- Future promises ("we will...", "I plan to...")
- Emotional rhetoric ("devastating", "incredible")
- Vague assertions ("many people", "a lot of")

Transcript segment (starting at {timestamp_offset}s):
{segment}
"""


async def extract_claims(segment: str, timestamp_offset: float) -> list[dict]:
    prompt = EXTRACT_PROMPT.format(
        segment=segment,
        timestamp_offset=timestamp_offset
    )

    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "HTTP-Referer": "https://clearview.app",
                "X-Title": "ClearView",
            },
            json={
                "model": "anthropic/claude-haiku-4.5",
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt}
                ]
            }
        )
        r.raise_for_status()
        raw = r.json()["choices"][0]["message"]["content"]

    raw = raw.strip().replace("```json", "").replace("```", "").strip()

    try:
        results = json.loads(raw)
    except json.JSONDecodeError:
        return []

    claims = []
    for r in results:
        if not isinstance(r, dict):
            continue
        if not r.get("claim") or not r.get("raw_quote"):
            continue
        claims.append({
            "claim": r["claim"],
            "timestamp": r.get("timestamp", timestamp_offset),
            "raw_quote": r["raw_quote"]
        })

    return claims