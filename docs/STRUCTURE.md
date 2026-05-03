# STRUCTURE.md — Current Repo State

**Status:** Snapshot of what's actually on disk on `main` (or, when work is in flight, on the active feature branch).
**Companion doc:** [`AGENTIC_WORKFLOW.md`](./AGENTIC_WORKFLOW.md) describes the target architecture. The gap between the two is the work backlog — pick tasks from those gaps.
**Update rule:** Refresh this file whenever files are added, moved, or deleted on `main`.

---

## Repo tree

```
beaverhacks-project/
├── .gitignore                       # team-level ignore (Python, Node, secrets, OS, .claude/, model.pkl, large training CSVs)
├── README.md                        # public project pitch and high-level summary
├── infrastructure.png               # architecture diagram referenced by README
│
├── chrome-extension/                # MV3 Chrome extension — front end (replaces React sidebar)
│   ├── manifest.json                # MV3 manifest, content script on youtube.com/*, single permission: activeTab
│   ├── background.js                # service worker; listens for tab URL changes and pings the content script
│   ├── content.js                   # main injection logic — fact-check card, record button, clip sidebar
│   ├── content.css                  # all extension styling
│   ├── api.js                       # real fetch() calls to the local backend (replaces mock.js paths)
│   ├── mock.js                      # mock backend responses; kept as fallback when the API errors
│   └── icons/icon48.png
│
├── backend/                         # Python backend — agent pipeline lives here
│   ├── main.py                      # FastAPI entry point: app, CORS, /api router, uvicorn entrypoint on port 8000
│   ├── requirements.txt             # fastapi, uvicorn, openai, pydantic, scikit-learn, joblib, httpx, ...
│   ├── contracts.py                 # canonical Pydantic models for cross-level shapes (Claim, Source, EvidenceItem,
│   │                                # VerificationResult, AgentActivityLog, Annotation, frontend response shapes)
│   │                                # plus pure adapters (to_judge_evidence_items, to_frontend_sources/activity, ...)
│   ├── api/
│   │   └── video.py                 # FastAPI routes — /check-political, /analyze-video, /analyze-clip
│   │                                # composes L1→L5 and returns AnalyzeVideoResponse
│   ├── agents/
│   │   ├── README.md                # describes the 5-domain taxonomy
│   │   ├── base.py                  # AllowlistedAgent base class — hard permission enforcement, cache, Tier A/B,
│   │   │                            # activity logging, robust failure handling. The ConductorOne layer.
│   │   ├── base_agent.py            # legacy Tier-A/B function (Kevin's original); kept for back-compat callers
│   │   ├── llm.py                   # OpenRouterLlmClient — async OpenAI-compatible client, lazy module-level singleton
│   │   ├── orchestrator.py          # AgentOrchestrator — concurrent fan-out via asyncio.gather, bounded concurrency,
│   │   │                            # topic→agent registry, defense-in-depth exception handling
│   │   ├── aggregator.py            # L4a/L5-prep — pure-Python aggregation; no LLM (asserted by tests)
│   │   ├── judge.py                 # L4b confidence rules: source trust/bias from registry,
│   │   │                            # weighted-evidence math, calculate_confidence_structured()
│   │   │                            # consumes EvidenceItems directly and skips NLI when nli_source=="agent"
│   │   ├── agent_crime.py           # CrimeAgent(AllowlistedAgent) + back-compat retrieve_evidence/verify shims
│   │   ├── agent_economy.py         # EconomyAgent(AllowlistedAgent) — also exports UNIVERSAL_FACT_CHECKERS frozenset
│   │   ├── agent_education.py       # EducationAgent(AllowlistedAgent)
│   │   ├── agent_healthcare.py      # HealthcareAgent(AllowlistedAgent)
│   │   ├── agent_immigration.py     # ImmigrationAgent(AllowlistedAgent)
│   │   ├── sources.md               # source list with universal fact-checkers tier + per-domain sources
│   │   └── sources.py               # parses sources.md (still used by the legacy base_agent.py)
│   ├── app/
│   │   └── level2b_routing/         # local multi-label topic classifier (no LLM)
│   │       ├── topics.py            # canonical topic IDs (single source of truth)
│   │       ├── types.py             # RoutingDecision dataclass
│   │       ├── keyword_tables.py    # per-topic keyword + regex tables
│   │       ├── keyword_matcher.py   # deterministic keyword scoring
│   │       ├── decision.py          # decision tree: keyword strong / classifier / no_route
│   │       ├── router.py            # public route() — lazy-loads model.pkl, masks speakers, falls back gracefully
│   │       ├── data_prep.py         # speaker masking, batch loading, dedup
│   │       ├── classifier/
│   │       │   ├── train.py         # CLI to train the OvR-calibrated logistic regression
│   │       │   ├── predict.py       # load_model + predict_probs
│   │       │   ├── eval.py          # CLI for offline evaluation (per-topic metrics, threshold sweep, baseline)
│   │       │   ├── inspect.py       # dump top-N tokens per class
│   │       │   └── model.pkl        # gitignored — train locally
│   │       └── data/
│   │           ├── README.md
│   │           ├── synthetic_train_*.csv  # 10 batches, ~920 rows; combined_train.csv gitignored
│   │           └── liar_*.csv             # LIAR dataset for held-out eval
│   ├── core/
│   │   ├── __init__.py
│   │   ├── extract.py               # claim extraction via Haiku 4.5 (raw httpx → OpenRouter)
│   │   ├── router.py                # legacy single-label LLM router — superseded by app/level2b_routing
│   │   └── transcript.py            # YouTube transcript fetch + 60s chunking with 10s overlap
│   ├── data/
│   │   ├── media_bias.csv           # AllSides bias ratings — loaded by judge.py at module import
│   │   └── media_bias_raw.txt       # source data for parsing.py
│   ├── parsing.py                   # one-shot script that built media_bias.csv
│   ├── eval/
│   │   └── README.md                # placeholder — eval harness not yet built
│   └── tests/
│       ├── conftest.py                       # sets dummy OPENROUTER_API_KEY so judge.py imports succeed
│       ├── test_contracts.py                 # round-trip serialization, adapter shapes, security invariants
│       ├── test_allowlisted_agent.py         # permission enforcement, cache, Tier A/B, failure handling
│       ├── test_agent_migration.py           # 5 migrated agents — class attrs + back-compat shims
│       ├── test_orchestrator.py              # fan-out, concurrency, defense-in-depth
│       ├── test_aggregator.py                # trust/bias mapping, source dedup, activity propagation, no-LLM invariant
│       ├── test_judge_structured.py          # NLI-skip-on-agent invariant
│       ├── test_crime.py / test_economy.py / ...  # legacy per-agent integration tests (require API key)
│       ├── test_edge_cases.py                # legacy
│       └── test_fact_check.py                # legacy universal-fact-checker test
│
└── docs/
    ├── STRUCTURE.md                 # this file
    ├── AGENTIC_WORKFLOW.md          # target architecture
    ├── API_CONTRACT.md              # the synchronous endpoint contract the chrome extension consumes
    └── CHANGELOG.md                 # 4-line entries per commit/PR
```

---

## What works today

### Chrome extension (front end, real backend)
- Wired to the real backend via `chrome-extension/api.js`. `mock.js` remains as a fallback when the API errors.
- Three UI surfaces in `content.js`: full-video fact-check card, record-clip button, clip sidebar.
- SPA navigation handled via a `MutationObserver` on URL changes.

### Backend (live, end-to-end)
- **`main.py`** — FastAPI app with CORS, includes `/api` router, uvicorn entrypoint on `:8000`.
- **`POST /api/check-political`** — currently mocked-true so the rest of the pipeline runs.
- **`POST /api/analyze-video`** — full L1→L5 pipeline:
  - L1 transcript via `core/transcript.py` (YouTube captions, 60s chunks, 10s overlap)
  - L2a claim extraction via `core/extract.py` (Haiku 4.5)
  - L2b topic routing via `app/level2b_routing/router.route()` — local, multi-label, no LLM
  - L3 fan-out via `agents/orchestrator.AgentOrchestrator` — concurrent, bounded, hard allowlist
  - L4b confidence via `agents/judge.calculate_confidence_structured` — skips NLI when agent pre-filled
  - L4a/L5-prep via `agents/aggregator.aggregate_annotations` — pure Python rules, no LLM
- **`POST /api/analyze-clip`** — same pipeline scoped to a single chunk; accepts caption-text override.

### L3 enforcement (the ConductorOne thesis as code)
- Every agent extends `AllowlistedAgent`. `ALLOWED_SOURCES` is a frozenset declared at the class level.
- Tier A: universal-fact-checker probe (Haiku) — short-circuits when a verdict exists, pre-fills `nli_source="agent"` so the judge skips its NLI call.
- Tier B: domain retrieval (Gemini 2.5 Flash) with structured-JSON output. Citations not in `ALLOWED_SOURCES` are dropped from evidence and recorded in `denied_sources`.
- Source-name normalization handles cosmetic variants (`"factcheck.org"` ≡ `"FactCheck.org"`).
- Per-call disk-key cache (in-memory by default; swap-in seam for `diskcache` later). `cache_hit=True` propagates to activity logs.
- All failure modes (parse failures, network errors) surface in `AgentActivityLog.error` rather than crashing.

### L4b auditability invariant
- AGENTIC_WORKFLOW.md mandates "no LLM" at L4b. The deterministic verdict math lives in `aggregator.py` and the rules-based aggregation. NLI scoring still uses Gemini (Kevin's original design); the call is skipped on Tier-A hits.
- `test_aggregator_does_not_import_an_llm_client` enforces the no-LLM invariant on the aggregator at test time.

### Tests
- 134/134 currently pass on the L3 branch (61 contract / agent / orchestrator + 24 aggregator + 7 judge_structured + 42 routing).
- Excluded: legacy `test_crime/economy/.../fact_check` integration tests that require a live OpenRouter API key.

---

## Known deltas vs. AGENTIC_WORKFLOW.md (target)

Open work items remaining:

1. **Topic taxonomy.** Disk: 5 topics (`immigration`, `healthcare`, `crime`, `economy`, `education`). Spec: 4 topics (`legislative`, `economy`, `historical_statements`, `policy_outcome`). Disk taxonomy is what shipped; the spec hasn't been updated. **What to do:** team conversation; either commit the spec to the disk taxonomy or pivot the agents.
2. **L4b rules-only invariant is partial.** Aggregator and verdict math are LLM-free. NLI scoring still uses Gemini for non-Tier-A items. **What to do:** decide whether to keep LLM-NLI (and update spec), or replace with a smaller deterministic NLI step.
3. **Real test data for the routing classifier.** `data/real_test.csv` doesn't exist yet. The 0.95 macro-F1 numbers are training-distribution. Hand-label 50–100 real claims for honest accuracy.
4. **Eval harness.** No L6 batch runner against ground-truth clips. AGENTIC_WORKFLOW.md § Level 7 specifies extraction / routing / citation-relevance metrics; nothing is built yet.
5. **Legacy `core/router.py` and `agents/base_agent.py`** are no longer used by `api/video.py` after the L3 refactor, but remain on disk. **What to do:** delete after one demo session confirms nothing else depends on them.
6. **Activity panel UI.** Backend now serves `FrontendActivity` rows on each claim, but the chrome extension doesn't render them yet. **What to do:** austaciouscoder picks up the rendering work when ready.
7. **Caching invariant — disk-backed.** `AllowlistedAgent` uses `InMemoryCache` by default (lost on restart). AGENTIC_WORKFLOW.md mandates persistent caching. **What to do:** swap in `diskcache.Cache` via the existing `Cache` protocol; ~10 lines.
8. **README.md is stale.** Still pre-pivot. Front door doesn't match current architecture.

When picking up a task, find the corresponding section in `AGENTIC_WORKFLOW.md` for the contract/intent, then update this file when your work lands.
