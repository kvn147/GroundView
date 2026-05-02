from fastapi import APIRouter, WebSocket
from backend.core.router import route_claim_to_agent

api_router = APIRouter()

@api_router.post("/process-video")
async def process_video(youtube_url: str):
    # 1. Trigger transcript extraction
    # 2. Extract claims
    # 3. Return a job ID so the frontend can listen for results
    return {"status": "processing", "job_id": "12345"}

@api_router.websocket("/ws/claims/{job_id}")
async def websocket_endpoint(websocket: WebSocket, job_id: str):
    await websocket.accept()
    # Stream verified claims back to the frontend as the agents finish them
    # await websocket.send_json({"time": "0:45", "claim": "...", "context": "..."})
