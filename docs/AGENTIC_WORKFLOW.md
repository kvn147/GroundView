# AGENTIC_WORKFLOW.md — Target Architecture

**Status:** North-star design. Doesn't change unless the team explicitly revises it.
**Companion doc:** [`STRUCTURE.md`](./STRUCTURE.md) describes what's actually on disk now. The gap between this doc and STRUCTURE.md is the work backlog.

---

## Framing discipline (non-negotiable)

The system **never renders its own verdicts.** It aggregates citations from existing reputable sources (PolitiFact, ProPublica) and lets the user click through. **Every output is attribution, never adjudication.**

This framing defuses bias attacks and is the project's identity. Do not drift from it during development.

---

## Pipeline — six levels

### Level 0 — Ingestion (no model)
- Pre-downloaded video + caption files (VTT/SRT).
- Manifest-driven clip library: `{id, title, year, speakers, video_path, caption_path}`.

### Level 1 — Caption Parsing (no model)
- Parse VTT/SRT into segments: `[{speaker, text, start_time, end_time}, ...]`.
- Group consecutive segments into claim-bearing windows (~30–60s with overlap).
- Captions are ground truth. **No transcription model in the pipeline.**

### Level 2a — Claim Extraction (frontier model)
- Claude Sonnet via OpenRouter, structured output, strict verifiability filter.
- Output: typed `Claim` objects with topics, timestamps, speaker.

### Level 2b — Topic Routing (hybrid)
- Keyword tables first (deterministic), Haiku fallback for ambiguous cases.
- Multi-label allowed.
- Out-of-scope claims (no topic match, no LLM rescue) flow to `insufficient_coverage` rather than being force-routed (see ADR-0003).

### Level 3 — Topic Agents (cheap LLM + embeddings)
- 4 agents, each with hard-coded `ALLOWED_SOURCES` frozenset.
- Per-agent: small-LLM query construction + embedding similarity matching.
- **Permission enforcement at agent boundary** — agent raises `PermissionError` if asked to query a source outside its allowlist. This is the ConductorOne thesis as code; keep it visible and uncompromising.

The four agents:

| Agent                       | Allowed sources                            |
| --------------------------- | ------------------------------------------ |
| `LegislativeAgent`          | ProPublica Congress API                    |
| `EconomyAgent`              | PolitiFact (economy-tagged subset)         |
| `HistoricalStatementsAgent` | PolitiFact (prior-statements subset)       |
| `PolicyOutcomeAgent`        | PolitiFact (policy-outcome subset)         |

### Level 4a — Aggregation (no model)
- Collect verification results across agents, deduplicate, group by agent.

### Level 4b — Confidence Classification (**no model — RULES**)
- Auditable Python rules. **Critical: never put an LLM here.**
- This is the most bias-sensitive decision in the system; it must be inspectable.
- Output states: `verified` / `contradicted` / `insufficient_coverage` / `sources_disagree`.

### Level 5 — Rendering (no model)
- React components, timeline-synced annotation cards.

### Level 6 — Eval Harness (no model in critical path)
- Batch runner against 5 ground-truth-annotated clips.
- Three numbers: extraction accuracy, routing accuracy, citation relevance.
- Aggressive caching by content hash.

---

## Inter-level contracts

These types are the API between levels. Changes require team agreement.

```typescript
// Level 1 output
type CaptionSegment = {
  speaker: string | null,       // from caption metadata if present
  text: string,
  start_time: number,           // seconds
  end_time: number
}

// Level 2a output
type Claim = {
  claim_text: string,           // verbatim from caption
  claim_type: "voting_record" | "statistic" | "prior_statement"
            | "policy_outcome" | "biographical",
  topics: string[],             // multi-label routing tags (canonical IDs — see ADR-0002)
  speaker: string,
  start_time: number,
  end_time: number,
  verifiability: "structured_data" | "fact_checker_likely",
  extraction_confidence: number
}

// Level 3 output (per agent)
type VerificationResult = {
  agent: string,                // "LegislativeAgent" etc.
  allowed_sources: string[],    // for activity panel display
  queried_sources: string[],
  matched_record: object | null,
  rating_or_value: string | null,
  url: string | null,
  date: string | null,
  confidence: number,
  cache_hit: boolean
}

// Level 5 input
type Annotation = {
  claim: Claim,
  results: VerificationResult[],
  confidence_state: "verified" | "contradicted"
                  | "insufficient_coverage" | "sources_disagree"
}
```

---

## MVP scope — locked

**Must-haves (the spine):**
- Curated 5-clip library with VTT/SRT captions.
- Caption ingestion and parsing.
- Claim extraction with verifiability filter.
- Hybrid topic router (keyword + LLM fallback) into 4 topics.
- 4 topic agents with allowlist enforcement.
- Rule-based confidence classifier.
- Annotation sidebar UI synced to video timeline.
- Agent activity panel showing allowlist, queried sources, cache status.
- Eval harness on the 5 hand-annotated clips.

**Cut entirely (do not build, do not pitch):**
- Live YouTube URL ingestion.
- Audio transcription (Whisper, faster-whisper, etc.).
- Speaker diarization.
- Additional verification sources beyond ProPublica + PolitiFact (architecture is "extensible to these," nothing more).
- Nemotron fine-tuning.
- Browser extension.
- True async streaming (use batch-per-chunk instead).
- Animations, transitions, micro-interactions.

---

## Caching invariant

Same input must never hit an external API twice across the hackathon. Disk cache keyed by content hash, with the model string included in the key so a model swap correctly invalidates.

---

## Cross-references

- **ADR-0001** — OpenRouter as the single LLM gateway.
- **ADR-0002** — Topic name canonicalization (`legislative` / `economy` / `historical_statements` / `policy_outcome`).
- **ADR-0003** — No-route claims become `insufficient_coverage`, not forced into a closest topic.
