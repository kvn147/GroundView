"""
Immigration Agent - Retrieves information for immigration claims using OpenRouter.
"""

import os
from dotenv import load_dotenv
from openai import AsyncOpenAI
from .sources import get_sources_for_domain

# Load the environment variables from your .env file
load_dotenv()

async def retrieve_evidence(claim: str) -> str:
    """
    Uses OpenRouter to retrieve facts and context about an immigration claim. 
    Returns the gathered information in Markdown.
    """
    # Initialize the OpenAI client pointing to OpenRouter
    client = AsyncOpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.environ.get("OPENROUTER_API_KEY"),
    )
    
    sources_text = get_sources_for_domain("immigration")
    
    system_instruction = f"""
    You are an expert research assistant specializing in immigration, demographic data, and policy.
    Your ONLY job is to retrieve factual, reliable context for the given claim.
    You do NOT render a final true/false verdict.
    
    When searching your knowledge base, prioritize information from reliable sources:
    {sources_text}
    
    Instructions:
    1. Retrieve thorough facts and statistics related to the claim from your knowledge base.
    2. Synthesize the raw facts, statistics, and context you find.
    3. Output the gathered information in clear Markdown format.
    4. Mention the likely sources (like USCIS, MPI, Pew Research, etc.) for this information.
    """
    
    prompt = f"Here is the claim you need to research:\n\"{claim}\"\n\nPlease provide the gathered evidence in Markdown."
    
    try:
        # Note: We use the synchronous client here, but wrap it in an async function 
        # so it remains compatible with the router.py expectations.
        # Alternatively, you could use AsyncOpenAI for true async execution.
        response = await client.chat.completions.create(
            model="google/gemini-2.5-flash", # OpenRouter model name
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt}
            ],
            extra_headers={
                "HTTP-Referer": "http://localhost:8000",
                "X-Title": "BeaverHacks Fact-Checker",
            }
        )
        
        # Return the markdown text which will be passed down the pipeline to the Judge model
        return response.choices[0].message.content
        
    except Exception as e:
        # Fallback error handling
        return f"### Error Retrieving Evidence\nFailed to gather information for the claim. Error: {str(e)}"

# Alias to match what router.py might be calling
async def verify(claim: str) -> str:
    return await retrieve_evidence(claim)
