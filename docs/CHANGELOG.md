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