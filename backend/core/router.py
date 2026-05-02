from backend.agents import agent_politics, agent_science, agent_general
# Assuming you have an LLM client set up
from backend.services.gemini import classify_topic 

async def route_claim_to_agent(claim: str):
    """
    Determines the domain of the claim and routes it to the appropriate agent.
    """
    # LLM decides if this is 'immigration', 'healthcare', or 'general'
    topic = await classify_topic(claim)
    
    if topic == "healthcare":
        return await agent_healthcare.verify(claim)
    elif topic == "immigration":
        return await agent_immigration.verify(claim)
    else:
        return await agent_general.verify(claim)
