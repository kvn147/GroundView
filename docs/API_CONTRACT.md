# Frontend-Backend API Contract

**Status:** Current (Synchronous MVP)
*Note: This contract reflects the synchronous `POST` endpoints designed specifically to cater to the current `chrome-extension` mock expectations. The real-time WebSocket streaming architecture has been postponed.*

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
**Endpoint:** `POST /analyze-video`
**Purpose:** Triggers the end-to-end extraction and fact-checking pipeline for a full YouTube video. *Warning: As a synchronous endpoint, this request will block until the entire pipeline (transcript fetch -> LLM extraction -> domain routing -> evidence retrieval) is completed.*

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
**Endpoint:** `POST /analyze-clip`
**Purpose:** Analyzes a specific, manually-recorded timestamp window from a video. 

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
