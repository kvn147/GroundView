import json
import httpx
import os
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

DOMAINS = [
   
    "immigration",
    "healthcare",
]

DOMAIN_DESCRIPTIONS = {
    "immigration": "border, deportation, visa, asylum, migrants, ICE",
    "healthcare": "insurance, Medicare, Medicaid, hospitals, FDA",
}

ROUTER_PROMPT = """Classify this political claim into exactly one domain.

Domains:
{domain_list}

Claim: "{claim}"

Return ONLY JSON, no other text:
{{"domain": "one of the domain names above", "confidence": 0.0}}

Confidence 0.0-1.0 based on how clearly it fits."""


async def classify_claim(claim_text: str) -> tuple[str, float]:
    domain_list = "\n".join([
        f"- {d}: {DOMAIN_DESCRIPTIONS[d]}"
        for d in DOMAINS
    ])

    prompt = ROUTER_PROMPT.format(
        domain_list=domain_list,
        claim=claim_text
    )

    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "HTTP-Referer": "https://clearview.app",
                "X-Title": "ClearView",
            },
            json={
                "model": "anthropic/claude-haiku-4-5",
                "messages": [{"role": "user", "content": prompt}]
            }
        )
        r.raise_for_status()
        raw = r.json()["choices"][0]["message"]["content"]

    raw = raw.strip().replace("```json", "").replace("```", "").strip()

    try:
        result = json.loads(raw)
        domain = result.get("domain", "other")
        confidence = float(result.get("confidence", 0.5))
        if domain not in DOMAINS:
            domain = "other"
        return domain, confidence
    except (json.JSONDecodeError, ValueError):
        return "other", 0.5


def needs_fallback(confidence: float) -> bool:
    return confidence < 0.6