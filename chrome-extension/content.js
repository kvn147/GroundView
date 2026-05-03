// YouTube Political Fact-Checker — Content Script
// Injects fact-check UI into YouTube watch pages

(function () {
  "use strict";

  let currentVideoId = null;
  let isRecording = false;
  let recordStartTime = 0;
  let recordTimerInterval = null;
  let clipResults = [];

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

  function getVerdictClass(verdict) {
    const v = verdict.toLowerCase().replace(/\s+/g, "-");
    return `ytfc-verdict-${v}`;
  }

  function getScoreClass(score) {
    return `ytfc-score-${score}`;
  }

  function cleanup() {
    document.querySelectorAll(".ytfc-card, .ytfc-loading-card, .ytfc-clip-sidebar").forEach((el) => el.remove());
    const btn = document.querySelector(".ytfc-record-btn");
    if (btn) btn.remove();
    stopRecording(true);
    clipResults = [];
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
    const result = await API_analyzeClip(videoUrl, recordStartTime, endTime);

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

    // Step 2: Full analysis
    const analysis = await API_getFullAnalysis(window.location.href);
    injectFactCheckCard(analysis);

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
