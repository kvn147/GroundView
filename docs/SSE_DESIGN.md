# SSE API Design

## Why SSE

The current `POST /api/analyze-video` and `POST /api/analyze-clip` endpoints block until the whole pipeline finishes. That is awkward for this project because the backend naturally produces useful intermediate results:

- transcript chunks arrive before all extraction is done
- claims are extracted one at a time
- routing decisions are local and fast
- domain agents finish independently
- the UI can render each final claim before video-level aggregation is ready

Server-Sent Events fit this better than REST batch responses for the MVP. The Chrome extension only needs server-to-client progress, not bidirectional messaging, and `EventSource` handles reconnects, streaming text, and simple browser integration without a WebSocket protocol layer.

## Endpoint Shape

Keep the current synchronous endpoints during migration, but add streaming equivalents:

```txt
GET /api/analyze-video/stream?url=<encoded-youtube-url>
GET /api/analyze-clip/stream?url=<encoded-youtube-url>&startTime=120.5&endTime=180&captions=<encoded-captions>
```

`EventSource` only supports `GET`, so request inputs should be query parameters. If captions become too large for query strings, switch clip analysis to a two-step job:

```txt
POST /api/analysis-jobs
GET  /api/analysis-jobs/{job_id}/stream
```

For the current extension, direct `GET` streaming is simpler and enough.

## Wire Format

Every event uses named SSE events and JSON payloads:

```txt
event: claim_final
id: run-abc:claim-3
data: {"runId":"run-abc","claim":{...}}

```

Use comment heartbeats every 10-15 seconds while waiting on LLM or retrieval calls:

```txt
: ping

```

Event payloads should include:

- `runId`: unique ID for the analysis run
- `type`: same value as the SSE event name, useful after JSON parsing
- `seq`: monotonically increasing event number
- `timestamp`: ISO timestamp

## Event Contract

### `run_started`

Sent immediately after request validation.

```json
{
  "type": "run_started",
  "runId": "run-abc",
  "seq": 1,
  "mode": "video",
  "url": "https://www.youtube.com/watch?v=..."
}
```

### `transcript_ready`

Sent after transcript fetch, before claim extraction begins.

```json
{
  "type": "transcript_ready",
  "runId": "run-abc",
  "seq": 2,
  "chunkCount": 42,
  "processedChunkLimit": 42
}
```

### `claim_extracted`

Sent as soon as a claim is extracted from a chunk.

```json
{
  "type": "claim_extracted",
  "runId": "run-abc",
  "seq": 3,
  "claimIndex": 0,
  "claim": {
    "claim_text": "Inflation was at 9% last year.",
    "raw_quote": "Inflation was at 9% last year.",
    "start_time": 12.3,
    "end_time": 12.3,
    "topics": []
  }
}
```

### `claim_routed`

Sent after local L2b routing.

```json
{
  "type": "claim_routed",
  "runId": "run-abc",
  "seq": 4,
  "claimIndex": 0,
  "routedTopics": ["economy"],
  "routingMethod": "keyword",
  "routingConfidence": 0.92
}
```

### `agent_result`

Sent once per domain agent result. This lets the UI show activity and partial evidence before final judging.

```json
{
  "type": "agent_result",
  "runId": "run-abc",
  "seq": 5,
  "claimIndex": 0,
  "agent": "economy",
  "result": {
    "agent": "economy",
    "claim_text": "Inflation was at 9% last year.",
    "allowed_sources": ["BLS", "FRED"],
    "queried_sources": ["BLS"],
    "evidence_items": []
  }
}
```

### `claim_final`

Sent when a claim has completed routing, retrieval, judge scoring, and frontend adaptation. This payload should match the current `FrontendClaim` shape so the extension can append it directly.

```json
{
  "type": "claim_final",
  "runId": "run-abc",
  "seq": 6,
  "claimIndex": 0,
  "claim": {
    "id": "claim-1",
    "text": "Inflation was at 9% last year.",
    "verdict": "Mixed",
    "explanation": "### Evidence\n...",
    "sources": [],
    "activity": []
  }
}
```

### `summary_updated`

Sent after each `claim_final`, using the same top-level fields as `AnalyzeVideoResponse` but with the claims accumulated so far.

```json
{
  "type": "summary_updated",
  "runId": "run-abc",
  "seq": 7,
  "summary": "Analyzed 1 claims...",
  "trustworthinessScore": 3,
  "maxScore": 5,
  "trustworthinessLabel": "Mixed Accuracy / Needs Context",
  "politicalLean": { "label": "Center / Neutral", "value": 0.5 },
  "aggregatedSources": []
}
```

### `done`

Final event. For video analysis, include the complete `AnalyzeVideoResponse`. For clip analysis, include the complete `AnalyzeClipResponse`.

```json
{
  "type": "done",
  "runId": "run-abc",
  "seq": 8,
  "result": {
    "summary": "Analyzed 3 claims...",
    "trustworthinessScore": 4,
    "maxScore": 5,
    "trustworthinessLabel": "Mostly True",
    "politicalLean": { "label": "Center / Neutral", "value": 0.5 },
    "claims": [],
    "aggregatedSources": []
  }
}
```

### `error`

Errors should be streamed when possible instead of surfacing as an abruptly closed connection.

```json
{
  "type": "error",
  "runId": "run-abc",
  "seq": 9,
  "stage": "agent_result",
  "message": "Economy agent timed out.",
  "recoverable": true
}
```

Recoverable errors should allow the stream to continue. Fatal errors should be followed by `done` with whatever partial result can be safely returned.

## Backend Design

Create a small streaming helper in `backend/api/video.py` or a new `backend/api/streaming.py`:

```python
async def sse_event(event: str, payload: dict, event_id: str | None = None) -> str:
    lines = [f"event: {event}"]
    if event_id:
        lines.append(f"id: {event_id}")
    lines.append(f"data: {json.dumps(payload, default=str)}")
    return "\n".join(lines) + "\n\n"
```

Use `StreamingResponse`:

```python
return StreamingResponse(
    analyze_video_events(req.url),
    media_type="text/event-stream",
    headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    },
)
```

The generator should own the same pipeline currently inside `analyze_video`:

1. emit `run_started`
2. fetch transcript and emit `transcript_ready`
3. for each capped chunk, extract claims
4. for each claim, emit `claim_extracted`
5. route claim and emit `claim_routed`
6. run agents and emit `agent_result`
7. run judge, build `Annotation`, emit `claim_final`
8. aggregate accumulated annotations and emit `summary_updated`
9. emit `done`

Check for client disconnects between expensive steps:

```python
if await request.is_disconnected():
    break
```

This prevents a closed YouTube tab from continuing to spend LLM/retrieval budget.

## Frontend Design

Add streaming client functions beside the existing `fetch` functions:

```js
function API_streamFullAnalysis(videoUrl, handlers) {
  const params = new URLSearchParams({ url: videoUrl });
  const source = new EventSource(`${API_BASE_URL}/analyze-video/stream?${params}`);

  source.addEventListener("claim_final", (event) => {
    handlers.onClaimFinal(JSON.parse(event.data));
  });

  source.addEventListener("summary_updated", (event) => {
    handlers.onSummaryUpdated(JSON.parse(event.data));
  });

  source.addEventListener("done", (event) => {
    handlers.onDone(JSON.parse(event.data));
    source.close();
  });

  source.addEventListener("error", (event) => {
    handlers.onError(event.data ? JSON.parse(event.data) : null);
  });

  return () => source.close();
}
```

The content script should keep one active stream cleanup function and call it during YouTube SPA cleanup. That is important because YouTube navigation does not reload the page.

The full-video card should be able to render with:

- zero claims and a loading summary
- claims appended incrementally
- top-level score and sources updated after `summary_updated`
- a final replacement from `done`

Clip analysis can keep the existing loading card but update it as soon as `claim_final` arrives.

## Migration Plan

1. Add streaming endpoints without deleting existing `POST` endpoints.
2. Refactor the shared pipeline into an async generator that yields internal events.
3. Adapt generator events to SSE in the streaming endpoint.
4. Adapt generator completion back into the existing synchronous response for `POST /analyze-video`, so both paths share behavior.
5. Add extension streaming functions while keeping `fetch` fallbacks.
6. Switch the content script to streaming for full-video analysis first.
7. Switch clip analysis after the full-video path is stable.
8. Update `docs/API_CONTRACT.md` once the extension uses SSE by default.

## Tradeoffs

SSE is the right default here because the extension needs progress and partial results, not client-to-server messages. The main limitation is that `EventSource` is `GET`-only, so large clip caption payloads may eventually need the two-step job flow. If the product later needs user-driven cancellation, pausing, or sending live captions continuously from the browser, WebSockets would become more attractive.
