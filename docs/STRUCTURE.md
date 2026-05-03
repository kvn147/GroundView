# STRUCTURE.md — Current Repo State

**Status:** Snapshot of what's actually on disk as of the most recent commit on `main`.
**Companion doc:** [`AGENTIC_WORKFLOW.md`](./AGENTIC_WORKFLOW.md) describes the target architecture. The gap between the two is the work backlog — pick tasks from those gaps.
**Update rule:** Refresh this file whenever files are added, moved, or deleted on `main`.

---

## Repo tree

```
beaverhacks-project/
├── .gitignore                       # team-level ignore (Python, Node, secrets, OS, .claude/)
├── README.md                        # public project pitch and high-level summary
├── infrastructure.png               # architecture diagram referenced by README
│
├── backend/                         # Python backend — agent pipeline lives here
│   ├── main.py                      # (empty stub) intended FastAPI entry point
│   ├── api/
│   │   └── video.py                 # FastAPI routes: POST /process-video, WS /ws/claims/{job_id}
│   ├── agents/
│   │   ├── agent_healthcare.py      # (empty stub) topic agent for healthcare claims
│   │   └── agent_immigration.py     # (empty stub) topic agent for immigration claims
│   ├── core/
│   │   ├── __init__.py
│   │   ├── extract.py               # claim extraction via Haiku 4.5 over OpenRouter
│   │   ├── router.py                # claim → topic classifier (immigration/healthcare) via Haiku
│   │   └── transcript.py            # YouTube transcript fetch + 60s chunking with 10s overlap
│   └── eval/
│       └── README.md                # placeholder — eval harness not yet built
│
└── docs/
    ├── STRUCTURE.md                 # this file
    ├── AGENTIC_WORKFLOW.md          # target architecture (spec)
    ├── CHANGELOG.md                 # human-curated log of changes landing on main
    └── decisions/                   # ADRs — one file per cross-team decision
        ├── 0001-openrouter-as-llm-gateway.md
        ├── 0002-topic-name-canonicalization.md
        └── 0003-no-route-to-insufficient-coverage.md
```

---

## What works today

- **Transcript ingestion** (`core/transcript.py`): pulls captions from a YouTube URL via `youtube-transcript-api`, normalizes timestamps, chunks into ~60s windows with 10s overlap.
- **Claim extraction** (`core/extract.py`): sends a chunk + system prompt to Haiku 4.5 via OpenRouter, parses the JSON-array response, drops malformed entries. Strict verifiability filter in the prompt.
- **Topic classification** (`core/router.py`): single-label classifier for two domains (`immigration`, `healthcare`) via Haiku. Returns `(domain, confidence)` and a `needs_fallback(confidence)` helper at threshold 0.6.

## What's stubbed or broken

- `backend/main.py` — empty file. No FastAPI app instance, the API router in `api/video.py` is unwired.
- `backend/agents/agent_healthcare.py`, `agent_immigration.py` — empty files. Topic agents have no implementation.
- `backend/api/video.py` — imports `route_claim_to_agent` from `core.router`, but that function doesn't exist (the router exports `classify_claim` and `needs_fallback`). **Import will fail at runtime.**
- `backend/eval/` — only a one-line README. No harness, no fixtures, no ground truth.
- No frontend directory yet.
- No `clips/`, `contracts/`, or `scripts/` directories yet.

## Known deltas vs. AGENTIC_WORKFLOW.md (target)

These are the gaps to pick from when looking for work:

1. **Topic agents.** Disk has 2 (`healthcare`, `immigration`). Target has 4 (`legislative`, `economy`, `historical_statements`, `policy_outcome`). No agent has `ALLOWED_SOURCES` allowlist enforcement yet.
2. **Transcription vs. captions.** Disk pulls live YouTube transcripts. Target uses pre-shipped VTT/SRT caption files for a curated 5-clip library. No `clips/manifest.json` exists.
3. **Routing topology.** Disk: single-label LLM classifier. Target: keyword tables → small-LLM fallback, multi-label allowed, with a `no_route → insufficient_coverage` path (see ADR-0003).
4. **Levels not yet present:** Level 4a aggregation, Level 4b rule-based confidence classifier, Level 5 render API, Level 6 eval harness.
5. **Shared LLM client.** Both `extract.py` and `router.py` independently construct `httpx.AsyncClient` calls to OpenRouter with hard-coded model strings. Target: one `shared/llm_clients.py` factory + `shared/model_config.py` registry (see ADR-0001).
6. **Contracts module.** No `/contracts/` directory yet. `Claim`, `VerificationResult`, `Annotation` types are not formally defined anywhere.
7. **Topic name canonicalization.** Routing currently uses `"immigration"`, `"healthcare"`, `"other"`. Target uses canonical IDs `legislative` / `economy` / `historical_statements` / `policy_outcome` (see ADR-0002).
8. **API surface.** `/process-video` returns a fake `job_id`; the WebSocket handler is a comment-only stub.

When picking up a task, find the corresponding section in `AGENTIC_WORKFLOW.md` for the contract/intent, then update this file when your work lands.
