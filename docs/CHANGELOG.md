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

## 2026-05-02 — refactor(agent): Add Universal Fact Checkers as Priority Override
**Changes:** Implemented a priority-based retrieval system in `agents/base_agent.py`. The system first checks the given claim against a curated list of universal fact-checking organizations (PolitiFact, FactCheck.org, Snopes, etc.). If a match is found, it returns the fact-checker's verdict immediately, bypassing the standard domain-specific retrieval.
**Current status:** Universal fact-check override is implemented and functional, successfully catching claims that have been explicitly fact-checked by the listed organizations.
**Future issues / conflicts:** The list of "universal" fact-checkers is currently hardcoded in `agents/sources.md`. This list represents a specific editorial stance (e.g., favoring ProPublica over Axios) and may need to be expanded or adjusted based on community feedback.