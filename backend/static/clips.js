(function () {
  "use strict";

  const STORAGE_KEY = "ytfc-publisher-session-id";

  function createSessionId() {
    if (globalThis.crypto?.randomUUID) {
      return globalThis.crypto.randomUUID();
    }
    return `sess-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }

  function getSessionId(initialSessionId) {
    if (initialSessionId) {
      window.localStorage.setItem(STORAGE_KEY, initialSessionId);
      return initialSessionId;
    }
    const existing = window.localStorage.getItem(STORAGE_KEY);
    if (existing) return existing;
    const created = createSessionId();
    window.localStorage.setItem(STORAGE_KEY, created);
    return created;
  }

  function formatTime(seconds) {
    const total = Math.max(0, Math.floor(Number(seconds) || 0));
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const secs = total % 60;
    if (hours > 0) {
      return `${hours}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
    }
    return `${minutes}:${String(secs).padStart(2, "0")}`;
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function getVideoId(videoUrl) {
    try {
      const parsed = new URL(videoUrl);
      const direct = parsed.searchParams.get("v");
      if (direct) return direct;
      if (parsed.hostname.endsWith("youtu.be")) {
        return parsed.pathname.replace(/^\/+/, "").split("/")[0] || "";
      }
      const embedMatch = parsed.pathname.match(/\/embed\/([^/?#]+)/);
      return embedMatch ? embedMatch[1] : "";
    } catch (_err) {
      return "";
    }
  }

  function getEmbedUrl(videoUrl, startTime) {
    const videoId = getVideoId(videoUrl);
    if (!videoId) return "";
    const start = Math.max(0, Math.floor(Number(startTime) || 0));
    return `https://www.youtube.com/embed/${videoId}?start=${start}&autoplay=1`;
  }

  const urlState = new URL(window.location.href);
  const incomingSessionId = urlState.searchParams.get("session");

  const state = {
    sessionId: getSessionId(incomingSessionId),
    currentUrl: "",
    board: null
  };

  const form = document.getElementById("video-form");
  const input = document.getElementById("video-url-input");
  const iframe = document.getElementById("video-frame");
  const clipList = document.getElementById("clip-list");
  const boardStatus = document.getElementById("board-status");
  const countPill = document.getElementById("clip-count-pill");
  const youtubeLink = document.getElementById("youtube-link");

  async function fetchBoard(videoUrl) {
    const query = new URLSearchParams({
      url: videoUrl,
      sessionId: state.sessionId
    });
    const response = await fetch(`/api/published-clips?${query.toString()}`);
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    return response.json();
  }

  async function vote(clipId, value) {
    const response = await fetch(`/api/published-clips/${clipId}/vote`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        sessionId: state.sessionId,
        vote: value
      })
    });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    return response.json();
  }

  function setStatus(message, mode = "") {
    boardStatus.textContent = message;
    boardStatus.dataset.mode = mode;
  }

  function renderBoard(board) {
    state.board = board;
    state.currentUrl = board.videoUrl;

    input.value = board.videoUrl;
    iframe.src = board.embedUrl || "";
    youtubeLink.href = board.videoUrl || "#";
    countPill.textContent = `${board.clips.length} published clip${board.clips.length === 1 ? "" : "s"}`;

    clipList.innerHTML = "";
    if (board.clips.length === 0) {
      setStatus("No one has published a clip fact-check for this video yet.", "empty");
      return;
    }

    setStatus("Vote on the most useful fact-checks. Ranking uses total vote activity first.", "ready");

    board.clips.forEach((clip) => {
      const article = document.createElement("article");
      article.className = "board-card";
      const publishedBy = clip.sessionId ? clip.sessionId.slice(0, 8) : "unknown";
      article.innerHTML = `
        <div class="board-card-top">
          <button class="timestamp-button" type="button" data-start="${clip.startTime}">
            ${formatTime(clip.startTime)} - ${formatTime(clip.endTime)}
          </button>
          <div class="vote-cluster">
            <button class="vote-button ${clip.userVote === 1 ? "is-active" : ""}" type="button" data-vote="1">▲ ${clip.upvotes}</button>
            <button class="vote-button ${clip.userVote === -1 ? "is-active vote-down" : "vote-down"}" type="button" data-vote="-1">▼ ${clip.downvotes}</button>
          </div>
        </div>
        <h3 class="board-claim">${escapeHtml(clip.claim || "Untitled clip")}</h3>
        <div class="board-meta">
          <span class="verdict-badge verdict-${escapeHtml((clip.verdict || "pending").toLowerCase().replace(/\s+/g, "-"))}">${escapeHtml(clip.verdict || "Pending")}</span>
          <span>Published by ${escapeHtml(publishedBy)}</span>
          <span>${clip.totalVotes} total votes</span>
          <span>Score ${clip.score >= 0 ? "+" : ""}${clip.score}</span>
        </div>
        <p class="board-explanation">${escapeHtml(clip.explanation || "No explanation provided.")}</p>
        <div class="source-row">
          ${(clip.sources || []).map((source) => {
            const name = escapeHtml(source.name || "Source");
            if (!source.url) return `<span class="source-chip">${name}</span>`;
            return `<a class="source-chip" href="${escapeHtml(source.url)}" target="_blank" rel="noopener">${name}</a>`;
          }).join("")}
        </div>
      `;

      article.querySelector(".timestamp-button")?.addEventListener("click", () => {
        iframe.src = getEmbedUrl(state.currentUrl, clip.startTime);
      });

      article.querySelectorAll(".vote-button").forEach((button) => {
        button.addEventListener("click", async () => {
          const voteValue = Number(button.dataset.vote);
          button.disabled = true;
          try {
            await vote(clip.id, voteValue);
            await loadBoard(state.currentUrl, false);
          } catch (error) {
            setStatus(`Vote failed: ${error.message || error}`, "error");
          } finally {
            button.disabled = false;
          }
        });
      });

      clipList.appendChild(article);
    });
  }

  async function loadBoard(videoUrl, updateQuery = true) {
    const trimmedUrl = (videoUrl || "").trim();
    if (!trimmedUrl) return;
    setStatus("Loading published clips...", "loading");
    clipList.innerHTML = "";

    try {
      const board = await fetchBoard(trimmedUrl);
      if (updateQuery) {
        const next = new URL(window.location.href);
        next.searchParams.set("url", trimmedUrl);
        window.history.replaceState({}, "", next);
      }
      renderBoard(board);
    } catch (error) {
      iframe.src = "";
      countPill.textContent = "0 published clips";
      setStatus(`Could not load the board: ${error.message || error}`, "error");
    }
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    loadBoard(input.value, true);
  });

  const initialUrl = urlState.searchParams.get("url");
  if (initialUrl) {
    loadBoard(initialUrl, false);
  }
})();
