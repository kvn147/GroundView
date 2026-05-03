"""Hard-coded local demo fixtures for known YouTube videos.

These fixtures keep the hackathon demo path independent from YouTube caption
scraping, API keys, and external LLM calls. The live pipeline remains the
default for every other URL.
"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any
from urllib.parse import parse_qs, urlparse

from backend.contracts import (
    AnalyzeClipResponse,
    AnalyzeVideoResponse,
    FrontendAggregatedSource,
    FrontendClaim,
    FrontendSource,
    PoliticalLean,
)


def _source(name: str, url: str = "") -> dict[str, str]:
    return {"name": name, "url": url}


DEMO_VIDEO_IDS = {"jCsL4Wmndho", "d4Tinv8DMBM"}


DEMO_TRANSCRIPTS: dict[str, list[dict[str, Any]]] = {
    "jCsL4Wmndho": [
        {"timestamp": 5.0, "text": "President Trump says he is not happy with Iran and its new offer."},
        {"timestamp": 20.0, "text": "The cease fire that began in early April is still holding."},
        {"timestamp": 56.0, "text": "The hostilities that began on February 28th 2026 have terminated."},
        {"timestamp": 72.0, "text": "Every other president considered the War Powers Act totally unconstitutional."},
        {"timestamp": 101.0, "text": "As a result of the war, gas prices have climbed to $4.39 a gallon."},
        {"timestamp": 122.0, "text": "If the president decides to break the cease fire, new strike options have been presented."},
        {"timestamp": 168.0, "text": "The Department of War is going to pull 5,000 troops out of Germany."},
        {"timestamp": 173.0, "text": "There are 38,000 American troops stationed there right now."},
        {"timestamp": 176.0, "text": "It is going to take 6 to 12 months for this to happen."},
    ],
    "d4Tinv8DMBM": [
        {"timestamp": 17.0, "text": "I am really calling for major jobs because the wealthy are going to create tremendous jobs."},
        {"timestamp": 33.0, "text": "It is a great thing for the middle class and a great thing for companies to expand."},
        {"timestamp": 40.0, "text": "They are going to bring two and a half trillion dollars back from overseas."},
        {"timestamp": 89.0, "text": "Republicans and Democrats agree that this should be done."},
        {"timestamp": 195.0, "text": "Trickle-down did not work; it got us into the mess we were in in 2008 and 2009."},
        {"timestamp": 273.0, "text": "We are in a big fat ugly bubble and we better be awfully careful."},
        {"timestamp": 337.0, "text": "I am under a routine audit and it will be released as soon as the audit is finished."},
        {"timestamp": 435.0, "text": "I will release my tax returns when she releases her 33,000 emails that have been deleted."},
        {"timestamp": 541.0, "text": "The only years anybody has seen showed he did not pay any federal income tax."},
        {"timestamp": 721.0, "text": "We have 20 trillion dollars in debt and our country's a mess."},
        {"timestamp": 765.0, "text": "We have spent six trillion dollars in the Middle East."},
        {"timestamp": 903.0, "text": "You have taken business bankruptcy six times."},
    ],
}


DEMO_RESPONSES: dict[str, dict[str, Any]] = {
    "jCsL4Wmndho": {
        "summary": (
            "Demo fixture: 5 selected claims from the supplied Iran/Germany segment "
            "are shown with canned, timestamped fact-check cards."
        ),
        "trustworthinessScore": 3,
        "maxScore": 5,
        "trustworthinessLabel": "Demo / Needs Context",
        "politicalLean": {"label": "Center / Mixed", "value": 0.0},
        "claims": [
            {
                "id": "demo-iran-1",
                "text": "The cease fire that began in early April is still holding.",
                "startTime": 20.0,
                "endTime": 24.0,
                "verdict": "Demo",
                "explanation": "Hard-coded demo card. In the live pipeline, this claim would be checked against current reporting and official statements before receiving a verdict.",
                "sources": [_source("Demo transcript")],
            },
            {
                "id": "demo-iran-2",
                "text": "The hostilities that began on February 28, 2026 have terminated.",
                "startTime": 56.0,
                "endTime": 61.0,
                "verdict": "Demo",
                "explanation": "Hard-coded demo card. This is a legal/status claim that the production system would route to legal and foreign-policy sources.",
                "sources": [_source("War Powers Resolution", "https://www.congress.gov/bill/93rd-congress/house-joint-resolution/542")],
            },
            {
                "id": "demo-iran-3",
                "text": "Gas prices have climbed to $4.39 a gallon as a result of the war.",
                "startTime": 101.0,
                "endTime": 107.0,
                "verdict": "Demo",
                "explanation": "Hard-coded demo card. The live version would compare the quoted price against current EIA/AAA data and separate price level from causal attribution.",
                "sources": [_source("U.S. Energy Information Administration", "https://www.eia.gov/petroleum/gasdiesel/")],
            },
            {
                "id": "demo-iran-4",
                "text": "The Department of War will pull 5,000 troops out of Germany.",
                "startTime": 168.0,
                "endTime": 172.0,
                "verdict": "Demo",
                "explanation": "Hard-coded demo card. This would normally be checked against Defense Department force-posture announcements.",
                "sources": [_source("U.S. Department of Defense", "https://www.defense.gov/News/Releases/")],
            },
            {
                "id": "demo-iran-5",
                "text": "There are 38,000 American troops stationed in Germany right now.",
                "startTime": 173.0,
                "endTime": 176.0,
                "verdict": "Demo",
                "explanation": "Hard-coded demo card. The live path would verify this against Defense Manpower Data Center or DoD posture reporting.",
                "sources": [_source("Defense Manpower Data Center", "https://dwp.dmdc.osd.mil/dwp/app/dod-data-reports/workforce-reports")],
            },
        ],
        "aggregatedSources": [
            {"name": "Demo transcript", "url": "", "citedCount": 1},
            {"name": "War Powers Resolution", "url": "https://www.congress.gov/bill/93rd-congress/house-joint-resolution/542", "citedCount": 1},
            {"name": "U.S. Energy Information Administration", "url": "https://www.eia.gov/petroleum/gasdiesel/", "citedCount": 1},
            {"name": "U.S. Department of Defense", "url": "https://www.defense.gov/News/Releases/", "citedCount": 1},
            {"name": "Defense Manpower Data Center", "url": "https://dwp.dmdc.osd.mil/dwp/app/dod-data-reports/workforce-reports", "citedCount": 1},
        ],
        "opinions": [],
    },
    "d4Tinv8DMBM": {
        "summary": (
            "Demo fixture: 6 selected claims from the supplied debate clip are "
            "rendered instantly for a stable local demo."
        ),
        "trustworthinessScore": 3,
        "maxScore": 5,
        "trustworthinessLabel": "Demo / Needs Context",
        "politicalLean": {"label": "Center / Mixed", "value": 0.0},
        "claims": [
            {
                "id": "demo-tax-1",
                "text": "We cannot bring two and a half trillion dollars back into the country because of taxes and red tape.",
                "startTime": 40.0,
                "endTime": 56.0,
                "verdict": "Demo",
                "explanation": "Hard-coded demo card. The live pipeline would check repatriated corporate earnings estimates against Treasury, CBO, and tax-policy sources.",
                "sources": [_source("Congressional Budget Office", "https://www.cbo.gov/")],
            },
            {
                "id": "demo-tax-2",
                "text": "Trickle-down economics did not work and contributed to the 2008-2009 crisis.",
                "startTime": 195.0,
                "endTime": 203.0,
                "verdict": "Demo",
                "explanation": "Hard-coded demo card. This is partly causal and partly historical, so the production system would present context rather than a one-word verdict.",
                "sources": [_source("Federal Reserve History", "https://www.federalreservehistory.org/essays/great-recession-of-200709")],
            },
            {
                "id": "demo-tax-3",
                "text": "The stock market is in a big, fat, ugly bubble.",
                "startTime": 273.0,
                "endTime": 288.0,
                "verdict": "Demo",
                "explanation": "Hard-coded demo card. Market-bubble claims require contemporaneous valuation metrics and cannot be fully resolved from the transcript alone.",
                "sources": [_source("Federal Reserve Economic Data", "https://fred.stlouisfed.org/")],
            },
            {
                "id": "demo-tax-4",
                "text": "A presidential candidate is free to release tax returns during an IRS audit.",
                "startTime": 402.0,
                "endTime": 410.0,
                "verdict": "Demo",
                "explanation": "Hard-coded demo card. The live path would cite IRS guidance and election transparency precedent.",
                "sources": [_source("Internal Revenue Service", "https://www.irs.gov/")],
            },
            {
                "id": "demo-tax-5",
                "text": "The country has 20 trillion dollars in debt.",
                "startTime": 721.0,
                "endTime": 729.0,
                "verdict": "Demo",
                "explanation": "Hard-coded demo card. The live pipeline would compare the statement date to Treasury debt-to-the-penny data.",
                "sources": [_source("U.S. Treasury Fiscal Data", "https://fiscaldata.treasury.gov/")],
            },
            {
                "id": "demo-tax-6",
                "text": "Trump businesses took bankruptcy six times.",
                "startTime": 903.0,
                "endTime": 912.0,
                "verdict": "Demo",
                "explanation": "Hard-coded demo card. The live pipeline would verify the count against court filings and reputable fact-checking archives.",
                "sources": [_source("FactCheck.org", "https://www.factcheck.org/")],
            },
        ],
        "aggregatedSources": [
            {"name": "Congressional Budget Office", "url": "https://www.cbo.gov/", "citedCount": 1},
            {"name": "Federal Reserve History", "url": "https://www.federalreservehistory.org/essays/great-recession-of-200709", "citedCount": 1},
            {"name": "Federal Reserve Economic Data", "url": "https://fred.stlouisfed.org/", "citedCount": 1},
            {"name": "Internal Revenue Service", "url": "https://www.irs.gov/", "citedCount": 1},
            {"name": "U.S. Treasury Fiscal Data", "url": "https://fiscaldata.treasury.gov/", "citedCount": 1},
            {"name": "FactCheck.org", "url": "https://www.factcheck.org/", "citedCount": 1},
        ],
        "opinions": [],
    },
}


def video_id_from_url(url: str) -> str | None:
    parsed = urlparse(url)
    host = parsed.netloc.lower()

    if "youtu.be" in host:
        return parsed.path.strip("/") or None

    if "youtube.com" in host:
        query_id = parse_qs(parsed.query).get("v", [None])[0]
        if query_id:
            return query_id
        match = re.search(r"/(?:embed|shorts)/([^/?#]+)", parsed.path)
        if match:
            return match.group(1)

    return None


def get_demo_video_id(url: str) -> str | None:
    video_id = video_id_from_url(url)
    return video_id if video_id in DEMO_VIDEO_IDS else None


def get_demo_transcript(url: str) -> list[dict[str, Any]] | None:
    video_id = get_demo_video_id(url)
    if video_id is None:
        return None
    return deepcopy(DEMO_TRANSCRIPTS[video_id])


def get_demo_response(url: str) -> AnalyzeVideoResponse | None:
    video_id = get_demo_video_id(url)
    if video_id is None:
        return None
    return AnalyzeVideoResponse(
        summary=DEMO_RESPONSES[video_id]["summary"],
        trustworthinessScore=DEMO_RESPONSES[video_id]["trustworthinessScore"],
        maxScore=DEMO_RESPONSES[video_id]["maxScore"],
        trustworthinessLabel=DEMO_RESPONSES[video_id]["trustworthinessLabel"],
        politicalLean=PoliticalLean.model_validate(
            DEMO_RESPONSES[video_id]["politicalLean"]
        ),
        claims=[
            FrontendClaim.model_validate(claim)
            for claim in DEMO_RESPONSES[video_id]["claims"]
        ],
        aggregatedSources=[
            FrontendAggregatedSource.model_validate(source)
            for source in DEMO_RESPONSES[video_id]["aggregatedSources"]
        ],
        opinions=[],
    )


def get_demo_clip_response(
    url: str,
    start_time: float,
    end_time: float,
) -> AnalyzeClipResponse | None:
    demo = get_demo_response(url)
    if demo is None:
        return None

    matching_claim = next(
        (
            claim
            for claim in demo.claims
            if claim.startTime is not None
            and claim.endTime is not None
            and claim.startTime <= end_time
            and claim.endTime >= start_time
        ),
        demo.claims[0] if demo.claims else None,
    )
    if matching_claim is None:
        return None

    return AnalyzeClipResponse(
        startTime=start_time,
        endTime=end_time,
        claim=matching_claim.text,
        verdict=matching_claim.verdict,
        explanation=matching_claim.explanation,
        sources=[
            FrontendSource(name=source.name, url=source.url)
            for source in matching_claim.sources
        ],
    )
