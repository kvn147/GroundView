import os
from dotenv import load_dotenv
from openai import AsyncOpenAI
from .sources import get_sources_for_domain

# Load the environment variables from your .env file
load_dotenv()

# Initialize the OpenAI client pointing to OpenRouter once at module level
client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.environ.get("OPENROUTER_API_KEY"),
)

async def run_domain_agent(domain: str, specialty_desc: str, source_examples: str, claim: str) -> str:
    """
    Uses OpenRouter to retrieve facts and context about a claim for a specific domain. 
    Returns the gathered information in Markdown.
    """
    sources_text = get_sources_for_domain(domain)
    
    system_instruction = f"""
    You are an expert research assistant specializing in {specialty_desc}.
    Your ONLY job is to retrieve factual, reliable context for the given claim.
    You do NOT render a final true/false verdict.
    
    When searching your knowledge base, prioritize information from reliable sources:
    {sources_text}
    
    Instructions:
    1. Retrieve thorough facts and statistics related to the claim from your knowledge base.
    2. Synthesize the raw facts, statistics, and context you find.
    3. Output the gathered information in clear Markdown format.
    4. Mention the likely sources {source_examples} for this information.
    """
    
    prompt = f"Here is the claim you need to research:\n\"{claim}\"\n\nPlease provide the gathered evidence in Markdown."
    
    try:
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
