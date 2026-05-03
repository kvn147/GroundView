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
from backend.agents.judge import extract_evidence_items, calculate_confidence

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
                
            # Judge verification
            evidence_items = await extract_evidence_items(evidence)
            judge_result = await calculate_confidence(claim_text, evidence_items)
            
            claims_data.append({
                "id": f"claim-{len(claims_data)+1}",
                "text": claim_text,
                "verdict": judge_result.get("verdict", "Unverified"),
                "explanation": f"{evidence}\n\n**Fact-Checker Warning:** {judge_result.get('warning')}" if judge_result.get("warning") else evidence,
                "sources": [{"name": item.get("source", "Unknown"), "url": "#"} for item in evidence_items],
                "_score": judge_result.get("final_score", 0.0),
                "_bias": judge_result.get("average_bias", 0.0)
            })
            
    # Calculate video-level aggregations
    num_claims = len(claims_data)
    if num_claims > 0:
        avg_score = sum(c["_score"] for c in claims_data) / num_claims
        avg_bias = sum(c["_bias"] for c in claims_data) / num_claims
    else:
        avg_score = 0.0
        avg_bias = 0.0
        
    # Map final_score (-1.0 to 1.0) to a 1-5 scale
    trust_score = round(((avg_score + 1) / 2) * 4) + 1
    trust_score = max(1, min(5, trust_score))
    
    trust_labels = {
        1: "Mostly False",
        2: "Mixed / Leans False",
        3: "Mixed Accuracy / Needs Context",
        4: "Mostly True",
        5: "Highly Accurate"
    }
    trust_label = trust_labels[trust_score]
    
    # Map average bias to political lean label
    if avg_bias < -0.3:
        lean_label = "Leans Left"
    elif avg_bias > 0.3:
        lean_label = "Leans Right"
    else:
        lean_label = "Center / Neutral"
        
    lean_value = (avg_bias + 1) / 2  # Map -1.0..1.0 to 0.0..1.0 for the UI progress bar
    
    # Aggregate sources
    agg_sources_map = {}
    for c in claims_data:
        for s in c["sources"]:
            name = s["name"]
            if name not in agg_sources_map:
                agg_sources_map[name] = {"name": name, "url": s["url"], "citedCount": 0}
            agg_sources_map[name]["citedCount"] += 1
            
    # Clean up internal keys
    for c in claims_data:
        c.pop("_score", None)
        c.pop("_bias", None)

    summary = (
        f"Analyzed {num_claims} claims. Overall video reliability is {trust_label} "
        f"with a {lean_label.lower()} sourcing bias."
    ) if num_claims > 0 else "No verifiable political claims were extracted from this video."

    # Construct the final synchronous object expected by the frontend mock.js
    return {
        "summary": summary,
        "trustworthinessScore": trust_score,
        "maxScore": 5,
        "trustworthinessLabel": trust_label,
        "politicalLean": {
            "label": lean_label,
            "value": round(lean_value, 2)
        },
        "claims": claims_data,
        "aggregatedSources": list(agg_sources_map.values())
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
