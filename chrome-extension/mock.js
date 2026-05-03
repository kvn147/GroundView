// =============================================================================
// MOCK DATA — Replace everything in this file with real API calls to the backend
// =============================================================================

/**
 * MOCK: Checks if a video is political based on its metadata.
 * Replace with: POST /api/check-political { title, description, tags, aiDescription }
 * Expected real response: { isPolitical: boolean }
 */
function MOCK_checkIfPolitical(metadata) {
  console.log("[MOCK] checkIfPolitical called with:", metadata);
  return new Promise((resolve) => {
    setTimeout(() => {
      resolve({ isPolitical: true });
    }, 800);
  });
}

/**
 * MOCK: Gets the full fact-check analysis for a political video.
 * Replace with: POST /api/analyze-video { url }
 * Expected real response: full analysis object (see shape below)
 */
function MOCK_getFullAnalysis(videoUrl) {
  console.log("[MOCK] getFullAnalysis called with:", videoUrl);
  return new Promise((resolve) => {
    setTimeout(() => {
      resolve({
        summary: "This video contains several political claims with mixed accuracy. Some statistics cited are outdated or lack proper context.",
        trustworthinessScore: 3,
        maxScore: 5,
        trustworthinessLabel: "Mixed Accuracy",
        politicalLean: {
          label: "Leans Right",
          value: 0.65,
        },
        claims: [
          {
            id: "claim-1",
            text: "The unemployment rate has doubled under the current administration.",
            verdict: "Mostly False",
            explanation:
              "Bureau of Labor Statistics data shows the unemployment rate increased by 0.8 percentage points, not doubled. The claim significantly exaggerates the actual change.",
            sources: [
              { name: "Bureau of Labor Statistics", url: "https://www.bls.gov/news.release/empsit.nr0.htm" },
              { name: "FactCheck.org", url: "https://www.factcheck.org" },
            ],
          },
          {
            id: "claim-2",
            text: "Immigration has increased by 300% compared to 2019 levels.",
            verdict: "Mixed",
            explanation:
              "Border encounter numbers did rise significantly, but the 300% figure depends on which specific metric is used. Encounters at the southern border rose roughly 200% using CBP data, but other measures vary.",
            sources: [
              { name: "CBP Enforcement Statistics", url: "https://www.cbp.gov/newsroom/stats" },
              { name: "Migration Policy Institute", url: "https://www.migrationpolicy.org" },
            ],
          },
          {
            id: "claim-3",
            text: "The infrastructure bill allocated $1.2 trillion for roads and bridges.",
            verdict: "Mostly True",
            explanation:
              "The Infrastructure Investment and Jobs Act totaled approximately $1.2 trillion, but only about $550 billion represents new spending. The rest reauthorizes existing programs. Roads and bridges received a portion, not the entirety.",
            sources: [
              { name: "Congress.gov", url: "https://www.congress.gov" },
              { name: "White House Briefing", url: "https://www.whitehouse.gov" },
            ],
          },
          {
            id: "claim-4",
            text: "Crime rates are at an all-time high nationwide.",
            verdict: "False",
            explanation:
              "FBI Uniform Crime Report data shows that violent crime rates peaked in the early 1990s and have generally declined since. Recent data shows some increases in specific categories but overall rates remain well below historical highs.",
            sources: [
              { name: "FBI UCR Data", url: "https://crime-data-explorer.fr.cloud.gov" },
              { name: "Brennan Center for Justice", url: "https://www.brennancenter.org" },
            ],
          },
          {
            id: "claim-5",
            text: "The education budget was cut by 25% last fiscal year.",
            verdict: "Mostly True",
            explanation:
              "The Department of Education's discretionary budget saw a proposed 25% reduction in the initial budget request. However, the final appropriated amount after congressional negotiation was reduced by approximately 18%.",
            sources: [
              { name: "Department of Education Budget", url: "https://www.ed.gov/about/overview/budget" },
              { name: "National Education Association", url: "https://www.nea.org" },
            ],
          },
        ],
        aggregatedSources: [
          { name: "Bureau of Labor Statistics", url: "https://www.bls.gov", citedCount: 1 },
          { name: "CBP Enforcement Statistics", url: "https://www.cbp.gov/newsroom/stats", citedCount: 1 },
          { name: "FBI UCR Data", url: "https://crime-data-explorer.fr.cloud.gov", citedCount: 1 },
          { name: "Congress.gov", url: "https://www.congress.gov", citedCount: 1 },
          { name: "FactCheck.org", url: "https://www.factcheck.org", citedCount: 1 },
          { name: "Migration Policy Institute", url: "https://www.migrationpolicy.org", citedCount: 1 },
        ],
      });
    }, 1500);
  });
}

/**
 * MOCK: Analyzes a manually-recorded clip.
 * Replace with: POST /api/analyze-clip { url, startTime, endTime, captions }
 * Expected real response: clip analysis object (see shape below)
 */
function MOCK_analyzeClip(videoUrl, startTime, endTime) {
  console.log("[MOCK] analyzeClip called:", { videoUrl, startTime, endTime });
  const mockClips = [
    {
      claim: "Tax revenue decreased by 40% after the policy change.",
      verdict: "Mostly False",
      explanation:
        "Tax revenue projections from the CBO show a decrease of approximately 12%, not 40%. The larger figure appears to conflate nominal and inflation-adjusted numbers.",
      sources: [
        { name: "Congressional Budget Office", url: "https://www.cbo.gov" },
        { name: "Tax Policy Center", url: "https://www.taxpolicycenter.org" },
      ],
    },
    {
      claim: "Healthcare costs have tripled for the average family.",
      verdict: "Mixed",
      explanation:
        "Kaiser Family Foundation data shows employer-sponsored family premiums rose about 47% over the past decade, not tripled. However, out-of-pocket costs in certain categories have seen steeper increases.",
      sources: [
        { name: "Kaiser Family Foundation", url: "https://www.kff.org" },
        { name: "HealthCare.gov", url: "https://www.healthcare.gov" },
      ],
    },
    {
      claim: "Foreign aid spending makes up 25% of the federal budget.",
      verdict: "False",
      explanation:
        "Foreign aid accounts for less than 1% of the federal budget. This is a commonly cited misconception — polls show many Americans overestimate foreign aid spending.",
      sources: [
        { name: "USAspending.gov", url: "https://www.usaspending.gov" },
        { name: "Brookings Institution", url: "https://www.brookings.edu" },
      ],
    },
  ];
  return new Promise((resolve) => {
    setTimeout(() => {
      const randomClip = mockClips[Math.floor(Math.random() * mockClips.length)];
      resolve({
        startTime,
        endTime,
        ...randomClip,
      });
    }, 1200);
  });
}
