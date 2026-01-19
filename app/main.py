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
from .models import Match, MatchDay
from .schemas import MatchCreate, ScorePoint, MatchResponse, MatchDayCreate, ScoreGame
from .scoring import score_point, score_game, create_initial_state, get_score_summary


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


@app.post("/api/matches/{match_id}/game")
async def score_game_endpoint(match_id: str, score_data: ScoreGame, db: AsyncSession = Depends(get_db)):
    """Score a whole game for the given team."""
    result = await db.execute(select(Match).where(Match.id == match_id))
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    if match.score_state.get("winner") is not None:
        raise HTTPException(status_code=400, detail="Match is already finished")

    if match.score_state.get("is_tiebreak") or match.score_state.get("is_super_tiebreak"):
        raise HTTPException(status_code=400, detail="Cannot score whole game during tiebreak")

    # Save current state to history for undo
    history = match.history.copy() if match.history else []
    history.append(match.score_state.copy())
    if len(history) > 50:
        history = history[-50:]

    # Calculate new state
    new_state = score_game(
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


# Match Day routes
@app.get("/matchday/new", response_class=HTMLResponse)
async def new_match_day_page(request: Request):
    return templates.TemplateResponse("matchday_setup.html", {"request": request})


@app.get("/matchday/{match_day_id}", response_class=HTMLResponse)
async def match_day_page(request: Request, match_day_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(MatchDay).where(MatchDay.id == match_day_id))
    match_day = result.scalar_one_or_none()
    if not match_day:
        raise HTTPException(status_code=404, detail="Match day not found")

    # Get all matches for this match day
    matches_result = await db.execute(
        select(Match).where(Match.match_day_id == match_day_id).order_by(Match.match_number)
    )
    matches = [m.to_dict() for m in matches_result.scalars().all()]

    return templates.TemplateResponse("matchday.html", {
        "request": request,
        "match_day": match_day.to_dict(),
        "matches": matches
    })


@app.post("/api/matchdays")
async def create_match_day(data: MatchDayCreate, db: AsyncSession = Depends(get_db)):
    """Create a match day with all matches."""
    match_day = MatchDay(
        name=data.name,
        format=data.format,
        players=data.players,
        team_a_name=data.team_a_name,
        team_b_name=data.team_b_name,
        team_a_players=data.team_a_players,
        team_b_players=data.team_b_players,
    )
    db.add(match_day)
    await db.flush()

    # Generate matches based on format
    matches = []
    match_number = 1

    if data.format == "6_person":
        # 6 singles + 3 doubles
        # Singles: each player plays 2 singles matches
        team_a = data.team_a_players[:3]
        team_b = data.team_b_players[:3]

        # Generate 6 singles: A1vB1, A2vB2, A3vB3, A1vB2, A2vB3, A3vB1
        singles_pairings = [
            (0, 0), (1, 1), (2, 2), (0, 1), (1, 2), (2, 0)
        ]
        for i, (a_idx, b_idx) in enumerate(singles_pairings):
            match = Match(
                match_day_id=match_day.id,
                match_number=match_number,
                match_type="singles",
                team_a_name=data.team_a_name,
                team_b_name=data.team_b_name,
                player_a1=team_a[a_idx] if a_idx < len(team_a) else f"Player A{a_idx+1}",
                player_b1=team_b[b_idx] if b_idx < len(team_b) else f"Player B{b_idx+1}",
                score_state=create_initial_state(),
                history=[]
            )
            db.add(match)
            matches.append(match)
            match_number += 1

        # 3 doubles
        doubles_pairings = [
            ((0, 1), (0, 1)), ((0, 2), (0, 2)), ((1, 2), (1, 2))
        ]
        for (a1, a2), (b1, b2) in doubles_pairings:
            match = Match(
                match_day_id=match_day.id,
                match_number=match_number,
                match_type="doubles",
                team_a_name=data.team_a_name,
                team_b_name=data.team_b_name,
                player_a1=team_a[a1] if a1 < len(team_a) else f"Player A{a1+1}",
                player_a2=team_a[a2] if a2 < len(team_a) else f"Player A{a2+1}",
                player_b1=team_b[b1] if b1 < len(team_b) else f"Player B{b1+1}",
                player_b2=team_b[b2] if b2 < len(team_b) else f"Player B{b2+1}",
                score_state=create_initial_state(),
                history=[]
            )
            db.add(match)
            matches.append(match)
            match_number += 1

    else:  # 4_person
        # 4 singles + 4 doubles
        team_a = data.team_a_players[:2]
        team_b = data.team_b_players[:2]

        # 4 singles: each player plays 2
        singles_pairings = [(0, 0), (0, 1), (1, 0), (1, 1)]
        for a_idx, b_idx in singles_pairings:
            match = Match(
                match_day_id=match_day.id,
                match_number=match_number,
                match_type="singles",
                team_a_name=data.team_a_name,
                team_b_name=data.team_b_name,
                player_a1=team_a[a_idx] if a_idx < len(team_a) else f"Player A{a_idx+1}",
                player_b1=team_b[b_idx] if b_idx < len(team_b) else f"Player B{b_idx+1}",
                score_state=create_initial_state(),
                history=[]
            )
            db.add(match)
            matches.append(match)
            match_number += 1

        # 4 doubles (playing 4 times with same pairing or mixed)
        for i in range(4):
            match = Match(
                match_day_id=match_day.id,
                match_number=match_number,
                match_type="doubles",
                team_a_name=data.team_a_name,
                team_b_name=data.team_b_name,
                player_a1=team_a[0] if len(team_a) > 0 else "Player A1",
                player_a2=team_a[1] if len(team_a) > 1 else "Player A2",
                player_b1=team_b[0] if len(team_b) > 0 else "Player B1",
                player_b2=team_b[1] if len(team_b) > 1 else "Player B2",
                score_state=create_initial_state(),
                history=[]
            )
            db.add(match)
            matches.append(match)
            match_number += 1

    await db.commit()
    await db.refresh(match_day)

    return {
        "success": True,
        "match_day": match_day.to_dict(),
        "matches": [m.to_dict() for m in matches]
    }


@app.get("/api/matchdays/{match_day_id}")
async def get_match_day(match_day_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(MatchDay).where(MatchDay.id == match_day_id))
    match_day = result.scalar_one_or_none()
    if not match_day:
        raise HTTPException(status_code=404, detail="Match day not found")

    matches_result = await db.execute(
        select(Match).where(Match.match_day_id == match_day_id).order_by(Match.match_number)
    )
    matches = [m.to_dict() for m in matches_result.scalars().all()]

    return {
        "match_day": match_day.to_dict(),
        "matches": matches
    }


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
