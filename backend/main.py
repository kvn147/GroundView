from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from backend.api.video import api_router
from backend.clip_store import init_db

app = FastAPI(title="BeaverHacks Fact Checker API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api")

STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.on_event("startup")
async def startup() -> None:
    init_db()


@app.get("/", response_class=HTMLResponse)
@app.get("/clips", response_class=HTMLResponse)
async def clips_page() -> str:
    return """
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Clip Fact-Checks</title>
        <link rel="preconnect" href="https://fonts.googleapis.com">
        <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
        <link href="https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700&display=swap" rel="stylesheet">
        <link rel="stylesheet" href="/static/clips.css">
      </head>
      <body>
        <div class="app-shell">
          <header class="topbar">
            <div class="brand">
              <div class="brand-mark"></div>
              <div>
                <div class="brand-title">Clip Fact-Checks</div>
                <div class="brand-subtitle">Local board for published YouTube clip reviews</div>
              </div>
            </div>
            <form id="video-form" class="video-form">
              <input id="video-url-input" name="url" type="url" placeholder="Paste a YouTube URL" autocomplete="off" required>
              <button type="submit">Load Board</button>
            </form>
          </header>

          <main class="page-grid">
            <section class="video-stage">
              <div class="stage-panel">
                <div class="stage-header">
                  <h1>Video</h1>
                  <span id="clip-count-pill" class="count-pill">0 published clips</span>
                </div>
                <div class="video-frame-wrap">
                  <iframe
                    id="video-frame"
                    title="YouTube video review board"
                    allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
                    allowfullscreen
                  ></iframe>
                </div>
              </div>
            </section>

            <aside class="clips-panel">
              <div class="clips-panel-header">
                <div>
                  <h2>Published Clips</h2>
                  <p>Sorted by total vote activity, then score.</p>
                </div>
                <a id="youtube-link" href="#" target="_blank" rel="noopener" class="youtube-link">Open on YouTube</a>
              </div>
              <div id="board-status" class="board-status">Enter a YouTube URL to load published clip fact-checks.</div>
              <div id="clip-list" class="clip-list"></div>
            </aside>
          </main>
        </div>
        <script src="/static/clips.js"></script>
      </body>
    </html>
    """

if __name__ == "__main__":
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
