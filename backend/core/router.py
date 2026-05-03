import json
import httpx
import os
import asyncio
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

DOMAINS = [
    "economic",
    "immigration",
    "crime",
    "healthcare",
    "foreign_policy",
    "education",
    "environment",
    "other",
]

DOMAIN_DESCRIPTIONS = {
    "economic": (
        "unemployment rate, job creation, GDP growth, wage increases, "
        "inflation, trade deficits, tariffs, federal budget, national debt, "
        "stock market, tax cuts, economic growth, manufacturing jobs"
    ),
    "immigration": (
        "border crossings, illegal immigration, deportations, asylum seekers, "
        "visa programs, ICE enforcement, border wall, migrant encounters, "
        "green cards, citizenship, sanctuary cities, DACA"
    ),
    "crime": (
        "violent crime rates, murder rates, drug seizures, fentanyl, "
        "police funding, incarceration rates, FBI crime statistics, "
        "drug trafficking, gang activity, law enforcement"
    ),
    "healthcare": (
        "health insurance coverage, Medicare, Medicaid, Affordable Care Act, "
        "drug prices, hospital costs, uninsured rates, prescription drugs, "
        "FDA approvals, life expectancy, infant mortality"
    ),
    "foreign_policy": (
        "military deployments, foreign aid, NATO, trade agreements, "
        "sanctions, diplomatic relations, wars, defense spending, "
        "nuclear deals, international treaties, allies"
    ),
    "education": (
        "student loan debt, graduation rates, school funding, "
        "teacher salaries, college tuition, standardized test scores, "
        "literacy rates, university enrollment, K-12 spending"
    ),
    "environment": (
        "carbon emissions, climate change, renewable energy, "
        "oil and gas production, EPA regulations, clean energy jobs, "
        "Paris Agreement, pollution levels, wildfire statistics, "
        "energy independence"
    ),
    "other": (
        "biographical claims, personal history, any claim that does "
        "not clearly fit the above domains"
    ),
}

ROUTER_MODELS = [
    "anthropic/claude-haiku-4-5",
    "google/gemini-flash-1.5",
    "meta-llama/llama-3.1-8b-instruct",
]

ROUTER_PROMPT = """Classify this political claim into exactly one domain.

Domains:
{domain_list}

Examples:
- "we were energy independent" → environment
- "we had the lowest taxes ever" → economic
- "we had the lowest regulations ever" → economic
- "the border had very few crossings" → immigration
- "GDP grew 2.4 percent last quarter" → economic
- "we created 6 million jobs" → economic
- "unemployment is at a 50 year low" → economic
- "we seized more fentanyl than ever" → crime
- "we passed the largest healthcare bill" → healthcare
- "we withdrew troops from Afghanistan" → foreign_policy
- "graduation rates hit an all time high" → education
- "carbon emissions dropped 20 percent" → environment
- "I was the youngest person elected to Senate" → other
- "I served in the military for 30 years" → other

Claim: "{claim}"

Return ONLY JSON, no other text:
{{"domain": "one of the domain names above", "confidence": 0.0}}

Confidence 0.0-1.0 based on how clearly it fits.
If the claim is biographical or doesn't fit any domain clearly, use "other" with low confidence."""


async def _classify_with_model(
    claim_text: str,
    model: str,
    domain_list: str
) -> tuple[str, float]:
    prompt = ROUTER_PROMPT.format(
        domain_list=domain_list,
        claim=claim_text
    )
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "HTTP-Referer": "https://clearview.app",
                    "X-Title": "ClearView",
                },
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}]
                }
            )
            r.raise_for_status()
            raw = r.json()["choices"][0]["message"]["content"]
            raw = raw.strip().replace("```json", "").replace("```", "").strip()
            result = json.loads(raw)
            domain = result.get("domain", "other")
            confidence = float(result.get("confidence", 0.5))
            if domain not in DOMAINS:
                domain = "other"
            return domain, confidence
    except Exception:
        return "other", 0.5


async def classify_claim(claim_text: str) -> tuple[str, float]:
    domain_list = "\n".join([
        f"- {d}: {DOMAIN_DESCRIPTIONS[d]}"
        for d in DOMAINS
    ])

    results = await asyncio.gather(*[
        _classify_with_model(claim_text, model, domain_list)
        for model in ROUTER_MODELS
    ])

    domain_votes: dict[str, list[float]] = {}
    for domain, confidence in results:
        if domain not in domain_votes:
            domain_votes[domain] = []
        domain_votes[domain].append(confidence)

    winner = max(
        domain_votes.items(),
        key=lambda x: (len(x[1]), sum(x[1]) / len(x[1]))
    )

    winning_domain = winner[0]
    avg_confidence = sum(winner[1]) / len(winner[1])

    if avg_confidence < 0.3:
        winning_domain = "other"

    print(f"  votes: {[(d, f'{sum(c)/len(c):.0%}') for d, c in domain_votes.items()]}")

    return winning_domain, avg_confidence


def needs_fallback(confidence: float) -> bool:
    return confidence < 0.6