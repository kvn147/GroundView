"""
Healthcare Agent - Retrieves information for healthcare claims using OpenRouter.
"""

from .base_agent import run_domain_agent

async def retrieve_evidence(claim: str) -> str:
    """
    Uses OpenRouter to retrieve facts and context about a healthcare claim. 
    Returns the gathered information in Markdown.
    """
    return await run_domain_agent(
        domain="healthcare",
        specialty_desc="healthcare and medical data",
        source_examples="(like CDC, BLS, etc.)",
        claim=claim
    )

# Alias to match what router.py might be calling
async def verify(claim: str) -> str:
    return await retrieve_evidence(claim)
