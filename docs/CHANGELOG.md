# CHANGELOG

Hand-curated log of changes landing on `main`. Two lines per merge: what changed, and what it means for other roles.

When your PR/commit lands, append an entry under today's date. Conventions:
- Group entries by date (most recent on top).
- Lead with the conventional-commit `type(scope)` of the change.
- Always include a "Affects:" line if other roles need to react.

---

## 2026-05-02

- **chore(docs): scaffold docs/, ADR conventions, and team .gitignore.**
  Adds `docs/STRUCTURE.md` (current repo state), `docs/AGENTIC_WORKFLOW.md` (target architecture), `docs/CHANGELOG.md` (this file), and `docs/decisions/` with ADR-0001/0002/0003. Removes outdated `structure.md` from repo root. Adds `.gitignore` covering Python, Node, secrets, OS files, and per-developer `.claude/` workspaces.
  Affects: everyone — pull main, then read `docs/STRUCTURE.md` and `docs/AGENTIC_WORKFLOW.md` to understand how to pick tasks. Per-developer `.claude/` directories are now gitignored team-wide.

- **refactor(agent): scaffold 5 domain agents and shared transcription pipeline.**
  Creates stub agent files (`agent_immigration.py`, etc.), an `agent_gatekeeper.py`, `core/router.py`, `core/shared_pipeline.py`, and `backend/agents/sources.md` for curated sources.
  Affects: Frontend — API endpoints remain unchanged; the backend now handles domain routing and transcription internally.
