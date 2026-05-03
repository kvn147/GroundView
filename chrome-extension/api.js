// =============================================================================
// API CLIENT — Actual API calls to the local FastAPI backend
// =============================================================================

const API_BASE_URL = "http://localhost:8000/api";

/**
 * Checks if a video is political based on its metadata.
 * Endpoint: POST /api/check-political { title, description, tags, aiDescription }
 */
async function API_checkIfPolitical(metadata) {
  console.log("[API] checkIfPolitical called with:", metadata);
  try {
    const response = await fetch(`${API_BASE_URL}/check-political`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(metadata)
    });
    if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
    return await response.json();
  } catch (e) {
    console.error("[API] check-political failed:", e);
    // Fallback to true so we don't break the pipeline on error during dev
    return { isPolitical: true };
  }
}

/**
 * Gets the full fact-check analysis for a political video.
 * Endpoint: POST /api/analyze-video { url }
 */
async function API_getFullAnalysis(videoUrl) {
  console.log("[API] getFullAnalysis called with:", videoUrl);
  try {
    const response = await fetch(`${API_BASE_URL}/analyze-video`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: videoUrl })
    });
    if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
    return await response.json();
  } catch (e) {
    console.error("[API] analyze-video failed:", e);
    // Return empty fallback on error
    return {
      summary: "Error connecting to backend.",
      trustworthinessScore: 1,
      maxScore: 5,
      trustworthinessLabel: "Error",
      politicalLean: { label: "Unknown", value: 0.5 },
      claims: [],
      aggregatedSources: []
    };
  }
}

/**
 * Streams full fact-check analysis events for a political video.
 * Endpoint: GET /api/analyze-video/stream?url=...
 */
function API_streamFullAnalysis(videoUrl, handlers = {}) {
  const params = new URLSearchParams({ url: videoUrl });
  const source = new EventSource(`${API_BASE_URL}/analyze-video/stream?${params.toString()}`);

  const parse = (event) => JSON.parse(event.data);
  const on = (name, handlerName) => {
    source.addEventListener(name, (event) => {
      if (handlers[handlerName]) handlers[handlerName](parse(event));
    });
  };

  on("run_started", "onRunStarted");
  on("transcript_ready", "onTranscriptReady");
  on("claim_extracted", "onClaimExtracted");
  on("claim_routed", "onClaimRouted");
  on("agent_result", "onAgentResult");
  on("claim_final", "onClaimFinal");
  on("summary_updated", "onSummaryUpdated");

  source.addEventListener("done", (event) => {
    if (handlers.onDone) handlers.onDone(parse(event));
    source.close();
  });

  source.addEventListener("error", (event) => {
    if (event.data && handlers.onStreamError) {
      handlers.onStreamError(parse(event));
      return;
    }
    if (handlers.onConnectionError) handlers.onConnectionError(event);
  });

  return () => source.close();
}

/**
 * Analyzes a manually-recorded clip.
 * Endpoint: POST /api/analyze-clip { url, startTime, endTime, captions }
 */
async function API_analyzeClip(videoUrl, startTime, endTime) {
  console.log("[API] analyzeClip called:", { videoUrl, startTime, endTime });
  try {
    const response = await fetch(`${API_BASE_URL}/analyze-clip`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url: videoUrl,
        startTime: startTime,
        endTime: endTime,
        captions: "" // Frontend doesn't pull captions yet
      })
    });
    if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
    return await response.json();
  } catch (e) {
    console.error("[API] analyze-clip failed:", e);
    return {
      startTime,
      endTime,
      claim: "Error connecting to backend.",
      verdict: "Error",
      explanation: "Could not reach the local FastAPI server.",
      sources: []
    };
  }
}

/**
 * Streams fact-check analysis for a manually-recorded clip.
 * Endpoint: GET /api/analyze-clip/stream?url=...&startTime=...&endTime=...
 */
function API_streamClipAnalysis(videoUrl, startTime, endTime, handlers = {}) {
  const params = new URLSearchParams({
    url: videoUrl,
    startTime: String(startTime),
    endTime: String(endTime),
    captions: ""
  });
  const source = new EventSource(`${API_BASE_URL}/analyze-clip/stream?${params.toString()}`);

  const parse = (event) => JSON.parse(event.data);
  const on = (name, handlerName) => {
    source.addEventListener(name, (event) => {
      if (handlers[handlerName]) handlers[handlerName](parse(event));
    });
  };

  on("claim_extracted", "onClaimExtracted");
  on("claim_routed", "onClaimRouted");
  on("agent_result", "onAgentResult");
  on("claim_final", "onClaimFinal");

  source.addEventListener("done", (event) => {
    if (handlers.onDone) handlers.onDone(parse(event));
    source.close();
  });

  source.addEventListener("error", (event) => {
    if (event.data && handlers.onStreamError) {
      handlers.onStreamError(parse(event));
      return;
    }
    if (handlers.onConnectionError) handlers.onConnectionError(event);
  });

  return () => source.close();
}
