from fastapi import APIRouter
from pydantic import BaseModel
from typing import List, Optional

from backend.core.transcript import get_transcript
from backend.core.extract import extract_claims
from backend.core.router import classify_claim
from backend.agents.agent_crime import retrieve_evidence as verify_crime
from backend.agents.agent_economy import retrieve_evidence as verify_economy
from backend.agents.agent_education import retrieve_evidence as verify_education
from backend.agents.agent_healthcare import retrieve_evidence as verify_healthcare
from backend.agents.agent_immigration import retrieve_evidence as verify_immigration

api_router = APIRouter()

class PoliticalCheckRequest(BaseModel):
    title: Optional[str] = ""
    description: Optional[str] = ""
    tags: Optional[str] = ""
    aiDescription: Optional[str] = ""

class AnalyzeVideoRequest(BaseModel):
    url: str

class AnalyzeClipRequest(BaseModel):
    url: str
    startTime: float
    endTime: float
    captions: Optional[str] = ""

@api_router.post("/check-political")
async def check_political(req: PoliticalCheckRequest):
    # Mock implementation for now, always return true to let the video proceed
    return {"isPolitical": True}

@api_router.post("/analyze-video")
async def analyze_video(req: AnalyzeVideoRequest):
    chunks = await get_transcript(req.url)
    
    claims_data = []
    
    # Process up to a certain number of chunks for MVP so it doesn't timeout
    for chunk in chunks[:5]:
        extracted = await extract_claims(chunk["text"], chunk["timestamp"])
        for claim_info in extracted:
            claim_text = claim_info["claim"]
            domain, confidence = await classify_claim(claim_text)
            
            evidence = "No evidence retrieved."
            if domain == "crime":
                evidence = await verify_crime(claim_text)
            elif domain == "economy":
                evidence = await verify_economy(claim_text)
            elif domain == "education":
                evidence = await verify_education(claim_text)
            elif domain == "healthcare":
                evidence = await verify_healthcare(claim_text)
            elif domain == "immigration":
                evidence = await verify_immigration(claim_text)
                
            claims_data.append({
                "id": f"claim-{len(claims_data)+1}",
                "text": claim_text,
                "verdict": domain.capitalize() if domain != "other" else "Mixed",
                "explanation": evidence,
                "sources": []
            })
            
    # Construct the final synchronous object expected by the frontend mock.js
    return {
        "summary": "This video contains several political claims with mixed accuracy. Some statistics cited are outdated or lack proper context.",
        "trustworthinessScore": 3,
        "maxScore": 5,
        "trustworthinessLabel": "Mixed Accuracy",
        "politicalLean": {
            "label": "Unknown",
            "value": 0.5
        },
        "claims": claims_data,
        "aggregatedSources": []
    }

@api_router.post("/analyze-clip")
async def analyze_clip(req: AnalyzeClipRequest):
    # Simple fallback that processes just one text chunk if provided, or mocks it
    return {
        "startTime": req.startTime,
        "endTime": req.endTime,
        "claim": "Manual clip analysis.",
        "verdict": "Pending",
        "explanation": "Clip analysis backend logic will process specific timestamps here.",
        "sources": []
    }
