# STRUCTURE.md — Current Repo State

**Status:** Snapshot of what's actually on disk on `main`.
**Companion doc:** [`AGENTIC_WORKFLOW.md`](./AGENTIC_WORKFLOW.md) describes the target architecture. The gap between the two is the work backlog — pick tasks from those gaps.
**Update rule:** Refresh this file whenever files are added, moved, or deleted on `main`.

---

## Repo tree

```
beaverhacks-project/
├── .gitignore                       # team-level ignore (Python, Node, secrets, OS, .claude/, backend/venv/)
├── README.md                        # public project pitch and high-level summary
├── infrastructure.png               # architecture diagram referenced by README
│
├── backend/                         # Python backend — agent pipeline lives here
│   ├── main.py                      # (empty stub) intended FastAPI entry point
│   ├── requirements.txt             # only google-genai + python-dotenv — UNDERSTATED, see "broken" below
│   ├── api/
│   │   └── video.py                 # FastAPI routes: POST /process-video, WS /ws/claims/{job_id}
│   ├── agents/
│   │   ├── README.md                # describes 5 domains: Healthcare, Immigration, Crime, Economy, Education
│   │   ├── base_agent.py            # shared async runner; calls google/gemini-2.5-flash via OpenRouter
│   │   ├── agent_crime.py           # crime domain agent
│   │   ├── agent_economy.py         # economy domain agent
│   │   ├── agent_education.py       # education domain agent
│   │   ├── agent_healthcare.py      # healthcare domain agent
│   │   ├── agent_immigration.py     # immigration domain agent
│   │   ├── sources.md               # curated source lists per domain (BLS, CDC, FBI, etc.)
│   │   └── sources.py               # parses sources.md and returns formatted source strings per domain
│   ├── core/
│   │   ├── __init__.py
│   │   ├── extract.py               # claim extraction via Haiku 4.5 (raw httpx → OpenRouter)
│   │   ├── router.py                # single-label classifier into 5 domains (raw httpx → OpenRouter, Haiku)
│   │   └── transcript.py            # YouTube transcript fetch + 60s chunking with 10s overlap
│   ├── eval/
│   │   └── README.md                # placeholder — eval harness not yet built
│   └── tests/
│       ├── test_crime.py
│       ├── test_economy.py
│       ├── test_education.py
│       ├── test_healthcare.py
│       ├── test_immigration.py
│       └── test_edge_cases.py
│
└── docs/
    ├── STRUCTURE.md                 # this file
    ├── AGENTIC_WORKFLOW.md          # target architecture
    └── CHANGELOG.md                 # 4-line entries per commit/PR (changes, status, future issues)
```

---

## What works today

- **Transcript ingestion** (`core/transcript.py`): pulls captions from a YouTube URL via `youtube-transcript-api`, normalizes timestamps, chunks into ~60s windows with 10s overlap.
- **Claim extraction** (`core/extract.py`): sends a chunk + system prompt to Haiku 4.5 via OpenRouter, parses JSON-array response, drops malformed entries. Strict verifiability filter in the prompt.
- **Topic classification** (`core/router.py`): single-label classifier into 5 domains (`immigration`, `healthcare`, `crime`, `economy`, `education`) via Haiku. Returns `(domain, confidence)` and a `needs_fallback(confidence)` helper at threshold 0.6. Falls back to `"other"` on parse failure or unknown domain.
- **Domain agents** (`agents/agent_*.py`): each agent calls `base_agent.run_domain_agent(...)` which uses `google/gemini-2.5-flash` over OpenRouter to retrieve evidence as Markdown. Sources are dropped into the system prompt as soft suggestions.
- **Source registry** (`agents/sources.md` + `sources.py`): curated source lists per domain, parsed at runtime.
- **Test scaffolding** (`tests/`): one test file per agent plus `test_edge_cases.py`. Coverage / pass status not verified.

## What's stubbed or broken

- `backend/main.py` — empty file. No FastAPI app instance, the API router in `api/video.py` is unwired.
- `backend/api/video.py` — imports `route_claim_to_agent` from `core.router`, but that function doesn't exist (the router exports `classify_claim` and `needs_fallback`). **Import will fail at runtime.**
- `backend/requirements.txt` — only lists `google-genai` and `python-dotenv`. Missing real deps: `fastapi`, `openai`, `httpx`, `youtube-transcript-api`, `uvicorn`, `pytest`. `google-genai` is listed but not imported anywhere in the code.
- `backend/eval/` — only a one-line README. No harness, no fixtures, no ground truth.
- No frontend directory yet.
- No `clips/` directory or manifest.

## Known deltas vs. AGENTIC_WORKFLOW.md (target)

These are gaps to pick from when looking for work. Conflicts surface here as we find them, with one-line "what to do" notes:

1. **Topic taxonomy.** Disk: `immigration` / `healthcare` / `crime` / `economy` / `education` (5). Target: `legislative` / `economy` / `historical_statements` / `policy_outcome` (4). Only `economy` overlaps. **What to do:** team conversation to pick a taxonomy, then update the loser. Routing/classifier work blocked until decided.
2. **Source allowlist.** Disk: `sources.md` lists 18 broad government sources (BLS, CDC, FBI, BEA, FRED, etc.) used as soft prompt suggestions, no enforcement. Target: ProPublica + PolitiFact only with `ALLOWED_SOURCES` frozenset and `PermissionError` enforcement at agent boundary. **What to do:** decide whether the project still pitches "ConductorOne thesis as code" — if yes, agent code needs an enforcing base class.
3. **No-route handling.** Disk: router returns `"other"` string on parse failure or unknown domain (single-label). Target: multi-label with `routed_topics = []` flowing to `insufficient_coverage` at Level 4b. **What to do:** rebuild router to multi-label with empty-list path.
4. **Transcription vs. captions.** Disk: live YouTube transcript fetch. Target: pre-shipped VTT/SRT for a curated 5-clip library. **What to do:** add `clips/manifest.json` + caption files; deprecate `core/transcript.py` once a caption parser exists.
5. **LLM client centralization.** Disk: three independent OpenRouter clients (`extract.py` raw httpx → Haiku; `router.py` raw httpx → Haiku; `base_agent.py` AsyncOpenAI → Gemini-2.5-flash). Target: one shared client + one model registry. **What to do:** consolidate when next touching any of these files.
6. **Levels not yet present:** Level 1 caption parsing, Level 4a aggregation, Level 4b rule-based confidence classifier, Level 5 render API, Level 6 eval harness.
7. **Contracts module.** No `/contracts/` directory. `Claim`, `VerificationResult`, `Annotation` types are not formally defined anywhere — informal dicts are passed around instead.
8. **API surface.** `/process-video` returns a fake `job_id`; the WebSocket handler is a comment-only stub.

When picking up a task, find the corresponding section in `AGENTIC_WORKFLOW.md` for the contract/intent, then update this file when your work lands.
