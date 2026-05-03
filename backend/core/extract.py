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

You DISCARD everything that is neither — including speculative
counterfactuals, vague event narration without verifiable specifics, and
characterizations of significance. It is far better to drop a borderline
item than to put it in the wrong bucket.

Categorization is mutually exclusive: one item, one bucket. Three buckets
exist: FACT, OPINION, and DISCARD. The discard bucket is silent (those
items simply do not appear in the output)."""

EXTRACT_PROMPT = """Given this transcript segment, categorize each substantive
political statement into one of two buckets — FACT or OPINION — and DISCARD
everything else.

== FACT bucket ==
A FACT is a specific, falsifiable assertion that a fact-checker could
investigate against data. It MUST contain at least one of:
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
- Characterizations of someone's actions or significance
       ("the proposal does not address the real issue",
        "they have not paid a big enough price for what they've done")

An item is an opinion when it is a contestable position. If reasonable
people across the political spectrum would debate the framing, it is an
OPINION even if it sounds factual.

== DISCARD (do NOT extract) ==
Drop items in any of these categories. Do not put them in either bucket.

- **Filler, greetings, narration, scene-setting**
  ("Welcome back", "Up next", "Let's go to our reporter")
- **Speculative counterfactuals** — statements about what would happen
  in a hypothetical that did not occur. These are unverifiable by
  definition because the precondition is not real.
  EXAMPLES TO DISCARD:
   - "If military action were halted now, it would take 20 years to rebuild"
   - "If Congress had passed the bill, unemployment would have dropped"
   - "Without that policy, things would be much worse"
- **Vague event narration without checkable specifics** — meetings,
  briefings, conversations referenced without a verifiable detail like
  a date, named topic of public record, or quoted outcome.
  EXAMPLES TO DISCARD:
   - "Admiral X met with the President to brief him on issues"
   - "Officials discussed several matters today"
   - "The team is reviewing the situation"
  KEEP if it has a specific named outcome:
   - "Admiral X recommended pulling 5,000 troops from Germany" (named action)
   - "The Pentagon completed its review of Europe force posture" (named outcome)
- **Future promises and aspirational statements with no factual anchor**
   - "We will fight for you", "I plan to bring jobs back"
- **Vague hedges and unattributed claims**
   - "Many people say", "a lot of folks", "everyone knows"
- **Pure rhetoric without a verifiable or contestable claim**
   - "devastating", "incredible", "tremendous"
- **Procedural meta-commentary about the broadcast**
   - "We'll be right back", "More on that after the break"

When borderline between FACT and DISCARD, prefer DISCARD — an empty
fact-check beats a confidently wrong "Unable to verify" verdict on
something that was never fact-shaped to begin with.

When borderline between OPINION and DISCARD, prefer DISCARD unless the
speaker is clearly staking out a contestable position.

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

If a bucket is empty, return [] for it. Both may be empty (entire segment
discarded). That is a valid and common outcome.

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
