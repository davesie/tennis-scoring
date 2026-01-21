from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, Request, Form
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
from .models import Match, MatchDay, AdminSession
from .schemas import MatchCreate, ScorePoint, MatchResponse, MatchDayCreate, ScoreGame, MatchPlayersUpdate, MatchScoreSet
from .scoring import score_point, score_game, create_initial_state, get_score_summary
from .auth import (
    ADMIN_PASSWORD,
    ADMIN_SESSION_COOKIE,
    verify_admin_password,
    create_admin_session,
    get_admin_session,
    delete_admin_session,
    get_scorer_token,
    verify_scorer_for_match,
)


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
async def home(request: Request, db: AsyncSession = Depends(get_db)):
    """Home page - redirects to admin login if not authenticated."""
    admin_session = await get_admin_session(request, db)
    if not admin_session:
        return RedirectResponse(url="/admin/login", status_code=302)
    return RedirectResponse(url="/admin", status_code=302)


# Admin routes
@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page(request: Request, db: AsyncSession = Depends(get_db)):
    """Show admin login page."""
    # If already logged in, redirect to dashboard
    admin_session = await get_admin_session(request, db)
    if admin_session:
        return RedirectResponse(url="/admin", status_code=302)

    return templates.TemplateResponse("admin_login.html", {"request": request})


@app.post("/admin/login")
async def admin_login(
    request: Request,
    password: str = Form(...),
    db: AsyncSession = Depends(get_db)
):
    """Process admin login."""
    if not verify_admin_password(password):
        return templates.TemplateResponse("admin_login.html", {
            "request": request,
            "error": "Invalid password"
        })

    # Create session
    session = await create_admin_session(db)

    # Set cookie and redirect (303 See Other for POST-redirect-GET pattern)
    response = RedirectResponse(url="/admin", status_code=303)
    response.set_cookie(
        key=ADMIN_SESSION_COOKIE,
        value=session.id,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        max_age=7 * 24 * 60 * 60  # 7 days
    )
    return response


@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    """Admin dashboard - main control panel."""
    admin_session = await get_admin_session(request, db)
    if not admin_session:
        return RedirectResponse(url="/admin/login", status_code=302)

    # Get all match days
    result = await db.execute(
        select(MatchDay).order_by(MatchDay.created_at.desc())
    )
    match_days = result.scalars().all()

    # Build data with match counts
    match_days_data = []
    for md in match_days:
        matches_result = await db.execute(
            select(Match).where(Match.match_day_id == md.id)
        )
        matches = matches_result.scalars().all()

        team_a_wins = sum(1 for m in matches if m.score_state.get("winner") == 0)
        team_b_wins = sum(1 for m in matches if m.score_state.get("winner") == 1)
        total_matches = len(matches)
        completed_matches = sum(1 for m in matches if m.score_state.get("winner") is not None)

        match_days_data.append({
            **md.to_dict(),
            "team_a_wins": team_a_wins,
            "team_b_wins": team_b_wins,
            "total_matches": total_matches,
            "completed_matches": completed_matches,
        })

    return templates.TemplateResponse("admin.html", {
        "request": request,
        "match_days": match_days_data
    })


@app.post("/admin/logout")
async def admin_logout(request: Request, db: AsyncSession = Depends(get_db)):
    """Log out admin user."""
    session_id = request.cookies.get(ADMIN_SESSION_COOKIE)
    if session_id:
        await delete_admin_session(session_id, db)

    response = RedirectResponse(url="/admin/login", status_code=303)
    response.delete_cookie(key=ADMIN_SESSION_COOKIE)
    return response


@app.get("/match/{match_id}", response_class=HTMLResponse)
async def match_page(request: Request, match_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Match).where(Match.id == match_id))
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    # Check if user is admin
    admin_session = await get_admin_session(request, db)

    # Get match day info if part of a match day
    match_day_share_code = None
    match_day_scorer_token = None
    if match.match_day_id:
        md_result = await db.execute(select(MatchDay).where(MatchDay.id == match.match_day_id))
        match_day = md_result.scalar_one_or_none()
        if match_day:
            match_day_share_code = match_day.share_code
            match_day_scorer_token = match_day.scorer_token

    # Determine scorer token to use for API calls
    # Priority: 1. Match day token (if part of match day), 2. Match's own token
    # Only provide token if user is admin (otherwise they should have it in sessionStorage)
    scorer_token = None
    if admin_session:
        scorer_token = match_day_scorer_token or match.scorer_token

    return templates.TemplateResponse("match.html", {
        "request": request,
        "match": match.to_dict(),
        "is_scorer": True,
        "match_day_share_code": match_day_share_code,
        "scorer_token": scorer_token
    })


@app.get("/watch/{share_code}", response_class=HTMLResponse)
async def spectator_page(request: Request, share_code: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Match).where(Match.share_code == share_code))
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    # Get match day share code if part of a match day
    match_day_share_code = None
    if match.match_day_id:
        md_result = await db.execute(select(MatchDay).where(MatchDay.id == match.match_day_id))
        match_day = md_result.scalar_one_or_none()
        if match_day:
            match_day_share_code = match_day.share_code

    return templates.TemplateResponse("match.html", {
        "request": request,
        "match": match.to_dict(),
        "is_scorer": False,
        "match_day_share_code": match_day_share_code
    })


# API routes
@app.post("/api/matches", response_model=MatchResponse)
async def create_match(match_data: MatchCreate, request: Request, db: AsyncSession = Depends(get_db)):
    """Create a single match. Requires admin authentication."""
    # Verify admin authentication
    admin_session = await get_admin_session(request, db)
    if not admin_session:
        raise HTTPException(status_code=401, detail="Admin authentication required")

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
async def score(match_id: str, score_data: ScorePoint, request: Request, db: AsyncSession = Depends(get_db)):
    # Verify scorer authorization
    match = await verify_scorer_for_match(match_id, request, db)

    if match.score_state.get("winner") is not None:
        raise HTTPException(status_code=400, detail="Match is already finished")

    # Set started_at on first point (when history is empty)
    if not match.started_at and not match.history:
        match.started_at = datetime.utcnow()

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
async def undo(match_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    # Verify scorer authorization
    match = await verify_scorer_for_match(match_id, request, db)

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
async def reset_match(match_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    # Verify scorer authorization
    match = await verify_scorer_for_match(match_id, request, db)

    match.score_state = create_initial_state()
    match.history = []
    match.updated_at = datetime.utcnow()
    match.started_at = None
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


@app.patch("/api/matches/{match_id}/players")
async def update_match_players(match_id: str, data: MatchPlayersUpdate, request: Request, db: AsyncSession = Depends(get_db)):
    """Update player assignments for a match (typically for setting doubles pairings)."""
    # Verify scorer authorization
    match = await verify_scorer_for_match(match_id, request, db)

    # Update player fields if provided
    if data.player_a1 is not None:
        match.player_a1 = data.player_a1
    if data.player_a2 is not None:
        match.player_a2 = data.player_a2
    if data.player_b1 is not None:
        match.player_b1 = data.player_b1
    if data.player_b2 is not None:
        match.player_b2 = data.player_b2

    match.updated_at = datetime.utcnow()

    await db.commit()
    await db.refresh(match)

    return {"success": True, "match": match.to_dict()}


@app.patch("/api/matches/{match_id}/score")
async def set_match_score(match_id: str, data: MatchScoreSet, request: Request, db: AsyncSession = Depends(get_db)):
    """Set the final score directly for a match that wasn't watched live."""
    # Verify scorer authorization
    match = await verify_scorer_for_match(match_id, request, db)

    # Validate winner
    if data.winner not in [0, 1]:
        raise HTTPException(status_code=400, detail="Winner must be 0 or 1")

    # Calculate sets won
    sets_a = sum(1 for s in data.sets if s[0] > s[1])
    sets_b = sum(1 for s in data.sets if s[1] > s[0])

    # Build the games array (pad to 3 sets)
    games = [[0, 0], [0, 0], [0, 0]]
    for i, s in enumerate(data.sets[:3]):
        games[i] = s

    # Update score state
    new_state = create_initial_state()
    new_state["games"] = games
    new_state["sets"] = [sets_a, sets_b]
    new_state["current_set"] = len(data.sets) - 1
    new_state["winner"] = data.winner
    new_state["points"] = [0, 0]

    match.score_state = new_state
    match.updated_at = datetime.utcnow()
    match.finished_at = datetime.utcnow()

    await db.commit()
    await db.refresh(match)

    # Broadcast update
    await manager.broadcast(match_id, {
        "type": "score_update",
        "match": match.to_dict(),
        "summary": get_score_summary(new_state)
    })

    return {"success": True, "match": match.to_dict()}


@app.post("/api/matches/{match_id}/game")
async def score_game_endpoint(match_id: str, score_data: ScoreGame, request: Request, db: AsyncSession = Depends(get_db)):
    """Score a whole game for the given team."""
    # Verify scorer authorization
    match = await verify_scorer_for_match(match_id, request, db)

    if match.score_state.get("winner") is not None:
        raise HTTPException(status_code=400, detail="Match is already finished")

    if match.score_state.get("is_tiebreak") or match.score_state.get("is_super_tiebreak"):
        raise HTTPException(status_code=400, detail="Cannot score whole game during tiebreak")

    # Set started_at on first action (when history is empty)
    if not match.started_at and not match.history:
        match.started_at = datetime.utcnow()

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
    """Redirect to admin dashboard for match day creation."""
    return RedirectResponse(url="/admin", status_code=302)


@app.get("/archive", response_class=HTMLResponse)
async def archive_page(request: Request, db: AsyncSession = Depends(get_db)):
    """Display archive of all match days."""
    result = await db.execute(
        select(MatchDay).order_by(MatchDay.created_at.desc())
    )
    match_days = result.scalars().all()

    # Build archive data
    archive = []
    for md in match_days:
        matches_result = await db.execute(
            select(Match).where(Match.match_day_id == md.id)
        )
        matches = matches_result.scalars().all()

        team_a_wins = sum(1 for m in matches if m.score_state.get("winner") == 0)
        team_b_wins = sum(1 for m in matches if m.score_state.get("winner") == 1)
        total_matches = len(matches)
        completed_matches = sum(1 for m in matches if m.score_state.get("winner") is not None)

        archive.append({
            **md.to_dict(),
            "team_a_wins": team_a_wins,
            "team_b_wins": team_b_wins,
            "total_matches": total_matches,
            "completed_matches": completed_matches,
        })

    return templates.TemplateResponse("archive.html", {
        "request": request,
        "match_days": archive
    })


@app.get("/matchday/{match_day_id}", response_class=HTMLResponse)
async def match_day_page(request: Request, match_day_id: str, db: AsyncSession = Depends(get_db)):
    # Require admin authentication for direct match day access
    admin_session = await get_admin_session(request, db)
    if not admin_session:
        return RedirectResponse(url="/admin/login", status_code=302)

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
        "matches": matches,
        "is_scorer": True
    })


@app.get("/watchday/{share_code}", response_class=HTMLResponse)
async def spectator_match_day_page(request: Request, share_code: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(MatchDay).where(MatchDay.share_code == share_code))
    match_day = result.scalar_one_or_none()
    if not match_day:
        raise HTTPException(status_code=404, detail="Match day not found")

    # Get all matches for this match day
    matches_result = await db.execute(
        select(Match).where(Match.match_day_id == match_day.id).order_by(Match.match_number)
    )
    matches = [m.to_dict() for m in matches_result.scalars().all()]

    return templates.TemplateResponse("matchday.html", {
        "request": request,
        "match_day": match_day.to_dict(),
        "matches": matches,
        "is_scorer": False
    })


@app.get("/scoreday/{scorer_token}", response_class=HTMLResponse)
async def scorer_match_day_page(request: Request, scorer_token: str, db: AsyncSession = Depends(get_db)):
    """Access match day with scorer permissions using a shareable token."""
    result = await db.execute(select(MatchDay).where(MatchDay.scorer_token == scorer_token))
    match_day = result.scalar_one_or_none()
    if not match_day:
        raise HTTPException(status_code=404, detail="Invalid scorer token")

    # Get all matches for this match day
    matches_result = await db.execute(
        select(Match).where(Match.match_day_id == match_day.id).order_by(Match.match_number)
    )
    matches = [m.to_dict() for m in matches_result.scalars().all()]

    return templates.TemplateResponse("matchday.html", {
        "request": request,
        "match_day": match_day.to_dict(),
        "matches": matches,
        "is_scorer": True
    })


@app.post("/api/matchdays")
async def create_match_day(data: MatchDayCreate, request: Request, db: AsyncSession = Depends(get_db)):
    """Create a match day with all matches. Requires admin authentication."""
    # Verify admin authentication
    admin_session = await get_admin_session(request, db)
    if not admin_session:
        raise HTTPException(status_code=401, detail="Admin authentication required")

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
        # 6 singles + 3 doubles (6 players per team)
        team_a = data.team_a_players[:6]
        team_b = data.team_b_players[:6]

        # 6 singles: Player 1 vs Player 1, Player 2 vs Player 2, etc.
        for i in range(6):
            match = Match(
                match_day_id=match_day.id,
                match_number=match_number,
                match_type="singles",
                team_a_name=data.team_a_name,
                team_b_name=data.team_b_name,
                player_a1=team_a[i] if i < len(team_a) else f"Player A{i+1}",
                player_b1=team_b[i] if i < len(team_b) else f"Player B{i+1}",
                score_state=create_initial_state(),
                history=[]
            )
            db.add(match)
            matches.append(match)
            match_number += 1

        # 3 doubles: (1,2) vs (1,2), (3,4) vs (3,4), (5,6) vs (5,6)
        doubles_pairings = [
            ((0, 1), (0, 1)), ((2, 3), (2, 3)), ((4, 5), (4, 5))
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
        # 4 singles + 2 doubles (4 players per team)
        team_a = data.team_a_players[:4]
        team_b = data.team_b_players[:4]

        # 4 singles: Player 1 vs Player 1, Player 2 vs Player 2, etc.
        for i in range(4):
            match = Match(
                match_day_id=match_day.id,
                match_number=match_number,
                match_type="singles",
                team_a_name=data.team_a_name,
                team_b_name=data.team_b_name,
                player_a1=team_a[i] if i < len(team_a) else f"Player A{i+1}",
                player_b1=team_b[i] if i < len(team_b) else f"Player B{i+1}",
                score_state=create_initial_state(),
                history=[]
            )
            db.add(match)
            matches.append(match)
            match_number += 1

        # 2 doubles: (1,2) vs (1,2), (3,4) vs (3,4)
        doubles_pairings = [
            ((0, 1), (0, 1)), ((2, 3), (2, 3))
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

    await db.commit()
    await db.refresh(match_day)

    return {
        "success": True,
        "match_day": match_day.to_dict(),
        "matches": [m.to_dict() for m in matches]
    }


@app.get("/api/matchdays")
async def list_match_days(db: AsyncSession = Depends(get_db)):
    """List all match days sorted by creation date (newest first)."""
    result = await db.execute(
        select(MatchDay).order_by(MatchDay.created_at.desc())
    )
    match_days = result.scalars().all()

    # For each match day, get the match results summary
    archive = []
    for md in match_days:
        matches_result = await db.execute(
            select(Match).where(Match.match_day_id == md.id)
        )
        matches = matches_result.scalars().all()

        team_a_wins = sum(1 for m in matches if m.score_state.get("winner") == 0)
        team_b_wins = sum(1 for m in matches if m.score_state.get("winner") == 1)
        total_matches = len(matches)
        completed_matches = sum(1 for m in matches if m.score_state.get("winner") is not None)

        archive.append({
            **md.to_dict(),
            "team_a_wins": team_a_wins,
            "team_b_wins": team_b_wins,
            "total_matches": total_matches,
            "completed_matches": completed_matches,
        })

    return {"match_days": archive}


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


@app.delete("/api/matchdays/{match_day_id}")
async def delete_match_day(match_day_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Delete a match day and all its matches. Requires admin authentication."""
    # Verify admin authentication
    admin_session = await get_admin_session(request, db)
    if not admin_session:
        raise HTTPException(status_code=401, detail="Admin authentication required")

    # Find the match day
    result = await db.execute(select(MatchDay).where(MatchDay.id == match_day_id))
    match_day = result.scalar_one_or_none()
    if not match_day:
        raise HTTPException(status_code=404, detail="Match day not found")

    # Delete all matches in this match day first
    matches_result = await db.execute(
        select(Match).where(Match.match_day_id == match_day_id)
    )
    matches = matches_result.scalars().all()
    for match in matches:
        await db.delete(match)

    # Delete the match day
    await db.delete(match_day)
    await db.commit()

    return {"success": True, "message": f"Match day '{match_day.name}' and {len(matches)} matches deleted"}


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
