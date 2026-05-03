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
    if (!response.ok) {
      const body = await response.text().catch(() => "");
      console.error("[API] check-political HTTP error:", response.status, body);
      throw new Error(`HTTP ${response.status}`);
    }
    const result = await response.json();
    console.log("[API] checkIfPolitical result:", result);
    return result;
  } catch (e) {
    console.error("[API] check-political failed:", e.message || e, "— falling back to isPolitical: true");
    // Fallback to true so we don't break the pipeline on error during dev
    return { isPolitical: true };
  }
}

/**
 * Uploads browser-extracted transcript segments to the local backend.
 * Endpoint: POST /api/transcripts { url, transcript }
 */
async function API_uploadTranscript(videoUrl, transcript) {
  console.log("[API] uploadTranscript called:", {
    videoUrl,
    segmentCount: Array.isArray(transcript) ? transcript.length : 0
  });
  try {
    const response = await fetch(`${API_BASE_URL}/transcripts`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: videoUrl, transcript })
    });
    if (!response.ok) {
      const body = await response.text().catch(() => "");
      console.error("[API] uploadTranscript HTTP error:", response.status, body);
      throw new Error(`HTTP ${response.status}: ${body}`);
    }
    const result = await response.json();
    console.log("[API] uploadTranscript success:", result);
    return result;
  } catch (e) {
    console.error("[API] uploadTranscript failed:", e.message || e);
    throw e;
  }
}

/**
 * Gets the full fact-check analysis for a political video.
 * Endpoint: POST /api/analyze-video { url, transcript? }
 */
async function API_getFullAnalysis(videoUrl, transcript = null, transcriptId = null) {
  console.log("[API] getFullAnalysis called with:", videoUrl);
  try {
    const response = await fetch(`${API_BASE_URL}/analyze-video`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: videoUrl, transcript, transcriptId })
    });
    if (!response.ok) {
      const body = await response.text().catch(() => "");
      console.error("[API] analyze-video HTTP error:", response.status, body);
      throw new Error(`HTTP ${response.status}`);
    }
    const result = await response.json();
    console.log("[API] getFullAnalysis result — claims:", result.claims?.length || 0);
    return result;
  } catch (e) {
    console.error("[API] analyze-video failed:", e.message || e, "— returning error fallback");
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
 * Analyzes a manually-recorded clip.
 * Endpoint: POST /api/analyze-clip { url, startTime, endTime, captions, transcriptId? }
 */
async function API_analyzeClip(videoUrl, startTime, endTime, transcriptId = null) {
  console.log("[API] analyzeClip called:", { videoUrl, startTime, endTime });
  try {
    const response = await fetch(`${API_BASE_URL}/analyze-clip`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url: videoUrl,
        startTime: startTime,
        endTime: endTime,
        captions: "",
        transcriptId
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

