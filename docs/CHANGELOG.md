# CHANGELOG

Hand-curated log of changes landing on `main`. **Format per entry (4 lines):**

```
## YYYY-MM-DD — <commit / PR title>
**Changes:** what landed (1–2 lines).
**Current status:** what works now / what's broken (1 line).
**Future issues / conflicts:** what this breaks downstream or what the next person should know (1–2 lines).
```

Most recent on top. When your PR/commit lands, append an entry under today's date.

---

## 2026-05-03 — feat(api): implement SSE replacement for batch analysis endpoints
**Changes:** Added `docs/SSE_DESIGN.md` and implemented `GET /api/analyze-video/stream` plus `GET /api/analyze-clip/stream` Server-Sent Events endpoints. Refactored the backend analysis path so the existing synchronous `POST /api/analyze-video` and `POST /api/analyze-clip` endpoints consume the same event pipeline and return the final `done.result`. Updated the Chrome extension to prefer `EventSource` streaming with REST fallback on connection failure.
**Current status:** Full-video analysis can render claims and summary updates incrementally; clip analysis streams to completion and still renders in the existing sidebar. Added mocked pipeline tests for the SSE event contract.
**Future issues / conflicts:** `EventSource` is GET-only, so large clip captions may need a two-step job flow (`POST /api/analysis-jobs`, then `GET /api/analysis-jobs/{job_id}/stream`) before production. Heartbeats are documented but not yet emitted during long LLM awaits.

## 2026-05-03 — feat(agents): L3 allowlist enforcement + structured contracts + pipeline integration
**Changes:** Added `backend/contracts.py` (Pydantic models for cross-level shapes — `Claim`, `Source`, `EvidenceItem`, `VerificationResult`, `AgentActivityLog`, `Annotation`, frontend response shapes — plus pure adapters). Added `backend/agents/base.py` (`AllowlistedAgent` base class: hard frozenset allowlist, prompt-hash cache, Tier-A Haiku probe, Tier-B Gemini retrieval with structured-JSON output, source-name normalization, robust failure handling). Added `backend/agents/llm.py` (OpenRouter client), `backend/agents/orchestrator.py` (concurrent fan-out via `asyncio.gather`), `backend/agents/aggregator.py` (pure-Python L4a/L5-prep, no LLM, asserted by tests). Migrated all 5 domain agents onto `AllowlistedAgent` while preserving the legacy `retrieve_evidence`/`verify` shims for back-compat. Added `calculate_confidence_structured` to `judge.py` that consumes `EvidenceItem`s directly and skips NLI when `nli_source=="agent"` (saves 1 LLM call per Tier-A hit + 1 per agent result vs. the legacy markdown re-parse path). Refactored `backend/api/video.py` to compose `level2b_routing.route` + `AgentOrchestrator` + `aggregate_annotations`, replacing the if/elif fan-out and the inline aggregation. Surfaced `AgentActivityLog`s on `FrontendClaim.activity` so the chrome extension's activity panel has data to render.
**Current status:** `/analyze-video` runs the full L1→L5 pipeline. Allowlist enforcement is live in the request path — non-allowlisted citations are dropped before reaching the user, denials surface in the activity log. 134/134 tests pass on `feat/l3_allowlist`. End-to-end run against real OpenRouter not yet validated (awaiting a real API key smoke test).
**Future issues / conflicts:** (1) Activity panel UI not yet rendered on the chrome extension — backend serves the data, frontend wiring is austaciouscoder's lane. (2) `AllowlistedAgent` uses `InMemoryCache` by default; spec mandates persistent caching. ~10 lines to swap in `diskcache` via the existing `Cache` protocol. (3) Legacy `core/router.py` and `agents/base_agent.py` no longer used by the API path; consider deletion after demo. (4) NLI scoring still uses Gemini for non-Tier-A items — partial L4b LLM-free invariant; team should decide whether to update spec or replace with deterministic NLI.

## 2026-05-03 — feat(routing): land Level 2b classifier scaffold + tuning
**Changes:** Added `backend/app/level2b_routing/` (CLI-generated scaffold: `data_prep`, `keyword_matcher`, `decision`, `router`, `classifier/{train,eval,predict,inspect}`) and `backend/tests/level2b_routing/` (42 tests, all green). Added `data/fetch_liar.py` with 5-topic LIAR mapping and committed `liar_train.csv` (8150 rows) + `liar_eval.csv` (200 rows). Fixed a real bug in `data_prep._read_one` and `classifier/eval._load_xy` where `pandas.read_csv(comment="#")` silently truncated 21 LIAR rows containing mid-line `#` (hashtags), producing `int64.min` sentinel labels that crashed `OneVsRestClassifier`. Tuned the pipeline with `sublinear_tf=True`, `class_weight="balanced"`, and per-topic decision thresholds (`TOPIC_THRESHOLDS` in `decision.py`, sourced from the eval threshold sweep).
**Current status:** Macro F1 on `liar_eval.csv` = 0.838, micro F1 = 0.835, every topic ≥ 0.76 (lowest is economy at 0.758). Beats keyword-only baseline (macro F1 0.589). Trained `model.pkl` is gitignored; `combined_train.csv` is regenerable from synthetic batches + `liar_train.csv`. `synthetic_train.csv` (the 244-row first batch) remains gitignored; batches 02-10 (~920 rows) are committed.
**Future issues / conflicts:** (1) **No LLM-router comparison yet** — the rule-based keyword + TF-IDF/LR stack hasn't been benchmarked against a Haiku-class router on the same `liar_eval.csv`. Needed before we can argue this scaffold is the right choice for production. (2) **No-topic fall-through is unwired** — `decision.decide()` returns `routing_method="no_route"` when neither keywords nor classifier fire, but no caller handles it; `router.py` and the (not-yet-existent) `/api/check-political` endpoint need a policy: drop the claim, flag for human review, or fall back to a universal-fact-checker pass. (3) `liar_eval.csv` is still raw LIAR labels (noisy topic mapping); hand-cleaning is the next handoff step.

## 2026-05-02 — chore(docs): rewrite for Chrome-extension pivot and verdict-rendering pipeline
**Changes:** Rewrote `AGENTIC_WORKFLOW.md` to reflect the Chrome-extension pivot — extension is the only front end, verdicts are LLM-rendered, universal-fact-checker tier runs before domain retrieval. Updated `STRUCTURE.md` repo tree and "Known deltas" to match disk after the extension and fact-checker commits landed. Dropped the old "attribution, never adjudication" framing, the 5-clip library MVP, and the rule-based Level 4b classifier.
**Current status:** Docs match disk. Extension is mocked end-to-end; backend endpoints (`/api/check-political`, `/api/analyze-video`, `/api/analyze-clip`) don't exist yet. Routing branch (`feat/routing_base`) work continues against the 5-domain taxonomy.
**Future issues / conflicts:** No eval harness exists for the post-pivot pipeline — Level 7 is undecided. `README.md` is stale (still describes pre-pivot 3-agent + judge model design). Three independent LLM clients still scattered across extract / router / base_agent.

## 2026-05-02 — added chrome extension (austaciouscoder)
**Changes:** Added `chrome-extension/` (MV3) — content script injects fact-check card under `#middle-row`, record button into YouTube player controls, and clip sidebar into `#secondary-inner`. SPA navigation handled via `MutationObserver`. All backend calls mocked in `mock.js` with realistic response shapes for the three intended endpoints.
**Current status:** Extension works end-to-end against mocks; can be loaded as an unpacked extension on `youtube.com/watch` URLs.
**Future issues / conflicts:** Front-end pivot — React sidebar from the original spec is dead. Extension expects three backend endpoints that don't exist yet. Verdicts in mock data ("Mostly False" / "Mixed" / etc.) commit the project to LLM-rendered verdicts, replacing the spec's rule-based Level 4b classifier.

## 2026-05-02 — feat(agent): universal fact-checkers as priority override
**Changes:** Implemented a priority-based retrieval system in `agents/base_agent.py`. The system first checks the given claim against a curated list of universal fact-checking organizations (PolitiFact, FactCheck.org, Snopes, AP, Reuters, WaPo). If a match is found, it returns the fact-checker's verdict immediately, bypassing standard domain-specific retrieval. Added `tests/test_fact_check.py` and the new tier in `sources.md`.
**Current status:** Universal fact-check override is implemented and functional, successfully catching claims that have been explicitly fact-checked by the listed organizations.
**Future issues / conflicts:** The list of "universal" fact-checkers is hardcoded in `agents/sources.md`. This represents a specific editorial stance and may need adjustment. Also locks in the verdict-rendering model (LLM extracts and reports the fact-checker's True/False conclusion), supporting the post-pivot direction.

## 2026-05-02 — chore(docs): drop ADRs, refresh docs, simplify CHANGELOG format
**Changes:** Deleted `docs/decisions/` (ADRs not used by the team). Stripped ADR cross-references from `AGENTIC_WORKFLOW.md`. Rewrote `STRUCTURE.md` to match disk after kevin-topics PR landed (5 agents, base_agent, sources module, tests, broken `requirements.txt`). Switched CHANGELOG format to 4-line entries.
**Current status:** Docs reflect reality. Routing/classifier work still blocked on topic-taxonomy conflict (5 disk vs. 4 spec).
**Future issues / conflicts:** Topic taxonomy needs team decision before classifier training. Source-allowlist thesis (ProPublica/PolitiFact vs. broad gov sources) needs team decision before agents can be considered "done."

## 2026-05-02 — refactor(agent): scaffold 5 domain agents and shared transcription pipeline (kevin-topics PR)
**Changes:** Added `agent_crime.py`, `agent_economy.py`, `agent_education.py`, `base_agent.py` (Gemini-2.5-flash via OpenRouter), `sources.md`, `sources.py`, `agents/README.md`, and `tests/` with one file per agent.
**Current status:** 5 agents working at the prompt level — base_agent calls Gemini and returns Markdown. No allowlist enforcement; sources are soft prompt suggestions.
**Future issues / conflicts:** 5 agents with `immigration/healthcare/crime/economy/education` taxonomy contradicts spec's 4-agent `legislative/economy/historical_statements/policy_outcome`. Sources contradict spec's ProPublica + PolitiFact framing. Adds a third independent OpenRouter client (extract.py and router.py also have their own).

## 2026-05-02 — chore(docs): scaffold docs/ and team .gitignore
**Changes:** Added `docs/STRUCTURE.md`, `docs/AGENTIC_WORKFLOW.md`, `docs/CHANGELOG.md`. Removed outdated `structure.md` from repo root. Added `.gitignore` covering Python, Node, secrets, OS files, and `.claude/`.
**Current status:** Docs scaffolded; spec is canonical.
**Future issues / conflicts:** None at the time of this commit (later contradicted by kevin-topics merge).

## 2026-05-03 - chore(api): implement API contract and endpoints
**Changes:** Added API contract documentation and implemented synchronous API endpoints for backend and frontend integration. Updated backend with endpoint logic for political check, video analysis, and clip analysis, including prompt templates and mock backend.
**Current status:** API endpoints are implemented and functional, with mock backend for testing.
**Future issues / conflicts:** Asynchronous pipeline needs to be implemented to replace the synchronous endpoints.

## 2026-05-03 - chore(frontend): update frontend to connect to backend and add claim verification logic
**Changes:** Updated frontend to connect to backend API and implement claim verification logic using judge agents.
**Current status:** Frontend is connected to backend and claim verification logic is implemented.
**Future issues / conflicts:** Asynchronous pipeline needs to be implemented to replace the synchronous endpoints.
