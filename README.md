# Fact Checker Project -- BeaverHacks 2026
Team: Cole, Tyler, David, Kevin

> **One-sentence pitch:** "We built a fact-check sidebar for political YouTube videos — so instead of Googling claims mid-debate, the context is already there next to the video."

**Track: ConductorOne** — parallel agents, scoped tools, eval harness, judge model. The architecture sells itself.

### What it is (Solution)
A YouTube fact-check layer for political content. Paste a URL, we process the video, you get an interactive sidebar showing every verifiable claim annotated on the timeline with sourced context — without ever leaving the page.

### The problem it solves (Problem Scope)
Misinformation is rampant across the internet and unbiased fact-checking is difficult. This solves two main issues:
1. **Real-time verification:** Political debate claims are hard to verify in real time — people either take them at face value or stop watching to Google.
2. **Out-of-context clips:** Viral political clips spread out of context — a 10-second clip can mean the opposite of what the full speech says. We specifically focus on short form content (Shorts, TikTok, Reels, etc.) where this spreads misinformation to millions quickly.

### How it works (Agentic Infrastructure)
- **Gemini** extracts a timestamped transcript from the YouTube URL.
- **LLM** extracts checkable factual claims only.
- **Topic router** classifies each claim.
- **3 domain-specific agents** verify in parallel across 5 sources.
- **Judge model** synthesizes an honest 2-3 sentence response — never a binary verdict, always hedged, always cited.
- Results render as a sidebar alongside the video with timeline markers.

### What makes it different
- Not a verdict machine — surfaces context and lets users decide
- Flags out-of-context clips, not just false claims
- Aggregates 5 sources and discloses when sourcing is skewed
- Consumer-facing, not a newsroom tool

### Future Directions
- Have this app be used as an overlay on live streams to check for misinformation.
- Pitch to social media platforms such as YouTube and TikTok to use this as a feature on their platform.
