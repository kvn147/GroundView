# AGENTIC_WORKFLOW.md — Target Architecture

**Status:** Reflects the team's current design after the Chrome-extension pivot. Updated when the team explicitly revises it.
**Companion doc:** [`STRUCTURE.md`](./STRUCTURE.md) describes what's actually on disk now. The gap between this doc and STRUCTURE.md is the work backlog.

---

## Framing

The system surfaces fact-check verdicts on political claims made in YouTube videos, in real time, directly inside the YouTube watch page. Each verdict is paired with a plain-English explanation and named, clickable source links so users can verify for themselves.

**Trust comes from transparency, not from refusing to render verdicts.** Users see the verdict, the reasoning, and the sources behind it. The system prefers established universal fact-checkers (PolitiFact, FactCheck.org, Snopes, AP, Reuters, Washington Post) when those organizations have already covered a claim, and falls back to domain-specific evidence retrieval when they have not.

This is a deliberate change from the earlier "attribution, never adjudication" framing. The team chose verdict-rendering because (1) the Chrome-extension surface needs an at-a-glance signal users can read in real time, (2) the universal-fact-checker tier provides external grounding for verdicts, and (3) explanations + source links preserve user agency to disagree.

---

## Pipeline

### Level 0 — Ingestion (Chrome extension)
- Extension activates on any `youtube.com/watch` URL.
- Extracts page metadata: title, description, meta keywords/tags.
- Listens for SPA navigations (YouTube does not full-reload between videos).

### Level 1 — Political gating (lightweight LLM)
- Before any expensive work, the extension calls the backend with the video's metadata: "is this a political video?"
- Endpoint: `POST /api/check-political` → `{ isPolitical: boolean }`.
- Non-political videos exit the pipeline here. No fact-check UI is injected.

### Level 2 — Claim extraction (frontier model)
- For political videos, the backend extracts factual claims from available text (captions, description, transcript when available).
- Strict verifiability filter: only specific, falsifiable assertions. No opinion, no rhetoric, no future predictions.

### Level 3 — Topic routing
- Each claim is routed to one or more domain agents based on topic.
- **Topics on disk:** `immigration`, `healthcare`, `crime`, `economy`, `education`.
- Hybrid routing: keyword tables for fast deterministic matches, small classifier or LLM fallback for ambiguous cases. Multi-label routing is allowed.
- Out-of-scope claims (no topic match) skip Level 4 and are surfaced with no verdict, or dropped, depending on UI policy.

### Level 4 — Evidence retrieval (per claim)
Each claim hits two tiers in order:

**Tier A — Universal fact-checker override.** The agent first asks an LLM whether the claim has been *explicitly* fact-checked by PolitiFact, FactCheck.org, Snopes, AP Fact Check, Reuters Fact Check, or Washington Post Fact Checker. If yes, the agent returns that fact-checker's verdict and reasoning. If no, the agent returns the literal string `NO_FACT_CHECK_FOUND` and Tier B runs.

**Tier B — Domain agent retrieval.** Domain-specific LLM call retrieves evidence from the topic agent's source list (BLS, FRED, USCIS, FBI/UCR, NCES, etc.). Returns Markdown with synthesized facts, statistics, and named sources.

### Level 5 — Verdict rendering (LLM)
- The pipeline assembles per-claim verdicts: `True | Mostly True | Mixed | Mostly False | False`, plus a plain-English explanation and a list of named, clickable source links.
- Per-video aggregates: a 1–5 trustworthiness score, a label (e.g., "Mixed Accuracy"), a political-lean estimate (0..1 with a label), a one-paragraph summary, and a deduplicated source list with citation counts.
- **Verdicts are LLM-rendered, not rule-based.** This is a deliberate trade: the system gains flexibility and per-claim explanation quality at the cost of the inspectability that a rule-based classifier would have offered. The LLM is constrained by the universal-fact-checker tier and by the named sources retrieved in Level 4 — its verdict should be defensible against those sources.

### Level 6 — UI (Chrome extension content script)
The extension injects three UI elements into the YouTube watch page:
- **Fact-check card** under `#middle-row`: video summary, trustworthiness score, political-lean meter, expandable per-claim list, aggregated source chips.
- **Record button** in the YouTube player controls (`.ytp-right-controls`): user marks a clip in/out and the extension fact-checks just that span.
- **Clip sidebar** in `#secondary-inner`: timestamped clip results, click-to-seek on timestamps.

All extension state lives in the content script — no popup, no options page (currently).

### Level 7 — Eval (TBD)
- The original 5-clip hand-annotated eval harness is no longer the right shape (extension targets arbitrary YouTube videos, not a fixed clip set).
- Replacement undecided. Likely candidates: (a) a fixed corpus of 20–50 hand-labeled real-world claims tested against the verdict pipeline; (b) regression tests on the universal-fact-checker tier where the expected verdict is known.

---

## Inter-level contracts

These types are the API between extension and backend, and between backend levels.

```typescript
// Level 1 — Political gating
type CheckPoliticalRequest = {
  title: string,
  description: string,
  tags: string,
  aiDescription?: string
}
type CheckPoliticalResponse = { isPolitical: boolean }

// Level 5 output — full video analysis
type Verdict = "True" | "Mostly True" | "Mixed" | "Mostly False" | "False"

type Source = { name: string, url: string }

type Claim = {
  id: string,
  text: string,
  verdict: Verdict,
  explanation: string,        // plain-English, references the sources
  sources: Source[]
}

type PoliticalLean = { label: string, value: number }   // value in 0..1

type VideoAnalysis = {
  summary: string,
  trustworthinessScore: number,                          // 1..5
  maxScore: number,                                      // currently 5
  trustworthinessLabel: string,                          // e.g. "Mixed Accuracy"
  politicalLean: PoliticalLean,
  claims: Claim[],
  aggregatedSources: (Source & { citedCount: number })[]
}

// Level 5 output — single-clip analysis (recorded by user)
type ClipAnalysis = {
  startTime: number,                                     // seconds
  endTime: number,
  claim: string,
  verdict: Verdict,
  explanation: string,
  sources: Source[]
}
```

---

## Backend endpoints (consumed by the extension)

- `POST /api/check-political` — Level 1 gating.
- `POST /api/analyze-video` — full video analysis. Body: `{ url: string }`. Returns `VideoAnalysis`.
- `POST /api/analyze-clip` — single clip analysis. Body: `{ url: string, startTime: number, endTime: number, captions?: string }`. Returns `ClipAnalysis`.

All three are currently mocked by `chrome-extension/mock.js`; real implementations are pending.

---

## MVP scope

**Must-haves (the spine):**
- Chrome extension that activates on `youtube.com/watch`, handles SPA navigation, and recovers cleanly across video changes.
- Political gating endpoint working on real metadata.
- Per-video full-analysis endpoint returning the `VideoAnalysis` contract.
- Per-clip clip-analysis endpoint returning the `ClipAnalysis` contract.
- Universal-fact-checker tier (Tier A) implemented and demonstrably overriding verdicts when applicable.
- 5 domain agents (`immigration` / `healthcare` / `crime` / `economy` / `education`) wired to retrieval.
- Topic routing into the 5 domains.
- Verdict + explanation + sources rendered inside the YouTube DOM.
- Demo on a real political YouTube video, end to end.

**Cut entirely (do not build, do not pitch):**
- Pre-shipped 5-clip library with VTT/SRT (replaced by live YouTube interaction via the extension).
- Audio transcription pipelines (Whisper, faster-whisper) — extension uses YouTube's existing captions/description text.
- Speaker diarization.
- Verification sources outside the universal-fact-checker tier and the existing per-domain source lists.
- Extension UI animations / transitions / micro-interactions.
- True async streaming (batch-per-claim is fine).
- React sidebar / standalone web app surface (extension is the only front end now).

---

## Caching invariant

Same input must never hit an external API twice across a session. Disk cache keyed by content hash, with the model string included in the key so a model swap correctly invalidates.

---

## Open team decisions (pull from these when picking work)

- **Verdict labels.** The 5-label set (`True | Mostly True | Mixed | Mostly False | False`) comes from the mock and matches PolitiFact's coloring. Add `Insufficient Evidence` as a sixth label when Tier A returns `NO_FACT_CHECK_FOUND` *and* Tier B comes back empty? Currently undecided.
- **Eval harness shape.** See Level 7. Needed before we can claim measurable accuracy.
- **Latency targets.** "Real time" inside the YouTube watch page implies a budget. No target has been set; assume best-effort for now.
- **Authentication / billing.** OpenRouter key is per-developer for now; production extension would need a server-side key with abuse mitigation. Out of scope for the demo.
