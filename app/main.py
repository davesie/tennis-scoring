from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, Request, Form
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import Dict, List, Set
import json
import asyncio
import logging
from datetime import datetime
from contextlib import asynccontextmanager

from .database import get_db, init_db, async_session_maker
from .models import Match, MatchDay, Club, Player

logger = logging.getLogger(__name__)
from .schemas import MatchCreate, ScorePoint, MatchResponse, MatchDayCreate, ScoreGame, MatchPlayersUpdate, MatchScoreSet, DoublesCreate, SetInitialServer
from .scoring import score_point, score_game, create_initial_state, get_score_summary
from .auth import (
    ADMIN_SESSION_COOKIE,
    verify_admin_password,
    create_admin_session,
    get_admin_session,
    delete_admin_session,
    get_scorer_token,
    verify_scorer_for_match,
)
from .wtb_scraper import scrape_all_clubs, scrape_all_clubs_with_progress, scrape_club_players

# Flag to prevent concurrent club syncs
_sync_in_progress = False


# ==================== Helpers ====================

def compute_matchday_stats(matches) -> dict:
    """Compute win/completion stats from a list of Match objects."""
    return {
        "team_a_wins": sum(1 for m in matches if m.score_state.get("winner") == 0),
        "team_b_wins": sum(1 for m in matches if m.score_state.get("winner") == 1),
        "total_matches": len(matches),
        "completed_matches": sum(1 for m in matches if m.score_state.get("winner") is not None),
    }


async def upsert_club(db, club_data: dict):
    """Insert or update a Club record from scraped data."""
    result = await db.execute(select(Club).where(Club.wtb_id == club_data["wtb_id"]))
    existing = result.scalar_one_or_none()
    if existing:
        existing.name = club_data["name"]
        existing.location = club_data.get("location")
        existing.district = club_data.get("district")
        existing.url = club_data["url"]
        existing.last_synced = datetime.utcnow()
    else:
        db.add(Club(
            wtb_id=club_data["wtb_id"],
            name=club_data["name"],
            location=club_data.get("location"),
            district=club_data.get("district"),
            url=club_data["url"],
            last_synced=datetime.utcnow(),
        ))


def create_player_from_data(player_data: dict, club_id: str) -> Player:
    """Construct a Player ORM instance from scraped dict."""
    return Player(
        name=player_data["name"],
        birth_year=player_data.get("birth_year"),
        category=player_data.get("category", "Herren"),
        wtb_id_nummer=player_data.get("wtb_id_nummer"),
        ranking=player_data.get("ranking"),
        is_captain=player_data.get("is_captain", False),
        club_id=club_id,
    )


async def broadcast_match_update(match, state):
    """Broadcast score_update to match viewers and match_update to matchday viewers."""
    await manager.broadcast(match.id, {
        "type": "score_update",
        "match": match.to_dict(),
        "summary": get_score_summary(state)
    })
    if match.match_day_id:
        await manager.broadcast_matchday(match.match_day_id, {
            "type": "match_update",
            "match": match.to_dict()
        })


async def _render_matchday(request, db, match_day, is_scorer):
    """Fetch matches for a match day and render matchday.html."""
    matches_result = await db.execute(
        select(Match).where(Match.match_day_id == match_day.id).order_by(Match.match_number)
    )
    matches = [m.to_dict() for m in matches_result.scalars().all()]
    return templates.TemplateResponse("matchday.html", {
        "request": request,
        "match_day": match_day.to_dict(),
        "matches": matches,
        "is_scorer": is_scorer
    })


async def _startup_sync_clubs():
    """Background task: sync WTB clubs on startup. Swallows all errors."""
    try:
        logger.info("Background startup: syncing WTB clubs...")
        clubs_data = await scrape_all_clubs()
        async with async_session_maker() as db:
            for club_data in clubs_data:
                await upsert_club(db, club_data)
            await db.commit()
        logger.info(f"Background startup: synced {len(clubs_data)} clubs")
    except Exception as e:
        logger.warning(f"Background startup club sync failed (non-fatal): {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    asyncio.create_task(_startup_sync_clubs())
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
        # match_day_id -> set of websocket connections
        self.matchday_connections: Dict[str, Set[WebSocket]] = {}

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

    async def connect_matchday(self, websocket: WebSocket, match_day_id: str):
        await websocket.accept()
        if match_day_id not in self.matchday_connections:
            self.matchday_connections[match_day_id] = set()
        self.matchday_connections[match_day_id].add(websocket)

    def disconnect_matchday(self, websocket: WebSocket, match_day_id: str):
        if match_day_id in self.matchday_connections:
            self.matchday_connections[match_day_id].discard(websocket)
            if not self.matchday_connections[match_day_id]:
                del self.matchday_connections[match_day_id]

    async def broadcast_matchday(self, match_day_id: str, message: dict):
        if match_day_id in self.matchday_connections:
            dead_connections = set()
            for connection in self.matchday_connections[match_day_id]:
                try:
                    await connection.send_json(message)
                except Exception:
                    dead_connections.add(connection)
            for conn in dead_connections:
                self.matchday_connections[match_day_id].discard(conn)


manager = ConnectionManager()


# Page routes
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Home page - shows the public archive."""
    return RedirectResponse(url="/archive", status_code=302)


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

        singles = [m for m in matches if m.match_type == "singles"]
        doubles = [m for m in matches if m.match_type == "doubles"]
        stats = compute_matchday_stats(matches)
        singles_completed = sum(1 for m in singles if m.score_state.get("winner") is not None)

        match_days_data.append({
            **md.to_dict(),
            **stats,
            "singles_total": len(singles),
            "singles_completed": singles_completed,
            "has_doubles": len(doubles) > 0,
        })

    # Query last club sync timestamp
    last_sync_result = await db.execute(select(func.max(Club.last_synced)))
    last_club_sync_dt = last_sync_result.scalar()
    last_club_sync = last_club_sync_dt.isoformat() if last_club_sync_dt else None

    return templates.TemplateResponse("admin.html", {
        "request": request,
        "match_days": match_days_data,
        "last_club_sync": last_club_sync,
    })


@app.post("/admin/logout")
async def admin_logout(request: Request, db: AsyncSession = Depends(get_db)):
    """Log out admin user."""
    session_id = request.cookies.get(ADMIN_SESSION_COOKIE)
    if session_id:
        await delete_admin_session(session_id, db)

    response = RedirectResponse(url="/", status_code=303)
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

    if not match.score_state.get("initial_server_set", True):
        raise HTTPException(status_code=400, detail="Please select who serves first")

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

    await broadcast_match_update(match, new_state)

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

    await broadcast_match_update(match, previous_state)

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

    await broadcast_match_update(match, match.score_state)

    return {"success": True, "match": match.to_dict()}


@app.post("/api/matches/{match_id}/set-server")
async def set_initial_server(match_id: str, data: SetInitialServer, request: Request, db: AsyncSession = Depends(get_db)):
    """Set who serves first. Only allowed before any games have been played."""
    match = await verify_scorer_for_match(match_id, request, db)

    if data.serving not in (0, 1):
        raise HTTPException(status_code=400, detail="serving must be 0 or 1")

    state = match.score_state
    # Only allowed while still in game 1 of set 1 with no winner
    if state.get("games", [[0, 0]])[0] != [0, 0] or state.get("winner") is not None:
        raise HTTPException(status_code=400, detail="Can only set server before first game is completed")

    new_state = {**state, "serving": data.serving, "initial_server_set": True}
    match.score_state = new_state
    match.updated_at = datetime.utcnow()

    await db.commit()
    await db.refresh(match)

    await broadcast_match_update(match, new_state)

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

    await broadcast_match_update(match, new_state)

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

    if not match.score_state.get("initial_server_set", True):
        raise HTTPException(status_code=400, detail="Please select who serves first")

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

    await broadcast_match_update(match, new_state)

    return {"success": True, "match": match.to_dict()}


# Match Day routes
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

        archive.append({**md.to_dict(), **compute_matchday_stats(matches)})

    # Check if user is logged in as admin
    admin_session = await get_admin_session(request, db)

    return templates.TemplateResponse("archive.html", {
        "request": request,
        "match_days": archive,
        "is_admin": admin_session is not None
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

    return await _render_matchday(request, db, match_day, is_scorer=True)


@app.get("/watchday/{share_code}", response_class=HTMLResponse)
async def spectator_match_day_page(request: Request, share_code: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(MatchDay).where(MatchDay.share_code == share_code))
    match_day = result.scalar_one_or_none()
    if not match_day:
        raise HTTPException(status_code=404, detail="Match day not found")

    return await _render_matchday(request, db, match_day, is_scorer=False)


@app.get("/scoreday/{scorer_token}", response_class=HTMLResponse)
async def scorer_match_day_page(request: Request, scorer_token: str, db: AsyncSession = Depends(get_db)):
    """Access match day with scorer permissions using a shareable token."""
    result = await db.execute(select(MatchDay).where(MatchDay.scorer_token == scorer_token))
    match_day = result.scalar_one_or_none()
    if not match_day:
        raise HTTPException(status_code=404, detail="Invalid scorer token")

    return await _render_matchday(request, db, match_day, is_scorer=True)


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

    # Determine player count based on format
    player_count = 6 if data.format == "6_person" else 4
    team_a = data.team_a_players[:player_count]
    team_b = data.team_b_players[:player_count]

    # Create singles only — doubles are set up separately after all singles complete
    for i in range(player_count):
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

    await db.commit()
    await db.refresh(match_day)

    return {
        "success": True,
        "match_day": match_day.to_dict(),
        "matches": [m.to_dict() for m in matches]
    }


@app.post("/api/matchdays/{match_day_id}/doubles")
async def create_match_day_doubles(match_day_id: str, data: DoublesCreate, request: Request, db: AsyncSession = Depends(get_db)):
    """Create doubles matches for a match day after all singles are complete. Requires admin authentication."""
    admin_session = await get_admin_session(request, db)
    if not admin_session:
        raise HTTPException(status_code=401, detail="Admin authentication required")

    result = await db.execute(select(MatchDay).where(MatchDay.id == match_day_id))
    match_day = result.scalar_one_or_none()
    if not match_day:
        raise HTTPException(status_code=404, detail="Match day not found")

    matches_result = await db.execute(
        select(Match).where(Match.match_day_id == match_day_id).order_by(Match.match_number)
    )
    all_matches = matches_result.scalars().all()

    singles = [m for m in all_matches if m.match_type == "singles"]
    doubles_existing = [m for m in all_matches if m.match_type == "doubles"]

    if doubles_existing:
        raise HTTPException(status_code=400, detail="Doubles already created for this match day")

    incomplete_singles = [m for m in singles if m.score_state.get("winner") is None]
    if incomplete_singles:
        raise HTTPException(
            status_code=400,
            detail=f"{len(incomplete_singles)} singles match(es) not yet complete"
        )

    max_number = max((m.match_number or 0) for m in all_matches) if all_matches else 0
    match_number = max_number + 1

    created = []
    for pairing in data.pairings:
        match = Match(
            match_day_id=match_day_id,
            match_number=match_number,
            match_type="doubles",
            team_a_name=match_day.team_a_name,
            team_b_name=match_day.team_b_name,
            player_a1=pairing.player_a1,
            player_a2=pairing.player_a2,
            player_b1=pairing.player_b1,
            player_b2=pairing.player_b2,
            score_state=create_initial_state(),
            history=[]
        )
        db.add(match)
        created.append(match)
        match_number += 1

    await db.commit()
    for m in created:
        await db.refresh(m)

    return {"success": True, "matches": [m.to_dict() for m in created]}


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

        archive.append({**md.to_dict(), **compute_matchday_stats(matches)})

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


# ==================== WTB Club & Player Integration ====================

@app.post("/api/admin/sync-clubs")
async def sync_wtb_clubs(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Scrape and sync all WTB clubs. Admin only.
    This will scrape all pages from the WTB website and update the database.
    """
    # Verify admin authentication
    admin_session = await get_admin_session(request, db)
    if not admin_session:
        raise HTTPException(status_code=401, detail="Admin authentication required")

    try:
        # Scrape all clubs from WTB
        clubs_data = await scrape_all_clubs()

        for club_data in clubs_data:
            await upsert_club(db, club_data)

        await db.commit()

        total_result = await db.execute(select(func.count()).select_from(Club))
        total_in_db = total_result.scalar()

        return {
            "success": True,
            "synced": len(clubs_data),
            "total_in_db": total_in_db,
            "message": f"Successfully synced {len(clubs_data)} clubs from WTB ({total_in_db} total in database)"
        }

    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Error syncing clubs: {str(e)}")


@app.post("/api/admin/sync-clubs-stream")
async def sync_wtb_clubs_stream(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Scrape and sync all WTB clubs with real-time SSE progress. Admin only.
    Returns a Server-Sent Events stream showing progress after each page.
    Returns 409 if a sync is already running.
    """
    global _sync_in_progress

    # Verify admin authentication
    admin_session = await get_admin_session(request, db)
    if not admin_session:
        raise HTTPException(status_code=401, detail="Admin authentication required")

    if _sync_in_progress:
        raise HTTPException(status_code=409, detail="Sync already in progress")

    async def event_generator():
        global _sync_in_progress
        _sync_in_progress = True
        try:
            clubs_data = []
            async for event in scrape_all_clubs_with_progress():
                if event["type"] == "progress":
                    payload = json.dumps({
                        "type": "progress",
                        "page": event["page"],
                        "clubs_so_far": event["clubs_so_far"],
                        **({"total_pages": event["total_pages"]} if "total_pages" in event else {}),
                    })
                    yield f"data: {payload}\n\n"
                elif event["type"] == "complete":
                    clubs_data = event["clubs"]
                    # Signal that we're now saving
                    saving_payload = json.dumps({
                        "type": "saving",
                        "total_clubs": event["total_clubs"],
                    })
                    yield f"data: {saving_payload}\n\n"

            # DB upsert
            async with async_session_maker() as save_db:
                for club_data in clubs_data:
                    await upsert_club(save_db, club_data)

                await save_db.commit()

                total_result = await save_db.execute(select(func.count()).select_from(Club))
                total_in_db = total_result.scalar()

                last_sync_result = await save_db.execute(select(func.max(Club.last_synced)))
                last_sync_dt = last_sync_result.scalar()
                last_synced_iso = last_sync_dt.isoformat() if last_sync_dt else None

            done_payload = json.dumps({
                "type": "done",
                "synced": len(clubs_data),
                "total_in_db": total_in_db,
                "last_synced": last_synced_iso,
            })
            yield f"data: {done_payload}\n\n"

        except Exception as e:
            error_payload = json.dumps({"type": "error", "message": str(e)})
            yield f"data: {error_payload}\n\n"
        finally:
            _sync_in_progress = False

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/admin/sync-club-players/{club_id}")
async def sync_club_players_endpoint(
    club_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Scrape and sync players for a specific club. Admin only.
    Only scrapes Herren (Men) category.
    """
    # Verify admin authentication
    admin_session = await get_admin_session(request, db)
    if not admin_session:
        raise HTTPException(status_code=401, detail="Admin authentication required")

    # Find the club
    result = await db.execute(select(Club).where(Club.id == club_id))
    club = result.scalar_one_or_none()
    if not club:
        raise HTTPException(status_code=404, detail="Club not found")

    try:
        # Scrape players from WTB
        players_data = await scrape_club_players(club.wtb_id)

        # Delete existing players for this club (to avoid duplicates)
        await db.execute(
            select(Player).where(Player.club_id == club_id)
        )
        existing_players = (await db.execute(
            select(Player).where(Player.club_id == club_id)
        )).scalars().all()

        for player in existing_players:
            await db.delete(player)

        # Add new players
        for player_data in players_data:
            db.add(create_player_from_data(player_data, club_id))

        # Update club's last_synced timestamp
        club.last_synced = datetime.utcnow()

        await db.commit()

        return {
            "success": True,
            "synced": len(players_data),
            "club_name": club.name,
            "message": f"Successfully synced {len(players_data)} Herren players for {club.name}"
        }

    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Error syncing players for club {club.name}: {str(e)}"
        )


@app.get("/api/clubs/search")
async def search_clubs(q: str = "", limit: int = 10, db: AsyncSession = Depends(get_db)):
    """
    Search clubs by name.
    Public endpoint - no authentication required.
    """
    query = select(Club)

    if q:
        query = query.where(Club.name.ilike(f"%{q}%"))

    query = query.limit(limit)

    result = await db.execute(query)
    clubs = result.scalars().all()

    return [club.to_dict() for club in clubs]


@app.get("/api/clubs/{club_id}/players")
async def get_club_players(club_id: str, db: AsyncSession = Depends(get_db)):
    """
    Return all Herren players for a club, sorted by ranking ASC (nulls last).
    If the club has no players yet, auto-triggers a scrape first.
    Public endpoint - no authentication required.
    """
    # Look up club
    club_result = await db.execute(select(Club).where(Club.id == club_id))
    club = club_result.scalar_one_or_none()
    if not club:
        raise HTTPException(status_code=404, detail="Club not found")

    # Count existing Herren players
    count_result = await db.execute(
        select(func.count()).select_from(Player).where(
            Player.club_id == club_id, Player.category == "Herren"
        )
    )
    player_count = count_result.scalar()

    if player_count == 0:
        # Auto-sync: scrape and store players for this club
        try:
            players_data = await scrape_club_players(club.wtb_id)
            for player_data in players_data:
                db.add(create_player_from_data(player_data, club_id))
            club.last_synced = datetime.utcnow()
            await db.commit()
        except Exception as e:
            logger.warning(f"Auto-sync players for club {club_id} failed: {e}")
            await db.rollback()

    # Query ordered by ranking ASC, NULLs last
    result = await db.execute(
        select(Player)
        .where(Player.club_id == club_id, Player.category == "Herren")
        .order_by(Player.ranking.is_(None), Player.ranking.asc())
    )
    players = result.scalars().all()
    return [p.to_dict() for p in players]


@app.get("/api/clubs/{club_id}/players/search")
async def search_club_players(
    club_id: str,
    q: str = "",
    limit: int = 20,
    db: AsyncSession = Depends(get_db)
):
    """
    Search players within a specific club.
    Only returns Herren (Men) players.
    Public endpoint - no authentication required.
    """
    query = select(Player).where(
        Player.club_id == club_id,
        Player.category == "Herren"
    )

    if q:
        query = query.where(Player.name.ilike(f"%{q}%"))

    query = query.limit(limit)

    result = await db.execute(query)
    players = result.scalars().all()

    return [player.to_dict() for player in players]


# WebSocket endpoint for matchday-level real-time updates
@app.websocket("/ws/matchday/{match_day_id}")
async def matchday_websocket_endpoint(websocket: WebSocket, match_day_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(MatchDay).where(MatchDay.id == match_day_id))
    match_day = result.scalar_one_or_none()
    if not match_day:
        await websocket.close(code=4004, reason="Match day not found")
        return

    await manager.connect_matchday(websocket, match_day_id)
    try:
        # Send initial state with all matches
        matches_result = await db.execute(
            select(Match).where(Match.match_day_id == match_day_id).order_by(Match.match_number)
        )
        matches = [m.to_dict() for m in matches_result.scalars().all()]
        await websocket.send_json({"type": "initial", "matches": matches})

        while True:
            try:
                await websocket.receive_text()
            except WebSocketDisconnect:
                break
    finally:
        manager.disconnect_matchday(websocket, match_day_id)


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
