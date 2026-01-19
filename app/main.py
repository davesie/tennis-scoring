from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Dict, List, Set
import json
from datetime import datetime
from contextlib import asynccontextmanager

from .database import get_db, init_db
from .models import Match
from .schemas import MatchCreate, ScorePoint, MatchResponse
from .scoring import score_point, create_initial_state, get_score_summary


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="Tennis Scoring", lifespan=lifespan)

# Mount static files and templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


# WebSocket connection manager
class ConnectionManager:
    def __init__(self):
        # match_id -> set of websocket connections
        self.active_connections: Dict[str, Set[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, match_id: str):
        await websocket.accept()
        if match_id not in self.active_connections:
            self.active_connections[match_id] = set()
        self.active_connections[match_id].add(websocket)

    def disconnect(self, websocket: WebSocket, match_id: str):
        if match_id in self.active_connections:
            self.active_connections[match_id].discard(websocket)
            if not self.active_connections[match_id]:
                del self.active_connections[match_id]

    async def broadcast(self, match_id: str, message: dict):
        if match_id in self.active_connections:
            dead_connections = set()
            for connection in self.active_connections[match_id]:
                try:
                    await connection.send_json(message)
                except Exception:
                    dead_connections.add(connection)
            # Clean up dead connections
            for conn in dead_connections:
                self.active_connections[match_id].discard(conn)


manager = ConnectionManager()


# Page routes
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/match/{match_id}", response_class=HTMLResponse)
async def match_page(request: Request, match_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Match).where(Match.id == match_id))
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    return templates.TemplateResponse("match.html", {
        "request": request,
        "match": match.to_dict(),
        "is_scorer": True
    })


@app.get("/watch/{share_code}", response_class=HTMLResponse)
async def spectator_page(request: Request, share_code: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Match).where(Match.share_code == share_code))
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    return templates.TemplateResponse("match.html", {
        "request": request,
        "match": match.to_dict(),
        "is_scorer": False
    })


# API routes
@app.post("/api/matches", response_model=MatchResponse)
async def create_match(match_data: MatchCreate, db: AsyncSession = Depends(get_db)):
    match = Match(
        match_type=match_data.match_type,
        team_a_name=match_data.team_a_name,
        team_b_name=match_data.team_b_name,
        player_a1=match_data.player_a1,
        player_b1=match_data.player_b1,
        player_a2=match_data.player_a2,
        player_b2=match_data.player_b2,
        best_of=match_data.best_of,
        super_tiebreak_final_set=match_data.super_tiebreak_final_set,
        score_state=create_initial_state(),
        history=[]
    )
    db.add(match)
    await db.commit()
    await db.refresh(match)
    return match


@app.get("/api/matches/{match_id}", response_model=MatchResponse)
async def get_match(match_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Match).where(Match.id == match_id))
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    return match


@app.get("/api/matches/share/{share_code}", response_model=MatchResponse)
async def get_match_by_share_code(share_code: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Match).where(Match.share_code == share_code))
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    return match


@app.post("/api/matches/{match_id}/score")
async def score(match_id: str, score_data: ScorePoint, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Match).where(Match.id == match_id))
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    if match.score_state.get("winner") is not None:
        raise HTTPException(status_code=400, detail="Match is already finished")

    # Save current state to history for undo
    history = match.history.copy() if match.history else []
    history.append(match.score_state.copy())
    # Keep only last 50 states to prevent excessive storage
    if len(history) > 50:
        history = history[-50:]

    # Calculate new state
    new_state = score_point(
        match.score_state,
        score_data.team,
        match.super_tiebreak_final_set
    )

    # Update match
    match.score_state = new_state
    match.history = history
    match.updated_at = datetime.utcnow()

    if new_state.get("winner") is not None:
        match.finished_at = datetime.utcnow()

    await db.commit()
    await db.refresh(match)

    # Broadcast update to all connected clients
    await manager.broadcast(match_id, {
        "type": "score_update",
        "match": match.to_dict(),
        "summary": get_score_summary(new_state)
    })

    return {"success": True, "match": match.to_dict()}


@app.post("/api/matches/{match_id}/undo")
async def undo(match_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Match).where(Match.id == match_id))
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    history = match.history.copy() if match.history else []
    if not history:
        raise HTTPException(status_code=400, detail="No history to undo")

    # Restore previous state
    previous_state = history.pop()
    match.score_state = previous_state
    match.history = history
    match.updated_at = datetime.utcnow()
    match.finished_at = None  # Clear finished status on undo

    await db.commit()
    await db.refresh(match)

    # Broadcast update
    await manager.broadcast(match_id, {
        "type": "score_update",
        "match": match.to_dict(),
        "summary": get_score_summary(previous_state)
    })

    return {"success": True, "match": match.to_dict()}


@app.post("/api/matches/{match_id}/reset")
async def reset_match(match_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Match).where(Match.id == match_id))
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    match.score_state = create_initial_state()
    match.history = []
    match.updated_at = datetime.utcnow()
    match.finished_at = None

    await db.commit()
    await db.refresh(match)

    # Broadcast update
    await manager.broadcast(match_id, {
        "type": "score_update",
        "match": match.to_dict(),
        "summary": get_score_summary(match.score_state)
    })

    return {"success": True, "match": match.to_dict()}


# WebSocket endpoint for real-time updates
@app.websocket("/ws/{match_id}")
async def websocket_endpoint(websocket: WebSocket, match_id: str, db: AsyncSession = Depends(get_db)):
    # Verify match exists
    result = await db.execute(select(Match).where(Match.id == match_id))
    match = result.scalar_one_or_none()
    if not match:
        await websocket.close(code=4004, reason="Match not found")
        return

    await manager.connect(websocket, match_id)
    try:
        # Send initial state
        await websocket.send_json({
            "type": "initial",
            "match": match.to_dict(),
            "summary": get_score_summary(match.score_state)
        })

        # Keep connection alive and handle any client messages
        while True:
            try:
                data = await websocket.receive_text()
                # Could handle client commands here if needed
            except WebSocketDisconnect:
                break
    finally:
        manager.disconnect(websocket, match_id)
