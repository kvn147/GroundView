"""
Economy Agent - Retrieves information for economy claims using OpenRouter.
"""

from .base_agent import run_domain_agent

async def retrieve_evidence(claim: str) -> str:
    """
    Uses OpenRouter to retrieve facts and context about an economy claim. 
    Returns the gathered information in Markdown.
    """
    return await run_domain_agent(
        domain="economy",
        specialty_desc="economy, demographic data, and policy",
        source_examples="(like BLS, FRED, Census Bureau, Pew Research, etc.)",
        claim=claim
    )

# Alias to match what router.py might be calling
async def verify(claim: str) -> str:
    return await retrieve_evidence(claim)
