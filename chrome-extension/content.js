// YouTube Political Fact-Checker — Content Script
// Injects fact-check UI into YouTube watch pages

(function () {
  "use strict";

  let currentVideoId = null;
  let isRecording = false;
  let recordStartTime = 0;
  let recordTimerInterval = null;
  let clipResults = [];
  let currentAnalysis = null;
  let currentTranscriptId = null;
  let currentTranscriptSegments = [];
  let timelineSyncInterval = null;

  const CLAIM_ACTIVE_PADDING_SECONDS = 8;
  const HARDCODED_DEMO_VIDEO_IDS = new Set(["jCsL4Wmndho", "d4Tinv8DMBM"]);

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

  function seekVideoTo(seconds) {
    const video = document.querySelector("video.html5-main-video");
    if (video) {
      video.currentTime = seconds;
    }
  }

  function delay(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  function clamp(value, min, max) {
    return Math.min(max, Math.max(min, value));
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/\"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function normalizeLean(rawLean) {
    const lean = rawLean && typeof rawLean === "object" ? rawLean : {};
    const rawValue = Number.isFinite(lean.value) ? lean.value : 0;
    const meterValue = (clamp(rawValue, -1, 1) + 1) / 2;
    return {
      label: typeof lean.label === "string" && lean.label.trim() ? lean.label : "Unknown",
      value: rawValue,
      meterValue
    };
  }

  function normalizeSource(source) {
    if (!source || typeof source !== "object") return null;
    const name = typeof source.name === "string" ? source.name.trim() : "";
    if (!name) return null;
    return {
      name,
      url: typeof source.url === "string" ? source.url : ""
    };
  }

  function normalizeActivity(activity) {
    if (!Array.isArray(activity)) return [];
    return activity
      .filter((row) => row && typeof row === "object")
      .map((row) => ({
        agent: typeof row.agent === "string" ? row.agent : "Unknown agent",
        queried_sources: Array.isArray(row.queried_sources) ? row.queried_sources.filter(Boolean) : [],
        denied_sources: Array.isArray(row.denied_sources) ? row.denied_sources.filter(Boolean) : [],
        allowed_sources: Array.isArray(row.allowed_sources) ? row.allowed_sources.filter(Boolean) : [],
        cache_hit: !!row.cache_hit,
        model_used: typeof row.model_used === "string" ? row.model_used : "",
        duration_ms: Number.isFinite(row.duration_ms) ? row.duration_ms : 0,
        error: typeof row.error === "string" && row.error.trim() ? row.error : ""
      }));
  }

  function normalizeEvidence(evidence) {
    if (!Array.isArray(evidence)) return [];
    return evidence
      .filter((item) => item && typeof item === "object")
      .map((item) => ({
        source: typeof item.source === "string" ? item.source : (item.name || ""),
        url: typeof item.url === "string" ? item.url : "",
        stance: typeof item.stance === "string" ? item.stance : "unverifiable",
        snippet: typeof item.snippet === "string"
          ? item.snippet
          : (typeof item.text === "string" ? item.text : "")
      }))
      .filter((item) => item.source);
  }

  function getOpinionBadge(lean) {
    const value = Number.isFinite(lean?.value) ? lean.value : 0;
    if (value < -0.2) return { label: "Leans Left", className: "ytfc-opinion-left" };
    if (value > 0.2) return { label: "Leans Right", className: "ytfc-opinion-right" };
    return { label: "Center / Mixed", className: "ytfc-opinion-center" };
  }

  function normalizeAnalysisItem(item, kind, index) {
    const sourceList = Array.isArray(item?.sources) ? item.sources.map(normalizeSource).filter(Boolean) : [];
    const evidenceList = normalizeEvidence(item?.evidence);
    const lean = kind === "opinion" ? normalizeLean(item?.lean) : null;
    const text = typeof item?.text === "string" && item.text.trim()
      ? item.text.trim()
      : (typeof item?.claim === "string" ? item.claim.trim() : "");
    const explanation = typeof item?.explanation === "string" && item.explanation.trim()
      ? item.explanation.trim()
      : (typeof item?.summary === "string" ? item.summary.trim() : "");

    return {
      id: typeof item?.id === "string" ? item.id : `${kind}-${index + 1}`,
      kind,
      text,
      explanation,
      startTime: Number.isFinite(item?.startTime) ? item.startTime : null,
      endTime: Number.isFinite(item?.endTime) ? item.endTime : null,
      verdict: kind === "claim" ? (typeof item?.verdict === "string" ? item.verdict : "Unverified") : "",
      lean,
      sources: sourceList,
      evidence: evidenceList,
      activity: normalizeActivity(item?.activity)
    };
  }

  function normalizeAnalysisData(data) {
    const claims = Array.isArray(data?.claims)
      ? data.claims.map((item, index) => normalizeAnalysisItem(item, "claim", index)).filter((item) => item.text)
      : [];
    const opinions = Array.isArray(data?.opinions)
      ? data.opinions.map((item, index) => normalizeAnalysisItem(item, "opinion", index)).filter((item) => item.text)
      : [];
    const aggregatedSources = Array.isArray(data?.aggregatedSources)
      ? data.aggregatedSources.map(normalizeSource).filter(Boolean)
      : [];

    return {
      summary: typeof data?.summary === "string" ? data.summary : "",
      trustworthinessScore: Number.isFinite(data?.trustworthinessScore) ? data.trustworthinessScore : 3,
      maxScore: Number.isFinite(data?.maxScore) ? data.maxScore : 5,
      trustworthinessLabel: typeof data?.trustworthinessLabel === "string" ? data.trustworthinessLabel : "Mixed Accuracy",
      politicalLean: normalizeLean(data?.politicalLean),
      claims,
      opinions,
      aggregatedSources
    };
  }

  function buildTimestampMarkup(startTime, endTime) {
    if (!Number.isFinite(startTime)) return "";
    const safeEnd = Number.isFinite(endTime) ? endTime : startTime;
    return `<div class="ytfc-claim-detail-meta">Timestamp: <button class="ytfc-claim-detail-timestamp" type="button" data-time="${startTime}" aria-label="Seek video to ${formatTime(startTime)}">${formatTime(startTime)}${safeEnd > startTime ? ` - ${formatTime(safeEnd)}` : ""}</button></div>`;
  }

  function buildSourcesMarkup(sources, className = "ytfc-claim-sources") {
    if (!Array.isArray(sources) || sources.length === 0) return "";
    return `
      <div class="${className}">
        ${sources.map((source) => {
          const safeName = escapeHtml(source.name);
          if (!source.url) return `<span class="ytfc-source-chip ytfc-source-chip-static">${safeName}</span>`;
          const safeUrl = escapeHtml(source.url);
          return `<a href="${safeUrl}" target="_blank" rel="noopener">${safeName}</a>`;
        }).join("")}
      </div>
    `;
  }

  function buildEvidenceMarkup(evidence) {
    if (!Array.isArray(evidence) || evidence.length === 0) return "";
    return `
      <div class="ytfc-activity-group">
        <div class="ytfc-detail-subheader">Evidence</div>
        <div class="ytfc-evidence-list">
          ${evidence.map((item) => `
            <div class="ytfc-evidence-row">
              <div class="ytfc-evidence-top">
                <span class="ytfc-evidence-source">${escapeHtml(item.source)}</span>
                <span class="ytfc-evidence-stance ytfc-evidence-${escapeHtml(item.stance)}">${escapeHtml(item.stance)}</span>
              </div>
              ${item.snippet ? `<div class="ytfc-evidence-snippet">${escapeHtml(item.snippet)}</div>` : ""}
            </div>
          `).join("")}
        </div>
      </div>
    `;
  }

  function buildActivityMarkup(activity) {
    if (!Array.isArray(activity) || activity.length === 0) return "";
    return `
      <div class="ytfc-activity-group">
        <div class="ytfc-detail-subheader">Agent Activity</div>
        <div class="ytfc-activity-list">
          ${activity.map((row) => {
            const meta = [];
            if (row.model_used) meta.push(escapeHtml(row.model_used));
            if (row.duration_ms > 0) meta.push(`${row.duration_ms}ms`);
            if (row.cache_hit) meta.push("cache hit");
            return `
              <div class="ytfc-activity-row">
                <div class="ytfc-activity-top">
                  <span class="ytfc-activity-agent">${escapeHtml(row.agent)}</span>
                  ${meta.length > 0 ? `<span class="ytfc-activity-meta">${meta.join(" · ")}</span>` : ""}
                </div>
                ${row.queried_sources.length > 0 ? `<div class="ytfc-activity-line">Queried: ${escapeHtml(row.queried_sources.join(", "))}</div>` : ""}
                ${row.denied_sources.length > 0 ? `<div class="ytfc-activity-line">Denied: ${escapeHtml(row.denied_sources.join(", "))}</div>` : ""}
                ${row.error ? `<div class="ytfc-activity-line ytfc-activity-error">Error: ${escapeHtml(row.error)}</div>` : ""}
              </div>
            `;
          }).join("")}
        </div>
      </div>
    `;
  }

  function buildAnalysisItemMarkup(item) {
    const badge = item.kind === "claim"
      ? {
          label: item.verdict,
          className: `ytfc-verdict ${getVerdictClass(item.verdict)}`
        }
      : (() => {
          const opinionBadge = getOpinionBadge(item.lean);
          return {
            label: opinionBadge.label,
            className: `ytfc-verdict ${opinionBadge.className}`
          };
        })();

    return `
      <div class="ytfc-claim-top">
        <div class="ytfc-claim-main">
          <span class="ytfc-claim-text">${escapeHtml(item.text)}</span>
        </div>
        <span class="${badge.className}">${escapeHtml(badge.label)}</span>
      </div>
      <div class="ytfc-claim-detail">
        ${buildTimestampMarkup(item.startTime, item.endTime)}
        ${item.explanation ? `<div class="ytfc-claim-explanation">${escapeHtml(item.explanation)}</div>` : ""}
        ${item.kind === "opinion" && item.lean ? `<div class="ytfc-claim-detail-meta">Lean: ${escapeHtml(item.lean.label)}</div>` : ""}
        ${buildSourcesMarkup(item.sources)}
        ${buildEvidenceMarkup(item.evidence)}
        ${buildActivityMarkup(item.activity)}
      </div>
    `;
  }

  function appendAnalysisSection(card, title, items) {
    const header = document.createElement("div");
    header.className = "ytfc-section-header";
    header.textContent = `${title} (${items.length})`;
    card.appendChild(header);

    const list = document.createElement("ul");
    list.className = "ytfc-claims-list";

    items.forEach((item) => {
      const li = document.createElement("li");
      li.className = "ytfc-claim";
      li.innerHTML = buildAnalysisItemMarkup(item);

      li.addEventListener("click", () => {
        li.classList.toggle("ytfc-expanded");
      });

      const detailTimestampButton = li.querySelector(".ytfc-claim-detail-timestamp");
      if (detailTimestampButton) {
        detailTimestampButton.addEventListener("click", (event) => {
          event.stopPropagation();
          seekVideoTo(parseFloat(detailTimestampButton.dataset.time));
        });
      }

      list.appendChild(li);
    });

    card.appendChild(list);
  }

  function isTranscriptPanelOpen() {
    return !!(
      document.querySelector("ytd-transcript-renderer") ||
      document.querySelector("transcript-segment-view-model")
    );
  }

  async function openTranscriptPanel() {
    if (isTranscriptPanelOpen()) {
      console.log("[FactChecker] Transcript panel already open");
      return true;
    }

    // Expand the description to reveal the "Show transcript" button
    const expandBtn = document.querySelector("tp-yt-paper-button#expand") ||
                      document.querySelector("#description-inline-expander #expand") ||
                      document.querySelector("ytd-text-inline-expander #expand");
    if (expandBtn) {
      console.log("[FactChecker] Expanding description...");
      expandBtn.click();
      await delay(500);
    }

    // Look for "Show transcript" button — try multiple selectors
    const allButtons = Array.from(document.querySelectorAll("button"));
    const transcriptBtn = allButtons.find((btn) => {
      const text = (btn.textContent || "").trim().toLowerCase();
      return text.includes("show transcript") || text === "transcript";
    });

    if (!transcriptBtn) {
      // Try the transcript section renderer
      const section = document.querySelector("ytd-video-description-transcript-section-renderer");
      if (section) {
        const btn = section.querySelector("button");
        if (btn) {
          console.log("[FactChecker] Clicking transcript section button");
          btn.click();
          await delay(2000);
          return isTranscriptPanelOpen();
        }
      }
      console.error("[FactChecker] Could not find 'Show transcript' button");
      return false;
    }

    console.log("[FactChecker] Clicking 'Show transcript' button");
    transcriptBtn.click();
    await delay(2000);
    return isTranscriptPanelOpen();
  }

  function parseTimestamp(timeStr) {
    const parts = timeStr.split(":").map(Number);
    if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
    if (parts.length === 2) return parts[0] * 60 + parts[1];
    return 0;
  }

  function isTimestampLabel(value) {
    return /^\d{1,2}:\d{2}(?::\d{2})?$/.test((value || "").trim());
  }

  function isElementVisible(el) {
    if (!(el instanceof Element)) return false;
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  }

  function getOwnVisibleText(el) {
    if (!(el instanceof Element)) return "";
    return (el.innerText || el.textContent || "").replace(/\s+/g, " ").trim();
  }

  function getTimestampNode(root) {
    if (!(root instanceof Element)) return null;
    const candidates = [root, ...root.querySelectorAll("*")];
    for (const el of candidates) {
      const text = getOwnVisibleText(el);
      if (!isElementVisible(el) || !isTimestampLabel(text)) continue;
      return el;
    }
    return null;
  }

  function getRowTextFromNode(row, timeNode) {
    const preferred = [
      "span.ytAttributedStringHost",
      ".segment-text",
      "yt-formatted-string",
      "[class*='segment-text']",
      "[class*='transcript'] span"
    ];

    for (const selector of preferred) {
      const match = row.querySelector(selector);
      const text = getOwnVisibleText(match);
      if (text && (!timeNode || match !== timeNode)) return text;
    }

    const clone = row.cloneNode(true);
    const removable = [clone, ...clone.querySelectorAll("*")];
    removable.forEach((el) => {
      const text = getOwnVisibleText(el);
      if (isTimestampLabel(text)) {
        el.remove();
      }
    });
    return getOwnVisibleText(clone);
  }

  function extractSegmentFromRow(row) {
    const timeNode = getTimestampNode(row);
    if (!timeNode) return null;

    const timeStr = getOwnVisibleText(timeNode);
    const text = getRowTextFromNode(row, timeNode);
    if (!text) return null;

    return {
      timestamp: parseTimestamp(timeStr),
      text
    };
  }

  function getTranscriptPanelRoot() {
    return document.querySelector(
      "ytd-engagement-panel-section-list-renderer[target-id='engagement-panel-searchable-transcript'], ytd-transcript-renderer"
    );
  }

  function findTranscriptStartAnchor() {
    const panelRoot = getTranscriptPanelRoot() || document;
    const candidates = Array.from(panelRoot.querySelectorAll("*"));
    return candidates.find((el) => isElementVisible(el) && getOwnVisibleText(el) === "0:00") || null;
  }

  function getTimestampRowCount(container, sampleRow) {
    if (!(container instanceof Element) || !(sampleRow instanceof Element)) return 0;
    const sampleTag = sampleRow.tagName;
    const sameTagRows = Array.from(container.querySelectorAll(sampleTag));
    const directChildren = Array.from(container.children);
    const directMatches = directChildren.filter((child) => getTimestampNode(child));
    const sameTagMatches = sameTagRows.filter((row) => getTimestampNode(row));
    return Math.max(directMatches.length, sameTagMatches.length);
  }

  function findTranscriptContainerFromAnchor(anchor) {
    if (!(anchor instanceof Element)) return null;

    let row = anchor;
    for (let i = 0; i < 6 && row.parentElement; i += 1) {
      if (extractSegmentFromRow(row)) break;
      row = row.parentElement;
    }

    let bestContainer = row.parentElement || row;
    let bestScore = getTimestampRowCount(bestContainer, row);
    let current = row.parentElement;

    for (let i = 0; i < 8 && current; i += 1) {
      const score = getTimestampRowCount(current, row);
      if (score >= bestScore) {
        bestContainer = current;
        bestScore = score;
      }
      current = current.parentElement;
    }

    return { row, container: bestContainer };
  }

  function scrapeTranscriptSegmentsFromInferredContainer() {
    const anchor = findTranscriptStartAnchor();
    if (!anchor) return [];

    const resolved = findTranscriptContainerFromAnchor(anchor);
    if (!resolved) return [];

    const { row, container } = resolved;
    const sampleTag = row.tagName;
    const directChildren = Array.from(container.children);
    const candidateRows = directChildren.some((child) => child.tagName === sampleTag)
      ? directChildren.filter((child) => child.tagName === sampleTag)
      : Array.from(container.querySelectorAll(sampleTag));

    const segments = [];
    const seen = new Set();

    candidateRows.forEach((candidate) => {
      const segment = extractSegmentFromRow(candidate);
      if (!segment) return;

      const key = `${segment.timestamp}:${segment.text}`;
      if (seen.has(key)) return;
      seen.add(key);
      segments.push(segment);
    });

    return segments.sort((a, b) => a.timestamp - b.timestamp);
  }

  function scrapeTranscriptSegments() {
    const segments = [];

    // Current YouTube DOM: transcript-segment-view-model
    const segmentEls = document.querySelectorAll("transcript-segment-view-model");

    if (segmentEls.length > 0) {
      console.log("[FactChecker] Found", segmentEls.length, "transcript-segment-view-model elements");
      segmentEls.forEach((el) => {
        const timeEl = el.querySelector(".ytwTranscriptSegmentViewModelTimestamp");
        const textEl = el.querySelector("span.ytAttributedStringHost");

        const timeStr = timeEl ? timeEl.textContent.trim() : "";
        const text = textEl ? textEl.textContent.trim() : "";

        if (text) {
          segments.push({ timestamp: parseTimestamp(timeStr), text });
        }
      });
      return segments;
    }

    // Fallback: older YouTube DOM (ytd-transcript-segment-renderer)
    const legacyEls = document.querySelectorAll("ytd-transcript-segment-renderer");
    if (legacyEls.length > 0) {
      console.log("[FactChecker] Found", legacyEls.length, "ytd-transcript-segment-renderer elements (legacy)");
      legacyEls.forEach((el) => {
        const timeEl = el.querySelector(".segment-timestamp, [class*='timestamp']");
        const textEl = el.querySelector(".segment-text, yt-formatted-string");

        const timeStr = timeEl ? timeEl.textContent.trim() : "";
        const text = textEl ? textEl.textContent.trim() : "";

        if (text) {
          segments.push({ timestamp: parseTimestamp(timeStr), text });
        }
      });
    }

    if (segments.length > 0) {
      return segments;
    }

    const inferredSegments = scrapeTranscriptSegmentsFromInferredContainer();
    if (inferredSegments.length > 0) {
      console.log("[FactChecker] Inferred transcript container from 0:00 anchor and scraped", inferredSegments.length, "segments");
    }
    return inferredSegments;
  }

  function closeTranscriptPanel() {
    // Try the X button on the engagement panel
    const closeBtn = document.querySelector(
      "ytd-engagement-panel-section-list-renderer[target-id='engagement-panel-searchable-transcript'] #visibility-button button"
    ) || document.querySelector(
      "ytd-engagement-panel-section-list-renderer button[aria-label='Close transcript']"
    );
    if (closeBtn) {
      closeBtn.click();
      console.log("[FactChecker] Closed transcript panel");
    }
  }

  async function fetchTranscriptSegments() {
    console.log("[FactChecker] Opening transcript panel to scrape segments...");

    const opened = await openTranscriptPanel();
    if (!opened) {
      throw new Error("Could not open transcript panel. Video may not have captions.");
    }

    // Wait for segments to render
    await delay(1000);

    // Scroll the transcript panel to load all segments (may be virtualized)
    const scrollContainer = document.querySelector(
      "ytd-transcript-renderer #body, " +
      "ytd-transcript-renderer [class*='body'], " +
      "ytd-engagement-panel-section-list-renderer[target-id='engagement-panel-searchable-transcript'] #content"
    );
    if (scrollContainer) {
      console.log("[FactChecker] Scrolling transcript panel to load all segments...");
      let prevHeight = 0;
      for (let i = 0; i < 50; i++) {
        scrollContainer.scrollTop = scrollContainer.scrollHeight;
        await delay(200);
        if (scrollContainer.scrollHeight === prevHeight) break;
        prevHeight = scrollContainer.scrollHeight;
      }
      scrollContainer.scrollTop = 0;
    }

    const segments = scrapeTranscriptSegments();
    console.log("[FactChecker] Scraped", segments.length, "transcript segments from DOM");

    if (segments.length === 0) {
      const all = document.querySelectorAll("transcript-segment-view-model, ytd-transcript-segment-renderer");
      console.error("[FactChecker] 0 segments scraped. Raw segment elements found:", all.length);
      closeTranscriptPanel();
      throw new Error("Transcript panel opened but no segments found.");
    }

    closeTranscriptPanel();
    return segments;
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
    clearInterval(timelineSyncInterval);
    timelineSyncInterval = null;
    clipResults = [];
    currentAnalysis = null;
    currentTranscriptId = null;
    currentTranscriptSegments = [];
  }

  function createClipLocalId() {
    if (globalThis.crypto?.randomUUID) {
      return globalThis.crypto.randomUUID();
    }
    return `clip-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }

  function updateBoardLink() {
    const boardLink = document.querySelector(".ytfc-board-link");
    if (!boardLink) return;
    boardLink.href = API_getBoardUrl(window.location.href);
  }

  async function publishClipResult(localId) {
    const clip = clipResults.find((entry) => entry.localId === localId);
    if (!clip || clip.publishState === "publishing" || clip.publishState === "published") return;

    clip.publishState = "publishing";
    clip.publishError = "";
    renderClipSidebar();

    try {
      const published = await API_publishClip(window.location.href, clip);
      clip.publishState = "published";
      clip.publishError = "";
      clip.publishedClipId = published.id;
      clip.publishedAt = published.publishedAt;
      clip.voteSummary = {
        upvotes: published.upvotes,
        downvotes: published.downvotes,
        totalVotes: published.totalVotes
      };
      console.log("[FactChecker] Published clip:", published.id);
    } catch (error) {
      clip.publishState = "error";
      clip.publishError = error.message || String(error);
      console.error("[FactChecker] Publish clip failed:", error);
    }

    renderClipSidebar();
  }

  function getClipPublishLabel(clip) {
    if (clip.publishState === "publishing") return "Publishing...";
    if (clip.publishState === "published") return "Published";
    return "Publish";
  }

  function getActiveClaimsForTime(currentTime) {
    const claims = currentAnalysis?.claims || [];
    return claims
      .filter((claim) => Number.isFinite(claim.startTime))
      .map((claim) => {
        const start = claim.startTime;
        const end = Number.isFinite(claim.endTime) ? Math.max(claim.endTime, start) : start;
        const paddedStart = Math.max(0, start - CLAIM_ACTIVE_PADDING_SECONDS);
        const paddedEnd = end + CLAIM_ACTIVE_PADDING_SECONDS;
        const inWindow = currentTime >= paddedStart && currentTime <= paddedEnd;
        const distance = inWindow
          ? 0
          : Math.min(Math.abs(currentTime - paddedStart), Math.abs(currentTime - paddedEnd));
        return { claim, start, end, inWindow, distance };
      })
      .filter((item) => item.inWindow)
      .sort((a, b) => a.distance - b.distance || a.start - b.start)
      .map((item) => item.claim);
  }

  function renderTimelineClaims() {
    const sidebar = document.querySelector(".ytfc-clip-sidebar");
    if (!sidebar) return;

    const timeEl = sidebar.querySelector(".ytfc-timeline-now");
    const list = sidebar.querySelector(".ytfc-timeline-list");
    if (!timeEl || !list) return;

    const currentTime = getVideoCurrentTime();
    timeEl.textContent = formatTime(currentTime);

    const activeClaims = getActiveClaimsForTime(currentTime);
    list.innerHTML = "";

    if (!currentAnalysis || !Array.isArray(currentAnalysis.claims)) {
      list.innerHTML = `<div class="ytfc-timeline-empty">Run video analysis to load timeline claims.</div>`;
      return;
    }

    if (activeClaims.length === 0) {
      list.innerHTML = `<div class="ytfc-timeline-empty">No extracted claim is mapped to this moment in the video.</div>`;
      return;
    }

    activeClaims.forEach((claim) => {
      const card = document.createElement("div");
      card.className = "ytfc-timeline-card";
      const claimStartTime = Number.isFinite(claim.startTime) ? claim.startTime : 0;
      const claimEndTime = Number.isFinite(claim.endTime) ? claim.endTime : claimStartTime;
      card.innerHTML = `
        <div class="ytfc-timeline-meta">
          <button class="ytfc-timeline-ts" type="button" data-time="${claimStartTime}">${formatTime(claimStartTime)}${claimEndTime > claimStartTime ? ` - ${formatTime(claimEndTime)}` : ""}</button>
          <span class="ytfc-verdict ${getVerdictClass(claim.verdict)}">${claim.verdict}</span>
        </div>
        <div class="ytfc-timeline-claim">${claim.text}</div>
        <div class="ytfc-timeline-explanation">${claim.explanation}</div>
        <div class="ytfc-timeline-sources">
          ${claim.sources.map((s) => `<a href="${s.url}" target="_blank" rel="noopener">${s.name}</a>`).join("")}
        </div>
      `;

      const tsButton = card.querySelector(".ytfc-timeline-ts");
      if (tsButton) {
        tsButton.addEventListener("click", () => {
          seekVideoTo(parseFloat(tsButton.dataset.time));
        });
      }

      list.appendChild(card);
    });
  }

  function startTimelineSync() {
    clearInterval(timelineSyncInterval);
    timelineSyncInterval = setInterval(renderTimelineClaims, 500);
    renderTimelineClaims();
  }

  // ── Fact-Check Card Builder ──

  function buildFactCheckCard(data) {
    const analysis = normalizeAnalysisData(data);
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
      <span class="ytfc-score-badge ${getScoreClass(analysis.trustworthinessScore)}">
        ${analysis.trustworthinessLabel} &mdash; ${analysis.trustworthinessScore}/${analysis.maxScore}
      </span>
    `;
    card.appendChild(header);

    // Summary
    const summary = document.createElement("div");
    summary.className = "ytfc-summary";
    summary.textContent = analysis.summary;
    card.appendChild(summary);

    // Political lean
    const lean = document.createElement("div");
    lean.className = "ytfc-lean";
    lean.innerHTML = `
      <div class="ytfc-lean-label">
        <span>Left</span>
        <span>${analysis.politicalLean.label}</span>
        <span>Right</span>
      </div>
      <div class="ytfc-lean-bar">
        <div class="ytfc-lean-marker" style="left: ${analysis.politicalLean.meterValue * 100}%"></div>
      </div>
    `;
    card.appendChild(lean);

    appendAnalysisSection(card, "Claims", analysis.claims);
    if (analysis.opinions.length > 0) {
      appendAnalysisSection(card, "Opinions Detected", analysis.opinions);
    }

    // Aggregated sources
    const sourcesHeader = document.createElement("div");
    sourcesHeader.className = "ytfc-section-header";
    sourcesHeader.textContent = "Sources";
    card.appendChild(sourcesHeader);

    const sourcesGrid = document.createElement("div");
    sourcesGrid.className = "ytfc-sources-grid";
    analysis.aggregatedSources.forEach((src) => {
      const el = src.url ? document.createElement("a") : document.createElement("span");
      el.className = "ytfc-source-chip";
      if (src.url) {
        el.href = src.url;
        el.target = "_blank";
        el.rel = "noopener";
      } else {
        el.classList.add("ytfc-source-chip-static");
      }
      el.textContent = src.name;
      sourcesGrid.appendChild(el);
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
    console.log("[FactChecker] Analyzing clip:", { start: recordStartTime, end: endTime });

    const result = await API_analyzeClip(videoUrl, recordStartTime, endTime, currentTranscriptId);
    console.log("[FactChecker] Clip result:", result.verdict);

    removeClipLoading();
    clipResults.unshift({
      ...result,
      localId: createClipLocalId(),
      publishState: "idle",
      publishError: "",
      publishedClipId: null,
      publishedAt: null,
      voteSummary: null
    });
    renderClipSidebar();
  }

  // ── Injection: Clip Sidebar ──

  function ensureClipSidebar() {
    if (document.querySelector(".ytfc-clip-sidebar")) return;

    const sidebar = document.createElement("div");
    sidebar.className = "ytfc-clip-sidebar";
    sidebar.innerHTML = `
      <div class="ytfc-timeline-panel">
        <div class="ytfc-timeline-header">
          <span class="ytfc-timeline-title">Current Claim Context</span>
          <span class="ytfc-timeline-now">0:00</span>
        </div>
        <div class="ytfc-timeline-list">
          <div class="ytfc-timeline-empty">Run video analysis to load timeline claims.</div>
        </div>
      </div>
      <div class="ytfc-clip-sidebar-header">
        <div class="ytfc-clip-sidebar-title-group">
          <span class="ytfc-clip-sidebar-title">Clip Fact-Checks</span>
          <span class="ytfc-clip-count">0 clips</span>
        </div>
        <a class="ytfc-board-link" href="${API_getBoardUrl(window.location.href)}" target="_blank" rel="noopener">Open board</a>
      </div>
      <div class="ytfc-clip-list">
        <div class="ytfc-clip-empty">Record a clip to fact-check it</div>
      </div>
    `;

    const secondary = document.querySelector("#secondary-inner") || document.querySelector("#secondary");
    if (secondary) {
      secondary.insertBefore(sidebar, secondary.firstChild);
    }

    updateBoardLink();
    renderTimelineClaims();
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
      const publishLabel = getClipPublishLabel(clip);
      const publishDisabled = clip.publishState === "publishing" || clip.publishState === "published";
      const publishMeta = clip.publishState === "published" && clip.voteSummary
        ? `<div class="ytfc-clip-publish-meta">Published · ${clip.voteSummary.totalVotes} vote${clip.voteSummary.totalVotes !== 1 ? "s" : ""}</div>`
        : (clip.publishError ? `<div class="ytfc-clip-publish-error">${escapeHtml(clip.publishError)}</div>` : "");
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
        <div class="ytfc-clip-actions">
          <button class="ytfc-clip-publish-btn" type="button" data-clip-id="${clip.localId}" ${publishDisabled ? "disabled" : ""}>${publishLabel}</button>
          ${publishMeta}
        </div>
      `;
      card.querySelectorAll(".ytfc-clip-ts").forEach((ts) => {
        ts.addEventListener("click", () => {
          seekVideoTo(parseFloat(ts.dataset.time));
        });
      });
      const publishButton = card.querySelector(".ytfc-clip-publish-btn");
      if (publishButton) {
        publishButton.addEventListener("click", () => {
          publishClipResult(publishButton.dataset.clipId);
        });
      }

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

    console.log("[FactChecker] Extracted metadata:", {
      title: title.substring(0, 80),
      descriptionLength: description.length,
      tagsLength: tags.length
    });

    // Step 1: Check if political
    injectLoadingCard();

    const politicalCheck = await API_checkIfPolitical({ title, description, tags });
    console.log("[FactChecker] Political check result:", politicalCheck);

    if (!politicalCheck.isPolitical) {
      document.querySelectorAll(".ytfc-loading-card").forEach((el) => el.remove());
      console.log("[FactChecker] Video is not political, skipping.");
      return;
    }

    if (HARDCODED_DEMO_VIDEO_IDS.has(videoId)) {
      currentTranscriptId = null;
      currentTranscriptSegments = [];
      console.log("[FactChecker] Hard-coded demo video detected; skipping YouTube transcript scrape.");
    } else {
      console.log("[FactChecker] Video is political, proceeding with transcript extraction...");

      try {
        currentTranscriptSegments = await fetchTranscriptSegments();
        console.log("[FactChecker] Transcript extracted:", currentTranscriptSegments.length, "segments");
        const upload = await API_uploadTranscript(window.location.href, currentTranscriptSegments);
        currentTranscriptId = upload.transcriptId;
        console.log("[FactChecker] Transcript uploaded:", {
          transcriptId: upload.transcriptId,
          chunkCount: upload.chunkCount,
          totalCharacters: upload.totalCharacters
        });
      } catch (error) {
        currentTranscriptId = null;
        currentTranscriptSegments = [];
        console.error("[FactChecker] Transcript extraction/upload failed:", error.message || error);
      }
    }

    // Step 2: Full analysis
    console.log("[FactChecker] Starting full analysis...", {
      url: window.location.href,
      transcriptId: currentTranscriptId,
      hasTranscript: currentTranscriptSegments.length > 0
    });

    const analysis = await API_getFullAnalysis(
      window.location.href,
      currentTranscriptSegments.length > 0 ? currentTranscriptSegments : null,
      currentTranscriptId
    );
    console.log("[FactChecker] Analysis result — claims:", analysis.claims?.length || 0);
    currentAnalysis = analysis;
    injectFactCheckCard(analysis);

    // Step 3: Inject record button & sidebar
    injectRecordButton();
    ensureClipSidebar();
    startTimelineSync();
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
      console.log("[FactChecker] URL changed:", lastUrl);
      if (lastUrl.includes("youtube.com/watch")) {
        // Wait for the page elements to render
        waitForElement("#middle-row").then((el) => {
          console.log("[FactChecker] #middle-row found:", !!el, "— scheduling initForVideo");
          setTimeout(initForVideo, 500);
        });
      } else {
        console.log("[FactChecker] Not a watch page, cleaning up");
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
