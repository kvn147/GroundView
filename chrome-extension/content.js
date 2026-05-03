// YouTube Political Fact-Checker — Content Script
// Injects fact-check UI into YouTube watch pages

(function () {
  "use strict";

  let currentVideoId = null;
  let isRecording = false;
  let recordStartTime = 0;
  let recordTimerInterval = null;
  let clipResults = [];
  let activeAnalysisCancel = null;
  let currentTranscriptId = null;
  let currentTranscriptSegments = [];

  // ── Helpers ──

  function getVideoId() {
    const params = new URLSearchParams(window.location.search);
    return params.get("v");
  }

  function formatTime(seconds) {
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${s.toString().padStart(2, "0")}`;
  }

  function getVideoCurrentTime() {
    const video = document.querySelector("video.html5-main-video");
    return video ? video.currentTime : 0;
  }

  function extractBalancedJson(source, marker) {
    const markerIndex = source.indexOf(marker);
    if (markerIndex === -1) return null;

    const start = source.indexOf("{", markerIndex);
    if (start === -1) return null;

    let depth = 0;
    let inString = false;
    let escaped = false;

    for (let i = start; i < source.length; i += 1) {
      const char = source[i];

      if (inString) {
        if (escaped) {
          escaped = false;
        } else if (char === "\\") {
          escaped = true;
        } else if (char === "\"") {
          inString = false;
        }
        continue;
      }

      if (char === "\"") {
        inString = true;
      } else if (char === "{") {
        depth += 1;
      } else if (char === "}") {
        depth -= 1;
        if (depth === 0) return source.slice(start, i + 1);
      }
    }

    return null;
  }

  function getPlayerResponseFromPage() {
    const scripts = Array.from(document.querySelectorAll("script"));
    for (const script of scripts) {
      const text = script.textContent || "";
      if (!text.includes("ytInitialPlayerResponse")) continue;

      const rawJson = extractBalancedJson(text, "ytInitialPlayerResponse");
      if (!rawJson) continue;

      try {
        return JSON.parse(rawJson);
      } catch (error) {
        console.warn("[FactChecker] Failed to parse player response:", error);
      }
    }

    return null;
  }

  function chooseCaptionTrack(captionTracks) {
    if (!Array.isArray(captionTracks) || captionTracks.length === 0) return null;

    const isEnglish = (track) => {
      const code = track.languageCode || "";
      const label = track.name && track.name.simpleText ? track.name.simpleText : "";
      return code.toLowerCase().startsWith("en") || /english/i.test(label);
    };
    const isManual = (track) => track.kind !== "asr";

    return (
      captionTracks.find((track) => isEnglish(track) && isManual(track)) ||
      captionTracks.find(isEnglish) ||
      captionTracks.find(isManual) ||
      captionTracks[0]
    );
  }

  function parseJson3Transcript(payload) {
    const events = Array.isArray(payload.events) ? payload.events : [];
    return events
      .filter((event) => Array.isArray(event.segs))
      .map((event) => ({
        timestamp: (event.tStartMs || 0) / 1000,
        text: event.segs.map((seg) => seg.utf8 || "").join("").trim()
      }))
      .filter((segment) => segment.text);
  }

  function parseXmlTranscript(xmlText) {
    const doc = new DOMParser().parseFromString(xmlText, "text/xml");
    return Array.from(doc.querySelectorAll("text"))
      .map((node) => ({
        timestamp: Number.parseFloat(node.getAttribute("start") || "0"),
        text: (node.textContent || "").trim()
      }))
      .filter((segment) => segment.text);
  }

  async function fetchTranscriptSegments() {
    const playerResponse = getPlayerResponseFromPage();
    const captionTracks =
      playerResponse &&
      playerResponse.captions &&
      playerResponse.captions.playerCaptionsTracklistRenderer &&
      playerResponse.captions.playerCaptionsTracklistRenderer.captionTracks;

    const track = chooseCaptionTrack(captionTracks);
    if (!track || !track.baseUrl) {
      throw new Error("No YouTube caption track found on this page.");
    }

    const url = new URL(track.baseUrl);
    url.searchParams.set("fmt", "json3");

    const response = await fetch(url.toString(), { credentials: "include" });
    if (!response.ok) throw new Error(`Caption fetch failed with ${response.status}`);

    const body = await response.text();
    try {
      const json = JSON.parse(body);
      const segments = parseJson3Transcript(json);
      if (segments.length > 0) return segments;
    } catch (_error) {
      const segments = parseXmlTranscript(body);
      if (segments.length > 0) return segments;
    }

    throw new Error("Caption track did not contain readable transcript text.");
  }

  function getVerdictClass(verdict) {
    const v = verdict.toLowerCase().replace(/\s+/g, "-");
    return `ytfc-verdict-${v}`;
  }

  function getScoreClass(score) {
    return `ytfc-score-${score}`;
  }

  function emptyVideoAnalysis() {
    return {
      summary: "Analyzing video for political claims...",
      trustworthinessScore: 3,
      maxScore: 5,
      trustworthinessLabel: "Analyzing",
      politicalLean: { label: "Unknown", value: 0.5 },
      claims: [],
      aggregatedSources: []
    };
  }

  function cleanup() {
    if (activeAnalysisCancel) {
      activeAnalysisCancel();
      activeAnalysisCancel = null;
    }
    document.querySelectorAll(".ytfc-card, .ytfc-loading-card, .ytfc-clip-sidebar").forEach((el) => el.remove());
    const btn = document.querySelector(".ytfc-record-btn");
    if (btn) btn.remove();
    stopRecording(true);
    clipResults = [];
    currentTranscriptId = null;
    currentTranscriptSegments = [];
  }

  // ── Fact-Check Card Builder ──

  function buildFactCheckCard(data) {
    const card = document.createElement("div");
    card.className = "ytfc-card";

    // Header
    const header = document.createElement("div");
    header.className = "ytfc-card-header";
    header.innerHTML = `
      <div class="ytfc-card-title">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#3ea6ff" stroke-width="2">
          <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
          <path d="M9 12l2 2 4-4"/>
        </svg>
        Fact Check
      </div>
      <span class="ytfc-score-badge ${getScoreClass(data.trustworthinessScore)}">
        ${data.trustworthinessLabel} &mdash; ${data.trustworthinessScore}/${data.maxScore}
      </span>
    `;
    card.appendChild(header);

    // Summary
    const summary = document.createElement("div");
    summary.className = "ytfc-summary";
    summary.textContent = data.summary;
    card.appendChild(summary);

    // Political lean
    const lean = document.createElement("div");
    lean.className = "ytfc-lean";
    lean.innerHTML = `
      <div class="ytfc-lean-label">
        <span>Left</span>
        <span>${data.politicalLean.label}</span>
        <span>Right</span>
      </div>
      <div class="ytfc-lean-bar">
        <div class="ytfc-lean-marker" style="left: ${data.politicalLean.value * 100}%"></div>
      </div>
    `;
    card.appendChild(lean);

    // Claims section
    const claimsHeader = document.createElement("div");
    claimsHeader.className = "ytfc-section-header";
    claimsHeader.textContent = `Claims (${data.claims.length})`;
    card.appendChild(claimsHeader);

    const claimsList = document.createElement("ul");
    claimsList.className = "ytfc-claims-list";

    data.claims.forEach((claim) => {
      const li = document.createElement("li");
      li.className = "ytfc-claim";

      li.innerHTML = `
        <div class="ytfc-claim-top">
          <span class="ytfc-claim-text">${claim.text}</span>
          <span class="ytfc-verdict ${getVerdictClass(claim.verdict)}">${claim.verdict}</span>
        </div>
        <div class="ytfc-claim-detail">
          <div class="ytfc-claim-explanation">${claim.explanation}</div>
          <div class="ytfc-claim-sources">
            ${claim.sources.map((s) => `<a href="${s.url}" target="_blank" rel="noopener">${s.name}</a>`).join("")}
          </div>
        </div>
      `;

      li.addEventListener("click", () => {
        li.classList.toggle("ytfc-expanded");
      });

      claimsList.appendChild(li);
    });
    card.appendChild(claimsList);

    // Aggregated sources
    const sourcesHeader = document.createElement("div");
    sourcesHeader.className = "ytfc-section-header";
    sourcesHeader.textContent = "Sources";
    card.appendChild(sourcesHeader);

    const sourcesGrid = document.createElement("div");
    sourcesGrid.className = "ytfc-sources-grid";
    data.aggregatedSources.forEach((src) => {
      const a = document.createElement("a");
      a.className = "ytfc-source-chip";
      a.href = src.url;
      a.target = "_blank";
      a.rel = "noopener";
      a.textContent = src.name;
      sourcesGrid.appendChild(a);
    });
    card.appendChild(sourcesGrid);

    return card;
  }

  // ── Injection: Fact-Check Card ──

  function injectFactCheckCard(data) {
    document.querySelectorAll(".ytfc-card, .ytfc-loading-card").forEach((el) => el.remove());

    const card = buildFactCheckCard(data);

    // Insert into #middle-row
    const middleRow = document.querySelector("#middle-row");
    if (middleRow) {
      middleRow.appendChild(card);
    }
  }

  function injectLoadingCard() {
    document.querySelectorAll(".ytfc-card, .ytfc-loading-card").forEach((el) => el.remove());

    const loader = document.createElement("div");
    loader.className = "ytfc-card ytfc-loading-card";
    loader.innerHTML = `<div class="ytfc-loading"><div class="ytfc-spinner"></div>Analyzing video for political claims...</div>`;

    const middleRow = document.querySelector("#middle-row");
    if (middleRow) {
      middleRow.appendChild(loader);
    }
  }

  // ── Injection: Record Button ──

  function injectRecordButton() {
    if (document.querySelector(".ytfc-record-btn")) return;

    const btn = document.createElement("button");
    btn.className = "ytfc-record-btn";
    btn.innerHTML = `
      <div class="ytfc-record-dot"></div>
      <span class="ytfc-record-timer">0:00</span>
      <span class="ytfc-record-tooltip">Fact-check a clip</span>
    `;

    btn.addEventListener("click", () => {
      if (isRecording) {
        stopRecording(false);
      } else {
        startRecording();
      }
    });

    const controls = document.querySelector(".ytp-right-controls");
    if (controls) {
      controls.insertBefore(btn, controls.firstChild);
    }
  }

  function startRecording() {
    isRecording = true;
    recordStartTime = getVideoCurrentTime();

    const btn = document.querySelector(".ytfc-record-btn");
    if (btn) {
      btn.classList.add("ytfc-recording");
      const tooltip = btn.querySelector(".ytfc-record-tooltip");
      if (tooltip) tooltip.textContent = "Stop recording";

      const timer = btn.querySelector(".ytfc-record-timer");
      recordTimerInterval = setInterval(() => {
        const elapsed = getVideoCurrentTime() - recordStartTime;
        if (timer) timer.textContent = formatTime(Math.max(0, elapsed));
      }, 200);
    }

    console.log("[FactChecker] Recording started at", formatTime(recordStartTime));
  }

  async function stopRecording(silent) {
    if (!isRecording && !silent) return;

    isRecording = false;
    clearInterval(recordTimerInterval);
    recordTimerInterval = null;

    const btn = document.querySelector(".ytfc-record-btn");
    if (btn) {
      btn.classList.remove("ytfc-recording");
      const tooltip = btn.querySelector(".ytfc-record-tooltip");
      if (tooltip) tooltip.textContent = "Fact-check a clip";
      const timer = btn.querySelector(".ytfc-record-timer");
      if (timer) timer.textContent = "0:00";
    }

    if (silent) return;

    const endTime = getVideoCurrentTime();
    console.log("[FactChecker] Recording stopped at", formatTime(endTime));

    // Show loading state in the clip being analyzed
    ensureClipSidebar();
    addClipLoading();

    const videoUrl = window.location.href;
    if (typeof API_streamClipAnalysis === "function") {
      let settled = false;
      API_streamClipAnalysis(videoUrl, recordStartTime, endTime, currentTranscriptId, {
        onDone: (event) => {
          settled = true;
          removeClipLoading();
          clipResults.unshift(event.result);
          renderClipSidebar();
        },
        onConnectionError: async () => {
          if (settled) return;
          settled = true;
          const result = await API_analyzeClip(videoUrl, recordStartTime, endTime, currentTranscriptId);
          removeClipLoading();
          clipResults.unshift(result);
          renderClipSidebar();
        }
      });
      return;
    }

    const result = await API_analyzeClip(videoUrl, recordStartTime, endTime, currentTranscriptId);

    removeClipLoading();
    clipResults.unshift(result);
    renderClipSidebar();
  }

  // ── Injection: Clip Sidebar ──

  function ensureClipSidebar() {
    if (document.querySelector(".ytfc-clip-sidebar")) return;

    const sidebar = document.createElement("div");
    sidebar.className = "ytfc-clip-sidebar";
    sidebar.innerHTML = `
      <div class="ytfc-clip-sidebar-header">
        <span class="ytfc-clip-sidebar-title">Clip Fact-Checks</span>
        <span class="ytfc-clip-count">0 clips</span>
      </div>
      <div class="ytfc-clip-list">
        <div class="ytfc-clip-empty">Record a clip to fact-check it</div>
      </div>
    `;

    const secondary = document.querySelector("#secondary-inner") || document.querySelector("#secondary");
    if (secondary) {
      secondary.insertBefore(sidebar, secondary.firstChild);
    }
  }

  function addClipLoading() {
    const list = document.querySelector(".ytfc-clip-list");
    if (!list) return;

    const empty = list.querySelector(".ytfc-clip-empty");
    if (empty) empty.remove();

    const loader = document.createElement("div");
    loader.className = "ytfc-clip-card ytfc-clip-loading";
    loader.innerHTML = `<div class="ytfc-loading"><div class="ytfc-spinner"></div>Analyzing clip...</div>`;
    list.insertBefore(loader, list.firstChild);
  }

  function removeClipLoading() {
    const loader = document.querySelector(".ytfc-clip-loading");
    if (loader) loader.remove();
  }

  function renderClipSidebar() {
    const sidebar = document.querySelector(".ytfc-clip-sidebar");
    if (!sidebar) return;

    const countEl = sidebar.querySelector(".ytfc-clip-count");
    if (countEl) countEl.textContent = `${clipResults.length} clip${clipResults.length !== 1 ? "s" : ""}`;

    const list = sidebar.querySelector(".ytfc-clip-list");
    if (!list) return;

    list.innerHTML = "";

    if (clipResults.length === 0) {
      list.innerHTML = `<div class="ytfc-clip-empty">Record a clip to fact-check it</div>`;
      return;
    }

    clipResults.forEach((clip) => {
      const card = document.createElement("div");
      card.className = "ytfc-clip-card";
      card.innerHTML = `
        <div class="ytfc-clip-timestamp">
          <span class="ytfc-clip-ts" data-time="${clip.startTime}">${formatTime(clip.startTime)}</span> – <span class="ytfc-clip-ts" data-time="${clip.endTime}">${formatTime(clip.endTime)}</span>
        </div>
        <div class="ytfc-clip-claim">"${clip.claim}"</div>
        <div class="ytfc-clip-verdict-row">
          <span class="ytfc-verdict ${getVerdictClass(clip.verdict)}">${clip.verdict}</span>
        </div>
        <div class="ytfc-clip-explanation">${clip.explanation}</div>
        <div class="ytfc-clip-sources">
          ${clip.sources.map((s) => `<a href="${s.url}" target="_blank" rel="noopener">${s.name}</a>`).join(" · ")}
        </div>
      `;
      card.querySelectorAll(".ytfc-clip-ts").forEach((ts) => {
        ts.addEventListener("click", () => {
          const video = document.querySelector("video.html5-main-video");
          if (video) video.currentTime = parseFloat(ts.dataset.time);
        });
      });

      list.appendChild(card);
    });
  }

  // ── Main Init ──

  async function initForVideo() {
    const videoId = getVideoId();
    if (!videoId || videoId === currentVideoId) return;
    currentVideoId = videoId;

    cleanup();
    console.log("[FactChecker] Processing video:", videoId);

    // Extract metadata from the page
    const title = document.title || "";
    const descEl = document.querySelector("#description-inner") || document.querySelector("ytd-text-inline-expander");
    const description = descEl ? descEl.textContent : "";
    const metaKeywords = document.querySelector('meta[name="keywords"]');
    const tags = metaKeywords ? metaKeywords.content : "";

    // Step 1: Check if political
    injectLoadingCard();

    const politicalCheck = await API_checkIfPolitical({ title, description, tags });

    if (!politicalCheck.isPolitical) {
      document.querySelectorAll(".ytfc-loading-card").forEach((el) => el.remove());
      console.log("[FactChecker] Video is not political, skipping.");
      return;
    }

    try {
      currentTranscriptSegments = await fetchTranscriptSegments();
      const upload = await API_uploadTranscript(window.location.href, currentTranscriptSegments);
      currentTranscriptId = upload.transcriptId;
      console.log("[FactChecker] Transcript uploaded:", upload);
    } catch (error) {
      currentTranscriptId = null;
      currentTranscriptSegments = [];
      console.error("[FactChecker] Could not extract/upload transcript:", error);
    }

    // Step 2: Full analysis
    if (typeof API_streamFullAnalysis === "function") {
      const analysis = emptyVideoAnalysis();
      let settled = false;

      activeAnalysisCancel = API_streamFullAnalysis(window.location.href, currentTranscriptId, {
        onClaimFinal: (event) => {
          analysis.claims[event.claimIndex] = event.claim;
          injectFactCheckCard(analysis);
        },
        onSummaryUpdated: (event) => {
          analysis.summary = event.summary;
          analysis.trustworthinessScore = event.trustworthinessScore;
          analysis.maxScore = event.maxScore;
          analysis.trustworthinessLabel = event.trustworthinessLabel;
          analysis.politicalLean = event.politicalLean;
          analysis.aggregatedSources = event.aggregatedSources;
          injectFactCheckCard(analysis);
        },
        onDone: (event) => {
          settled = true;
          activeAnalysisCancel = null;
          injectFactCheckCard(event.result);
        },
        onStreamError: (event) => {
          console.warn("[FactChecker] recoverable stream error:", event);
        },
        onConnectionError: async () => {
          if (settled) return;
          settled = true;
          activeAnalysisCancel = null;
          const fallback = await API_getFullAnalysis(
            window.location.href,
            currentTranscriptSegments.length > 0 ? currentTranscriptSegments : null,
            currentTranscriptId
          );
          injectFactCheckCard(fallback);
        }
      });

      injectFactCheckCard(analysis);
    } else {
      const analysis = await API_getFullAnalysis(
        window.location.href,
        currentTranscriptSegments.length > 0 ? currentTranscriptSegments : null,
        currentTranscriptId
      );
      injectFactCheckCard(analysis);
    }

    // Step 3: Inject record button & sidebar
    injectRecordButton();
    ensureClipSidebar();
  }

  // ── YouTube SPA Navigation Detection ──

  function waitForElement(selector, timeout = 10000) {
    return new Promise((resolve) => {
      const existing = document.querySelector(selector);
      if (existing) return resolve(existing);

      const observer = new MutationObserver(() => {
        const el = document.querySelector(selector);
        if (el) {
          observer.disconnect();
          resolve(el);
        }
      });

      observer.observe(document.body, { childList: true, subtree: true });

      setTimeout(() => {
        observer.disconnect();
        resolve(null);
      }, timeout);
    });
  }

  // Listen for YouTube's SPA navigations
  let lastUrl = "";
  const urlObserver = new MutationObserver(() => {
    if (window.location.href !== lastUrl) {
      lastUrl = window.location.href;
      if (lastUrl.includes("youtube.com/watch")) {
        // Wait for the page elements to render
        waitForElement("#middle-row").then(() => {
          setTimeout(initForVideo, 500);
        });
      } else {
        cleanup();
        currentVideoId = null;
      }
    }
  });

  urlObserver.observe(document.body, { childList: true, subtree: true });

  // Also listen for messages from background script
  chrome.runtime.onMessage.addListener((message) => {
    if (message.type === "URL_CHANGED" && message.url.includes("youtube.com/watch")) {
      waitForElement("#owner").then(() => {
        setTimeout(initForVideo, 500);
      });
    }
  });

  // Initial load
  if (window.location.href.includes("youtube.com/watch")) {
    waitForElement("#owner").then(() => {
      setTimeout(initForVideo, 500);
    });
  }
})();
