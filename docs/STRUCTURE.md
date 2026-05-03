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
├── chrome-extension/                # MV3 Chrome extension — front end (replaces React sidebar)
│   ├── manifest.json                # MV3 manifest, content script on youtube.com/*, single permission: activeTab
│   ├── background.js                # service worker; listens for tab URL changes and pings the content script
│   ├── content.js                   # main injection logic — fact-check card, record button, clip sidebar
│   ├── content.css                  # all extension styling
│   ├── mock.js                      # mock backend responses (loaded BEFORE content.js); replace with real fetch calls
│   └── icons/
│       └── icon48.png
│
├── backend/                         # Python backend — agent pipeline lives here
│   ├── main.py                      # (empty stub) intended FastAPI entry point
│   ├── requirements.txt             # only google-genai + python-dotenv — UNDERSTATED, see "broken" below
│   ├── api/
│   │   └── video.py                 # FastAPI routes: POST /process-video, WS /ws/claims/{job_id} (legacy, broken)
│   ├── agents/
│   │   ├── README.md                # describes 5 domains: Healthcare, Immigration, Crime, Economy, Education
│   │   ├── base_agent.py            # universal-fact-checker tier + domain retrieval; google/gemini-2.5-flash via OpenRouter
│   │   ├── agent_crime.py           # crime domain agent
│   │   ├── agent_economy.py         # economy domain agent
│   │   ├── agent_education.py       # education domain agent
│   │   ├── agent_healthcare.py      # healthcare domain agent
│   │   ├── agent_immigration.py     # immigration domain agent
│   │   ├── sources.md               # source list with universal fact-checkers tier + per-domain sources
│   │   └── sources.py               # parses sources.md and returns formatted source strings per section
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
│       ├── test_edge_cases.py
│       └── test_fact_check.py       # exercises the universal-fact-checker tier in base_agent
│
└── docs/
    ├── STRUCTURE.md                 # this file
    ├── AGENTIC_WORKFLOW.md          # target architecture (post-pivot to Chrome extension)
    └── CHANGELOG.md                 # 4-line entries per commit/PR (changes, status, future issues)
```

---

## What works today

### Chrome extension (front end, mocked end-to-end)
- **`manifest.json`** declares an MV3 extension matching `*://www.youtube.com/*`, with `activeTab` permission and a single content script + service worker.
- **`content.js`** activates on YouTube watch pages, handles SPA navigations via a `MutationObserver` on URL changes, and injects three UI surfaces:
  - Fact-check card under `#middle-row` (summary, trustworthiness score, political-lean meter, expandable claims, aggregated sources).
  - Record button in `.ytp-right-controls` for marking a clip in/out (start time captured at click, fact-checks the span on stop).
  - Clip sidebar in `#secondary-inner` listing recorded clip results with click-to-seek timestamps.
- **`background.js`** is a thin service worker that pings the content script on YouTube tab URL changes — defensive against missed SPA navigations.
- **`mock.js`** provides three mock async functions (`MOCK_checkIfPolitical`, `MOCK_getFullAnalysis`, `MOCK_analyzeClip`) returning realistic shapes with simulated latency. Loaded *before* `content.js` so the mock functions are globally available.

### Backend (currently disconnected from the extension)
- **Universal-fact-checker tier** (`agents/base_agent.py`): Tier A check sends the claim plus the "Universal Fact Checkers (Priority)" source list to Gemini-2.5-flash and asks if it's been *explicitly* fact-checked. If yes, returns the fact-checker's verdict. If no, returns `NO_FACT_CHECK_FOUND` and Tier B runs.
- **Domain retrieval** (`agents/base_agent.py` Tier B): falls through to a domain-specific evidence-gathering call against the topic agent's source list, returning Markdown.
- **Domain agents** (`agents/agent_*.py`): thin wrappers passing domain name + source examples + claim into `run_domain_agent`. Both `retrieve_evidence` and `verify` aliases exposed.
- **Source registry** (`agents/sources.md` + `sources.py`): six universal fact-checkers (PolitiFact, FactCheck.org, Snopes, AP, Reuters, WaPo) plus per-domain government sources. Parser is `## Section` aware.
- **Transcript ingestion** (`core/transcript.py`): pulls captions via `youtube-transcript-api`, normalizes timestamps, chunks into ~60s windows with 10s overlap. Not currently wired to the extension; will be replaced by extension-supplied caption text.
- **Claim extraction** (`core/extract.py`): sends a chunk + system prompt to Haiku 4.5 via OpenRouter, parses JSON-array response. Strict verifiability filter.
- **Topic classification** (`core/router.py`): single-label classifier into 5 domains via Haiku. Returns `(domain, confidence)` plus `needs_fallback` at 0.6. Falls back to `"other"` on parse failure or unknown domain.
- **Test scaffolding** (`tests/`): one test file per agent, plus `test_edge_cases.py` and `test_fact_check.py` exercising the universal-fact-checker tier.

## What's stubbed or broken

- **No backend endpoints yet.** The extension expects `POST /api/check-political`, `POST /api/analyze-video`, and `POST /api/analyze-clip`. None exist. `mock.js` is the only thing serving them.
- **`backend/main.py`** — empty file. No FastAPI app instance.
- **`backend/api/video.py`** — legacy from before the pivot. Routes are `/process-video` (returns a fake `job_id`) and a comment-only WebSocket handler. **Imports `route_claim_to_agent` from `core.router`, but that function doesn't exist.** Import fails at runtime.
- **`backend/requirements.txt`** — only `google-genai` + `python-dotenv`. Missing real deps: `fastapi`, `openai`, `httpx`, `youtube-transcript-api`, `uvicorn`, `pytest`. `google-genai` is listed but not imported anywhere.
- **`backend/eval/`** — one-line README. No eval harness for the post-pivot pipeline either.
- **Three independent LLM clients.** `extract.py` and `router.py` build raw `httpx.AsyncClient` calls to OpenRouter for Haiku; `base_agent.py` uses `AsyncOpenAI` for Gemini-2.5-flash. No shared client, no model registry.
- **Topic routing single-label.** `router.py` returns one domain string; the extension/spec expects multi-label.
- **No `clips/` directory** — the original 5-clip library concept is dropped post-pivot, but nothing was deleted in its place either.

## Known deltas vs. AGENTIC_WORKFLOW.md (target)

Open work items, with one-line "what to do" notes:

1. **Backend endpoints.** Build `/api/check-political`, `/api/analyze-video`, `/api/analyze-clip` matching the contracts in AGENTIC_WORKFLOW.md. Wire FastAPI in `main.py`.
2. **Replace mock.js with real fetch calls.** Each `MOCK_*` function in `chrome-extension/mock.js` carries a comment listing the intended endpoint. Swap one at a time.
3. **Topic routing → multi-label.** Current `router.py` is single-label LLM. New module at `backend/app/level2b_routing/` is in progress on `feat/routing_base` (keyword-first hybrid with logistic-regression fallback).
4. **LLM client centralization.** Three independent constructions (extract / router / base_agent) need consolidation. New module needs a shared client and a model registry. Do this when next touching any of those three files.
5. **Verdict pipeline assembly.** No code yet assembles per-claim verdicts into the `VideoAnalysis` shape (summary, trustworthiness score, political lean, aggregated sources). This is Level 5 work — needs design.
6. **Eval harness.** Original 5-clip ground-truth approach is dead. Replacement undecided (see AGENTIC_WORKFLOW.md § Level 7).
7. **Legacy `core/transcript.py` and `api/video.py`** are pre-pivot artifacts. Decide whether to delete or repurpose.
8. **`README.md` is stale.** Still describes the pre-pivot pitch (3 agents, judge model, 5 sources). Front door doesn't match current architecture.

When picking up a task, find the corresponding section in `AGENTIC_WORKFLOW.md` for the contract/intent, then update this file when your work lands.
