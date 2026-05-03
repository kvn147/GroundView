# Frontend-Backend API Contract

**Status:** Current (SSE-first, synchronous compatibility retained)
*Note: The Chrome extension now prefers Server-Sent Events for analysis progress. The original synchronous `POST` endpoints remain as compatibility wrappers and return the final accumulated result. See [SSE_DESIGN.md](SSE_DESIGN.md) for the event contract.*

## Base URL
Local Development: `http://localhost:8000/api`

---

## 1. Check Political Relevancy
**Endpoint:** `POST /check-political`
**Purpose:** Evaluates video metadata to determine if the content contains political claims requiring fact-checking.

**Request Body:**
```json
{
  "title": "State of the Union Address",
  "description": "The President's annual address to Congress...",
  "tags": "politics, economy, congress",
  "aiDescription": "Optional AI generated summary"
}
```

**Response (200 OK):**
```json
{
  "isPolitical": true
}
```

---

## 2. Full Video Analysis
**Streaming Endpoint:** `GET /analyze-video/stream?url=...`
**Purpose:** Streams the end-to-end extraction and fact-checking pipeline as named Server-Sent Events. The stream emits progress events such as `run_started`, `transcript_ready`, `claim_extracted`, `claim_routed`, `agent_result`, `claim_final`, `summary_updated`, and final `done`.

**Final `done` payload:**
```json
{
  "type": "done",
  "runId": "run-abc",
  "seq": 8,
  "timestamp": "2026-05-03T12:00:00+00:00",
  "result": {
    "summary": "This video contains several political claims with mixed accuracy...",
    "trustworthinessScore": 3,
    "maxScore": 5,
    "trustworthinessLabel": "Mixed Accuracy",
    "politicalLean": {
      "label": "Unknown",
      "value": 0.5
    },
    "claims": [],
    "aggregatedSources": []
  }
}
```

**Endpoint:** `POST /analyze-video`
**Purpose:** Compatibility wrapper that consumes the same streaming pipeline internally and returns only the final result. *Warning: This request will block until the entire pipeline is completed.*

**Request Body:**
```json
{
  "url": "https://www.youtube.com/watch?v=..."
}
```

**Response (200 OK):**
```json
{
  "summary": "This video contains several political claims with mixed accuracy...",
  "trustworthinessScore": 3,
  "maxScore": 5,
  "trustworthinessLabel": "Mixed Accuracy",
  "politicalLean": {
    "label": "Unknown",
    "value": 0.5
  },
  "claims": [
    {
      "id": "claim-1",
      "text": "Inflation was at 9% last year.",
      "verdict": "Economy",
      "explanation": "### Verification Results\n\nAccording to the Bureau of Labor Statistics...",
      "sources": []
    }
  ],
  "aggregatedSources": []
}
```
*(Note: `trustworthinessScore`, `politicalLean`, and `summary` are currently returning static placeholder values while the aggregation logic (Level 5) is being built. The `claims` array contains real LLM-verified data).*

---

## 3. Manual Clip Analysis
**Streaming Endpoint:** `GET /analyze-clip/stream?url=...&startTime=120.5&endTime=180.0&captions=...`
**Purpose:** Streams analysis for a bounded timestamp window. The final `done.result` matches the clip response shape below.

**Endpoint:** `POST /analyze-clip`
**Purpose:** Compatibility wrapper that analyzes a specific, manually-recorded timestamp window from a video and returns only the final result.

**Request Body:**
```json
{
  "url": "https://www.youtube.com/watch?v=...",
  "startTime": 120.5,
  "endTime": 180.0,
  "captions": "Optional manual caption override"
}
```

**Response (200 OK):**
```json
{
  "startTime": 120.5,
  "endTime": 180.0,
  "claim": "Manual clip analysis.",
  "verdict": "Pending",
  "explanation": "Clip analysis backend logic will process specific timestamps here.",
  "sources": []
}
```
*(Note: This endpoint is currently a placeholder returning dummy data until the backend clip processing logic is finalized).*
