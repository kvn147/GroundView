"""Two-bucket claim extraction (Level 2a).

A single LLM call categorizes each item from the transcript segment as either
a *verifiable factual assertion* (gets fact-checked downstream) or an
*opinion* (gets routed to the OpinionAgent for stance-based lean scoring).

The buckets are mutually exclusive. Borderline items bias toward the fact
bucket — empty fact verification is a clearer failure than a wrong-shaped
opinion verdict on a numeric claim.
"""

import json
import os
from dataclasses import dataclass, field

import httpx
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

SYSTEM_PROMPT = """You are a claim categorization system for political speech.
Your job is to identify two distinct kinds of statements from a transcript:

  1. VERIFIABLE FACTUAL ASSERTIONS — claims grounded in specific, checkable
     reality (statistics, named legislation, dated events, comparative
     superlatives, named-entity actions).
  2. OPINIONS — subjective political positions a speaker is taking
     (policy preferences, value judgments, ideological framings).

You discard everything that is neither (filler, narration, greetings, vague
hedges, future promises with no factual anchor).

Categorization is mutually exclusive: one item, one bucket. When borderline,
prefer the fact bucket."""

EXTRACT_PROMPT = """Given this transcript segment, categorize each substantive
political statement into one of two buckets.

== FACT bucket ==
A FACT is a specific, falsifiable assertion. It MUST contain at least one of:
- A specific number, percentage, or statistic
- A named policy, bill, or legislation
- A historical assertion with a timeframe ("in 2020", "last year", "since 1969")
- A comparative assertion ("more than any", "highest ever", "lowest in 50 years")
- A named entity + specific action ("we passed X", "X country did Y")

== OPINION bucket ==
An OPINION is a subjective political position the speaker is staking out.
Opinions look like:
- Policy preferences ("we need stronger borders", "healthcare should be universal")
- Value judgments about people, parties, or institutions
       ("X is corrupt", "Y is the greatest president")
- Ideological framings of issues ("this is an attack on freedom",
       "regulation is killing innovation")

An item is an opinion only when it is a contestable position, not a
verifiable claim. If an item could be checked against data, it is a FACT.

== DO NOT extract ==
- Filler, greetings, narration, transitions
- Future promises with no factual anchor ("we will fight for you")
- Vague hedges ("many people say", "a lot of folks")
- Pure rhetoric without a claim ("devastating", "incredible")

Return ONLY a JSON object, no other text, no markdown:
{{
  "facts": [
    {{
      "claim": "the clean verifiable assertion",
      "raw_quote": "the exact words from the transcript",
      "timestamp": {timestamp_offset}
    }}
  ],
  "opinions": [
    {{
      "statement": "the clean opinion statement",
      "raw_quote": "the exact words from the transcript",
      "timestamp": {timestamp_offset}
    }}
  ]
}}

If a bucket is empty, return [] for it. Both may be empty.

Transcript segment (starting at {timestamp_offset}s):
{segment}
"""


@dataclass
class ExtractionResult:
    """Output of one ``extract_claims`` call.

    ``facts`` items have shape:    {"claim", "raw_quote", "timestamp"}
    ``opinions`` items have shape: {"statement", "raw_quote", "timestamp"}

    Both lists may be empty independently.
    """

    facts: list[dict] = field(default_factory=list)
    opinions: list[dict] = field(default_factory=list)


async def extract_claims(segment: str, timestamp_offset: float) -> ExtractionResult:
    """Categorize a transcript segment into facts and opinions.

    Single LLM call (Haiku 4.5). Returns ``ExtractionResult``. On parse
    failure or upstream error, returns an empty ``ExtractionResult`` rather
    than raising — the caller treats "no claims" as a neutral outcome.
    """
    prompt = EXTRACT_PROMPT.format(
        segment=segment,
        timestamp_offset=timestamp_offset,
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
                    {"role": "user", "content": prompt},
                ],
            },
        )
        r.raise_for_status()
        raw = r.json()["choices"][0]["message"]["content"]

    raw = raw.strip().replace("```json", "").replace("```", "").strip()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return ExtractionResult()

    if not isinstance(parsed, dict):
        return ExtractionResult()

    facts = _normalize_facts(parsed.get("facts"), timestamp_offset)
    opinions = _normalize_opinions(parsed.get("opinions"), timestamp_offset)
    return ExtractionResult(facts=facts, opinions=opinions)


def _normalize_facts(items, timestamp_offset: float) -> list[dict]:
    if not isinstance(items, list):
        return []
    facts: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        claim = item.get("claim")
        raw_quote = item.get("raw_quote")
        if not claim or not raw_quote:
            continue
        facts.append({
            "claim": claim,
            "raw_quote": raw_quote,
            "timestamp": item.get("timestamp", timestamp_offset),
        })
    return facts


def _normalize_opinions(items, timestamp_offset: float) -> list[dict]:
    if not isinstance(items, list):
        return []
    opinions: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        statement = item.get("statement")
        raw_quote = item.get("raw_quote")
        if not statement or not raw_quote:
            continue
        opinions.append({
            "statement": statement,
            "raw_quote": raw_quote,
            "timestamp": item.get("timestamp", timestamp_offset),
        })
    return opinions
