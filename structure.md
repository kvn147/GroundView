# Project Structure: Fact Checker App

Based on the agentic infrastructure described in the README, a monorepo approach separating the frontend (UI) and backend (Agentic APIs) is recommended. Python is an excellent choice for the backend due to its strong AI/Agent ecosystem, while a modern JavaScript framework like Next.js or React (Vite) is ideal for the frontend.

## Proposed Directory Structure

```text
beaverhacks-project/
├── backend/                  # Python backend (FastAPI recommended)
│   ├── api/                  # API routes (e.g., POST /process-video)
│   ├── core/                 # Core orchestration logic
│   │   ├── router.py         # Topic router for claims
│   │   ├── judge.py          # Judge model synthesis logic
│   │   └── tools.py          # Scoped tools for agents (search, etc.)
│   ├── agents/               # The 3 domain-specific agents
│   │   ├── agent_politics.py # Politics Agent
│   │   ├── agent_science.py  # Science/Health Agent
│   │   └── agent_general.py  # General Facts Agent
│   ├── services/             # External service integrations
│   │   ├── youtube.py        # YouTube URL parsing and transcript extraction
│   │   ├── gemini.py         # Gemini API calls (claim extraction, etc.)
│   │   └── sources.py        # Integrations for the 5 verification sources
│   ├── evals/                # Eval harness for testing agent performance
│   │   └── test_judge.py     # Evaluation scripts
│   ├── main.py               # FastAPI application entry point
│   └── requirements.txt      # Python dependencies
│
├── frontend/                 # Frontend application (Next.js / React)
│   ├── src/
│   │   ├── components/       # Reusable UI components
│   │   │   ├── VideoPlayer.tsx # YouTube embed wrapper (syncs time)
│   │   │   ├── Sidebar.tsx     # The interactive fact-check sidebar
│   │   │   ├── ClaimCard.tsx   # Individual claim with hedged response & sources
│   │   │   └── TimelineMarker.tsx # Visual markers on the video timeline
│   │   ├── hooks/            # Custom React hooks (e.g., API fetching)
│   │   ├── types/            # TypeScript definitions (Claim, Source, etc.)
│   │   ├── app/              # Next.js App Router (or pages/)
│   │   └── styles/           # Global styles and CSS
│   ├── package.json          # Node dependencies
│   └── tsconfig.json         # TypeScript configuration
│
├── README.md                 # Project overview
├── infrastructure.png        # Architecture diagram
└── structure.md              # This file
```

## Key Architectural Decisions

1. **Backend (Python / FastAPI):**
   - **Why:** The AI ecosystem in Python is mature. FastAPI is highly performant and handles asynchronous operations beautifully, which is crucial since you are running "3 domain-specific agents in parallel".
   - **Evals:** The `evals/` directory is specifically included to satisfy the "eval harness" part of your ConductorOne track, allowing you to test the accuracy of your judge model and agents against known claims.

2. **Frontend (React / Next.js):**
   - **Why:** You need an interactive, dynamic UI for the sidebar and timeline markers. A component-based framework makes it much easier to sync the YouTube player's current video time with the corresponding fact-checks displayed in the sidebar.

3. **Separation of Concerns:**
   - The frontend is strictly responsible for rendering the YouTube video, reading its state, and displaying annotations.
   - The backend is stateless, handling the heavy lifting: downloading transcripts, routing to agents, running the judge model, and returning a clean JSON array of claims with timestamps and verdicts.
