import asyncio
import json
import logging
import secrets
import subprocess
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
import os
from typing import Dict, Optional, Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from .database import get_db, init_db, async_session_maker, ensure_superadmin
from .seed import seed_demo_data
from .models import Match, MatchDay, Club, Player, User, AdminSession
from .schemas import MatchCreate, ScorePoint, MatchResponse, MatchDayCreate, ScoreGame, MatchPlayersUpdate, MatchScoreSet, DoublesCreate, SetInitialServer, FixtureImport, MatchDaySetup, UserRegister, UserLogin, PointOutcome, AdminPasswordReset
from .scoring import score_point, score_game, create_initial_state, get_score_summary
from .auth import (
    SESSION_COOKIE,
    require_superadmin,
    hash_password,
    verify_password,
    create_session,
    get_current_user,
    get_session_id,
    delete_session,
    get_scorer_token,
    verify_scorer_for_match,
    is_owner_or_superadmin,
)
from .wtb_scraper import scrape_all_clubs, scrape_all_clubs_with_progress, scrape_club_players, scrape_club_teams, scrape_team_fixtures, scrape_spielbericht
from .i18n import i18n_context, get_lang, make_t, strings_for

# Make app INFO logs (superadmin bootstrap, sync progress) visible in
# container logs; uvicorn only configures its own loggers.
logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")

logger = logging.getLogger(__name__)

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
        lk=player_data.get("lk"),
        is_captain=player_data.get("is_captain", False),
        club_id=club_id,
    )


def push_history(match) -> list:
    """Snapshot the current score state AND point log for undo.

    Each entry is {"score_state": ..., "point_log": ...} so undoing a point
    also rolls back its statistics entry. Keeps at most 50 entries.
    """
    history = match.history.copy() if match.history else []
    history.append({
        "score_state": match.score_state.copy() if match.score_state else None,
        "point_log": list(match.point_log) if match.point_log else [],
    })
    if len(history) > 50:
        history = history[-50:]
    return history


async def apply_new_state(match, new_state, history, db, point_log=None):
    """Apply a new score state to a match, commit, and broadcast."""
    match.score_state = new_state
    match.history = history
    if point_log is not None:
        match.point_log = point_log
    match.updated_at = datetime.utcnow()

    if new_state.get("winner") is not None:
        match.finished_at = datetime.utcnow()

    await db.commit()
    await db.refresh(match)
    await broadcast_match_update(match, new_state)


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
    matches_result = await db.execute(
        select(Match).where(Match.match_day_id == match_day.id).order_by(Match.match_number)
    )
    matches = [m.to_dict() for m in matches_result.scalars().all()]
    md_dict = match_day.to_dict_private() if is_scorer else match_day.to_dict()
    return templates.TemplateResponse("matchday.html", {
        "request": request,
        "match_day": md_dict,
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
    await ensure_superadmin()
    await seed_demo_data()
    asyncio.create_task(_startup_sync_clubs())
    yield


app = FastAPI(title="Tennis Scoring", lifespan=lifespan)


# ==================== Security hardening ====================

# Content-Security-Policy for the server-rendered site. Inline scripts are
# allowed only via a per-request nonce (no 'unsafe-inline' for scripts, and no
# inline on* handlers — see the data-action delegation in common.js). Inline
# *styles* stay allowed (style="" attributes can't execute JS; far lower risk).
# Google Fonts are whitelisted. The Flutter bundle under /app manages its own
# loading (CanvasKit from gstatic) and is exempted below.
def _csp(nonce: str) -> str:
    return (
        "default-src 'self'; "
        f"script-src 'self' 'nonce-{nonce}'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self' ws: wss:; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'self'"
    )


@app.middleware("http")
async def security_headers(request: Request, call_next):
    # Per-request nonce, exposed to templates via the i18n context processor
    # (request.state.csp_nonce) and echoed in the CSP header below.
    nonce = secrets.token_urlsafe(16)
    request.state.csp_nonce = nonce

    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if not request.url.path.startswith("/app"):
        response.headers.setdefault("Content-Security-Policy", _csp(nonce))
    # Only meaningful over HTTPS (requires uvicorn --proxy-headers behind the
    # reverse proxy so the original scheme is visible).
    if request.url.scheme == "https":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    return response


# Simple in-memory per-IP rate limiter for the auth endpoints (login,
# register). Good enough for a single-process deployment; state resets on
# restart, which is fine — its job is to make credential/invite-code
# brute-forcing impractical, not to be perfect accounting.
_rate_buckets: Dict[str, list] = {}


def enforce_rate_limit(request: Request, key: str, limit: int = 10, window_seconds: int = 60):
    ip = request.client.host if request.client else "unknown"
    bucket_key = f"{key}:{ip}"
    now = time.monotonic()
    bucket = _rate_buckets.setdefault(bucket_key, [])
    bucket[:] = [t for t in bucket if now - t < window_seconds]
    if len(bucket) >= limit:
        raise HTTPException(status_code=429, detail="Too many attempts. Please wait a minute and try again.")
    bucket.append(now)
    # Keep the dict from growing unboundedly under scanning traffic
    if len(_rate_buckets) > 10000:
        for k in [k for k, v in _rate_buckets.items() if not v or now - v[-1] > window_seconds]:
            _rate_buckets.pop(k, None)


# A constant bcrypt hash used to equalize login timing when the email is
# unknown (prevents user enumeration via response-time differences).
_DUMMY_HASH = hash_password("not-a-real-password")


# Mount static files and templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates", context_processors=[i18n_context])


class SPAStaticFiles(StaticFiles):
    """StaticFiles that falls back to index.html for unknown paths.

    Lets the Flutter web build's client-side (go_router) routes resolve on a
    hard refresh, e.g. GET /app/watchday/{code} serves index.html so the app
    can route it, instead of returning 404.
    """

    async def get_response(self, path, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404:
                return await super().get_response("index.html", scope)
            raise


# Serve the compiled Flutter web bundle at /app (same origin as the API, so no
# CORS is needed). Only mounted when the build exists; run
# `flutter build web --base-href /app/` from mobile/ to produce it. The existing
# Jinja routes (/, /archive, /admin, ...) are unaffected.
_flutter_web_dir = Path(__file__).resolve().parent.parent / "mobile" / "build" / "web"
if _flutter_web_dir.is_dir():
    app.mount("/app", SPAStaticFiles(directory=str(_flutter_web_dir), html=True), name="flutter_web")


def _get_app_version() -> str:
    """Read version from pyproject.toml and append short git commit hash."""
    version = "0.0.0"
    try:
        pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
        for line in pyproject.read_text().splitlines():
            if line.strip().startswith("version"):
                version = line.split("=")[1].strip().strip('"')
                break
    except Exception:
        pass
    try:
        git_hash = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
        ).decode().strip()
        return f"{version}+{git_hash}"
    except Exception:
        return version


APP_VERSION = _get_app_version()
templates.env.globals["app_version"] = APP_VERSION


# WebSocket connection manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        self.matchday_connections: Dict[str, Set[WebSocket]] = {}

    async def _connect(self, pool: Dict[str, Set[WebSocket]], websocket: WebSocket, key: str):
        await websocket.accept()
        pool.setdefault(key, set()).add(websocket)

    def _disconnect(self, pool: Dict[str, Set[WebSocket]], websocket: WebSocket, key: str):
        if key in pool:
            pool[key].discard(websocket)
            if not pool[key]:
                del pool[key]

    async def _broadcast(self, pool: Dict[str, Set[WebSocket]], key: str, message: dict):
        if key not in pool:
            return
        dead = set()
        for conn in pool[key]:
            try:
                await conn.send_json(message)
            except Exception:
                dead.add(conn)
        pool[key] -= dead

    async def connect(self, websocket: WebSocket, match_id: str):
        await self._connect(self.active_connections, websocket, match_id)

    def disconnect(self, websocket: WebSocket, match_id: str):
        self._disconnect(self.active_connections, websocket, match_id)

    async def broadcast(self, match_id: str, message: dict):
        await self._broadcast(self.active_connections, match_id, message)

    async def connect_matchday(self, websocket: WebSocket, match_day_id: str):
        await self._connect(self.matchday_connections, websocket, match_day_id)

    def disconnect_matchday(self, websocket: WebSocket, match_day_id: str):
        self._disconnect(self.matchday_connections, websocket, match_day_id)

    async def broadcast_matchday(self, match_day_id: str, message: dict):
        await self._broadcast(self.matchday_connections, match_day_id, message)


manager = ConnectionManager()


# Page routes
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Home page - shows the public archive."""
    return RedirectResponse(url="/archive", status_code=302)


# Admin routes
@app.get("/admin/login", response_class=HTMLResponse)
async def login_page(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)
    if user:
        return RedirectResponse(url="/admin", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/admin/login")
async def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db)
):
    enforce_rate_limit(request, "login")
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    # Verify against a dummy hash when the email is unknown so both paths
    # take the same time (no user enumeration via timing).
    if not verify_password(password, user.password_hash if user else _DUMMY_HASH) or not user:
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "Invalid email or password"
        })

    user.last_login_at = datetime.utcnow()
    session = await create_session(db, user.id)

    response = RedirectResponse(url="/admin", status_code=303)
    response.set_cookie(
        key=SESSION_COOKIE,
        value=session.id,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        max_age=7 * 24 * 60 * 60
    )
    return response


@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)
    if user:
        return RedirectResponse(url="/admin", status_code=302)
    return templates.TemplateResponse("register.html", {
        "request": request,
        "registration_mode": REGISTRATION_MODE,
    })


# Registration gating: "open" (anyone), "code" (shared invite code required),
# "closed" (no self-registration). Set in the environment, e.g. via Coolify.
REGISTRATION_MODE = os.getenv("REGISTRATION_MODE", "open").strip().lower()
REGISTRATION_CODE = os.getenv("REGISTRATION_CODE", "")


def _check_invite(invite_code: str) -> Optional[str]:
    """Return an i18n error key if registration is not allowed, else None."""
    if REGISTRATION_MODE == "closed":
        return "register.closed"
    if REGISTRATION_MODE == "code":
        if not REGISTRATION_CODE:
            return "register.closed"  # misconfigured: fail safe
        if not secrets.compare_digest(invite_code.strip(), REGISTRATION_CODE):
            return "register.invite_invalid"
    return None


@app.post("/register")
async def register(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    display_name: str = Form(""),
    invite_code: str = Form(""),
    db: AsyncSession = Depends(get_db)
):
    enforce_rate_limit(request, "register")
    t = make_t(get_lang(request))

    def form_error(message: str):
        return templates.TemplateResponse("register.html", {
            "request": request,
            "error": message,
            "email": email,
            "display_name": display_name,
            "registration_mode": REGISTRATION_MODE,
        })

    invite_error = _check_invite(invite_code)
    if invite_error:
        return form_error(t(invite_error))

    if len(password) < 6:
        return form_error(t("register.password_short"))

    existing = await db.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none():
        return form_error(t("register.email_exists"))

    user = User(
        email=email,
        password_hash=hash_password(password),
        display_name=display_name.strip() or None,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    session = await create_session(db, user.id)

    response = RedirectResponse(url="/admin", status_code=303)
    response.set_cookie(
        key=SESSION_COOKIE,
        value=session.id,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        max_age=7 * 24 * 60 * 60
    )
    return response


@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/admin/login", status_code=302)

    query = select(MatchDay).order_by(
        func.coalesce(MatchDay.scheduled_date, MatchDay.created_at).desc()
    )
    if not user.is_superadmin:
        query = query.where(MatchDay.owner_id == user.id)

    result = await db.execute(query)
    match_days = result.scalars().all()

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

        md_dict = md.to_dict_private()
        match_days_data.append({
            **md_dict,
            **stats,
            "singles_total": len(singles),
            "singles_completed": singles_completed,
            "has_doubles": len(doubles) > 0,
        })

    last_sync_result = await db.execute(select(func.max(Club.last_synced)))
    last_club_sync_dt = last_sync_result.scalar()
    last_club_sync = last_club_sync_dt.isoformat() if last_club_sync_dt else None

    # Usage stats for superadmin
    stats = None
    if user.is_superadmin:
        total_users = (await db.execute(select(func.count()).select_from(User))).scalar()
        total_match_days = (await db.execute(select(func.count()).select_from(MatchDay))).scalar()
        total_matches = (await db.execute(select(func.count()).select_from(Match))).scalar()
        stats = {
            "total_users": total_users,
            "total_match_days": total_match_days,
            "total_matches": total_matches,
        }

    return templates.TemplateResponse("admin.html", {
        "request": request,
        "match_days": match_days_data,
        "last_club_sync": last_club_sync,
        "user": user.to_dict(),
        "is_superadmin": user.is_superadmin,
        "stats": stats,
        "create_page": False,
    })


@app.get("/admin/new", response_class=HTMLResponse)
async def admin_new_match_day(request: Request, db: AsyncSession = Depends(get_db)):
    """Dedicated full-page match-day creation form (reuses admin.html)."""
    user = await get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/admin/login", status_code=302)

    return templates.TemplateResponse("admin.html", {
        "request": request,
        "match_days": [],
        "last_club_sync": None,
        "user": user.to_dict(),
        "is_superadmin": user.is_superadmin,
        "stats": None,
        "create_page": True,
    })


@app.post("/admin/logout")
async def logout(request: Request, db: AsyncSession = Depends(get_db)):
    session_id = request.cookies.get(SESSION_COOKIE)
    if session_id:
        await delete_session(session_id, db)

    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie(key=SESSION_COOKIE)
    return response


# ==================== JSON auth (for the Flutter iOS/Android/Web client) ====================
# These mirror the form-based routes above but speak JSON and return a bearer
# token (the AdminSession id) instead of setting a cookie. The same session
# machinery backs both, so cookie-based web login is unaffected.

@app.post("/api/auth/register")
async def api_register(payload: UserRegister, request: Request, db: AsyncSession = Depends(get_db)):
    enforce_rate_limit(request, "register")
    invite_error = _check_invite(payload.invite_code or "")
    if invite_error:
        status = 403 if invite_error == "register.closed" else 401
        raise HTTPException(status_code=status, detail="Registration not allowed (invite code required or registration closed)")
    if len(payload.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    existing = await db.execute(select(User).where(User.email == payload.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="An account with this email already exists")

    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        display_name=(payload.display_name or "").strip() or None,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    session = await create_session(db, user.id)
    return {"token": session.id, "user": user.to_dict()}


@app.post("/api/auth/login")
async def api_login(payload: UserLogin, request: Request, db: AsyncSession = Depends(get_db)):
    enforce_rate_limit(request, "login")
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    # Dummy-hash comparison keeps timing equal for unknown emails
    if not verify_password(payload.password, user.password_hash if user else _DUMMY_HASH) or not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    user.last_login_at = datetime.utcnow()
    session = await create_session(db, user.id)
    return {"token": session.id, "user": user.to_dict()}


@app.get("/api/auth/me")
async def api_me(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return {"user": user.to_dict()}


@app.post("/api/auth/logout")
async def api_logout(request: Request, db: AsyncSession = Depends(get_db)):
    session_id = get_session_id(request)
    if session_id:
        await delete_session(session_id, db)
    return {"success": True}


@app.get("/match/{match_id}", response_class=HTMLResponse)
async def match_page(request: Request, match_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Match).where(Match.id == match_id))
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    user = await get_current_user(request, db)

    match_day_share_code = None
    match_day_scorer_token = None
    is_owner = False
    if match.match_day_id:
        md_result = await db.execute(select(MatchDay).where(MatchDay.id == match.match_day_id))
        match_day = md_result.scalar_one_or_none()
        if match_day:
            match_day_share_code = match_day.share_code
            match_day_scorer_token = match_day.scorer_token
            if user:
                is_owner = await is_owner_or_superadmin(user, match_day)

    # Link-scorers (via /scoreday/{token}) carry the token as a query param —
    # they get the full scorer view too, not just logged-in owners.
    token = get_scorer_token(request)
    is_token_scorer = bool(token) and (
        (match.scorer_token and secrets.compare_digest(token, match.scorer_token))
        or (match_day_scorer_token and secrets.compare_digest(token, match_day_scorer_token))
    )
    is_scorer = is_owner or is_token_scorer

    scorer_token = None
    if is_scorer:
        scorer_token = match_day_scorer_token or match.scorer_token

    # Back link that preserves the visitor's role/context
    if match.match_day_id:
        if is_owner:
            back_url = f"/matchday/{match.match_day_id}"
        elif is_token_scorer and match_day_scorer_token:
            back_url = f"/scoreday/{match_day_scorer_token}"
        else:
            back_url = f"/watchday/{match_day_share_code}"
    else:
        back_url = "/archive"

    return templates.TemplateResponse("match.html", {
        "request": request,
        "match": match.to_dict(include_stats=is_scorer),
        "is_scorer": is_scorer,
        "match_day_share_code": match_day_share_code,
        "scorer_token": scorer_token,
        "back_url": back_url,
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
    user = await get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

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
    # to_dict() so computed fields (score_cells, point_by_point, stats when
    # finished, durations) reach the public payload, not just column attrs.
    return match.to_dict()


@app.get("/api/matches/share/{share_code}", response_model=MatchResponse)
async def get_match_by_share_code(share_code: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Match).where(Match.share_code == share_code))
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    return match.to_dict()


@app.post("/api/matches/{match_id}/score")
async def score(match_id: str, score_data: ScorePoint, request: Request, db: AsyncSession = Depends(get_db)):
    # Verify scorer authorization
    match = await verify_scorer_for_match(match_id, request, db)

    if match.score_state.get("winner") is not None:
        raise HTTPException(status_code=400, detail="Match is already finished")

    if not match.score_state.get("initial_server_set", True):
        raise HTTPException(status_code=400, detail="Please select who serves first")

    if not match.started_at and not match.history:
        match.started_at = datetime.utcnow()

    # Capture who served this point BEFORE the state transition (for stats)
    serving_before = match.score_state.get("serving")
    set_before = match.score_state.get("current_set", 0)

    history = push_history(match)
    new_state = score_point(match.score_state, score_data.team, match.super_tiebreak_final_set)

    new_log = list(match.point_log or [])
    new_log.append({
        "winner": score_data.team,
        "server": serving_before,
        "set": set_before,
        "outcome": None,
        "ts": datetime.utcnow().isoformat(),
    })

    await apply_new_state(match, new_state, history, db, point_log=new_log)

    return {"success": True, "match": match.to_dict(include_stats=True)}


@app.post("/api/matches/{match_id}/point-outcome")
async def tag_point_outcome(match_id: str, data: PointOutcome, request: Request, db: AsyncSession = Depends(get_db)):
    """Classify how the most recent point ended (optional, scorer only).

    Updates the last point_log entry. Does not broadcast — live stats stay on
    the scorer's screen; the scorer's panel updates from this response.
    """
    match = await verify_scorer_for_match(match_id, request, db)

    point_log = list(match.point_log or [])
    if not point_log:
        raise HTTPException(status_code=400, detail="No point to tag yet")

    last = dict(point_log[-1])
    winner = last.get("winner")
    server = last.get("server")

    # Validate serve-context outcomes against who won the point
    if data.outcome == "ace" and winner is not None and server is not None and winner != server:
        raise HTTPException(status_code=400, detail="An ace can only be tagged when the server won the point")
    if data.outcome == "double_fault" and winner is not None and server is not None and winner == server:
        raise HTTPException(status_code=400, detail="A double fault can only be tagged when the receiver won the point")

    last["outcome"] = data.outcome
    point_log[-1] = last
    match.point_log = point_log
    match.updated_at = datetime.utcnow()

    await db.commit()
    await db.refresh(match)

    return {"success": True, "match": match.to_dict(include_stats=True)}


@app.post("/api/matches/{match_id}/undo")
async def undo(match_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    # Verify scorer authorization
    match = await verify_scorer_for_match(match_id, request, db)

    history = match.history.copy() if match.history else []
    if not history:
        raise HTTPException(status_code=400, detail="No history to undo")

    # Restore previous snapshot. New entries wrap score_state + point_log;
    # legacy entries are the bare score_state dict.
    previous = history.pop()
    if isinstance(previous, dict) and "score_state" in previous:
        previous_state = previous["score_state"]
        match.point_log = previous.get("point_log", [])
    else:
        previous_state = previous

    match.score_state = previous_state
    match.history = history
    match.updated_at = datetime.utcnow()
    match.finished_at = None  # Clear finished status on undo

    await db.commit()
    await db.refresh(match)

    await broadcast_match_update(match, previous_state)

    return {"success": True, "match": match.to_dict(include_stats=True)}


@app.post("/api/matches/{match_id}/reset")
async def reset_match(match_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    # Verify scorer authorization
    match = await verify_scorer_for_match(match_id, request, db)

    match.score_state = create_initial_state()
    match.history = []
    match.point_log = []
    match.updated_at = datetime.utcnow()
    match.started_at = None
    match.finished_at = None

    await db.commit()
    await db.refresh(match)

    await broadcast_match_update(match, match.score_state)

    return {"success": True, "match": match.to_dict(include_stats=True)}


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

    if not match.started_at and not match.history:
        match.started_at = datetime.utcnow()

    serving_before = match.score_state.get("serving")
    set_before = match.score_state.get("current_set", 0)

    history = push_history(match)
    new_state = score_game(match.score_state, score_data.team, match.super_tiebreak_final_set)

    # Log a game marker (no "winner" key, so point statistics are unaffected)
    # to keep the point-by-point timeline faithful with mixed scoring.
    new_log = list(match.point_log or [])
    new_log.append({
        "kind": "game",
        "team": score_data.team,
        "server": serving_before,
        "set": set_before,
        "ts": datetime.utcnow().isoformat(),
    })

    await apply_new_state(match, new_state, history, db, point_log=new_log)

    return {"success": True, "match": match.to_dict(include_stats=True)}


@app.get("/faq", response_class=HTMLResponse)
async def faq_page(request: Request):
    """Public FAQ — how to score, share links, doubles pairings, etc."""
    return templates.TemplateResponse("faq.html", {"request": request})


@app.get("/i18n.js")
async def i18n_js(request: Request):
    """Current-language strings for the browser (window.T / window.LANG).

    Loaded synchronously before common.js so dynamic JS renders never race
    the catalog. Vary on the cookie, so switching languages busts caches.
    """
    lang = get_lang(request)
    payload = json.dumps(strings_for(lang), ensure_ascii=False)
    body = f"window.LANG={json.dumps(lang)};window.T={payload};"
    return Response(
        content=body,
        media_type="application/javascript; charset=utf-8",
        headers={"Cache-Control": "no-cache"},
    )


# Match Day routes
@app.get("/archive", response_class=HTMLResponse)
async def archive_page(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)

    from sqlalchemy import or_
    query = select(MatchDay).order_by(MatchDay.created_at.desc())
    if user and user.is_superadmin:
        pass  # superadmin sees all
    elif user:
        query = query.where(or_(MatchDay.is_public == True, MatchDay.owner_id == user.id))
    else:
        query = query.where(MatchDay.is_public == True)

    result = await db.execute(query)
    match_days = result.scalars().all()

    archive = []
    for md in match_days:
        matches_result = await db.execute(
            select(Match).where(Match.match_day_id == md.id)
        )
        matches = matches_result.scalars().all()
        archive.append({**md.to_dict(), **compute_matchday_stats(matches)})

    return templates.TemplateResponse("archive.html", {
        "request": request,
        "match_days": archive,
        "user": user.to_dict() if user else None,
    })


@app.get("/matchday/{match_day_id}", response_class=HTMLResponse)
async def match_day_page(request: Request, match_day_id: str, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/admin/login", status_code=302)

    result = await db.execute(select(MatchDay).where(MatchDay.id == match_day_id))
    match_day = result.scalar_one_or_none()
    if not match_day:
        raise HTTPException(status_code=404, detail="Match day not found")

    if not await is_owner_or_superadmin(user, match_day):
        raise HTTPException(status_code=403, detail="Access denied")

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
    user = await get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    name = f"{data.team_a_name} vs {data.team_b_name}"

    match_day = MatchDay(
        name=name,
        format=data.format,
        players=data.players,
        team_a_name=data.team_a_name,
        team_b_name=data.team_b_name,
        team_a_players=data.team_a_players,
        team_b_players=data.team_b_players,
        club_a_id=data.club_a_id,
        club_b_id=data.club_b_id,
        category=data.category,
        owner_id=user.id,
        is_public=data.is_public,
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
    result = await db.execute(select(MatchDay).where(MatchDay.id == match_day_id))
    match_day = result.scalar_one_or_none()
    if not match_day:
        raise HTTPException(status_code=404, detail="Match day not found")

    # Owner/superadmin session, or the match day's scorer token (the on-court
    # scorer via /scoreday/{token} is exactly who sets the doubles pairings).
    user = await get_current_user(request, db)
    authorized = user is not None and await is_owner_or_superadmin(user, match_day)
    if not authorized:
        token = get_scorer_token(request)
        if token and match_day.scorer_token and secrets.compare_digest(token, match_day.scorer_token):
            authorized = True
    if not authorized:
        raise HTTPException(status_code=401, detail="Authentication required")

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
async def list_match_days(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)

    from sqlalchemy import or_
    query = select(MatchDay).order_by(MatchDay.created_at.desc())
    if user and user.is_superadmin:
        pass
    elif user:
        query = query.where(or_(MatchDay.is_public == True, MatchDay.owner_id == user.id))
    else:
        query = query.where(MatchDay.is_public == True)

    result = await db.execute(query)
    match_days = result.scalars().all()

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


async def _match_day_bundle(match_day: MatchDay, db: AsyncSession, private: bool) -> dict:
    matches_result = await db.execute(
        select(Match).where(Match.match_day_id == match_day.id).order_by(Match.match_number)
    )
    matches = [m.to_dict() for m in matches_result.scalars().all()]
    md = match_day.to_dict_private() if private else match_day.to_dict()
    return {"match_day": md, "matches": matches}


@app.get("/api/matchdays/share/{share_code}")
async def get_match_day_by_share_code(share_code: str, db: AsyncSession = Depends(get_db)):
    """Public spectator read of a match day by its 8-char share code."""
    result = await db.execute(select(MatchDay).where(MatchDay.share_code == share_code))
    match_day = result.scalar_one_or_none()
    if not match_day:
        raise HTTPException(status_code=404, detail="Match day not found")
    return await _match_day_bundle(match_day, db, private=False)


@app.get("/api/matchdays/by-scorer-token/{scorer_token}")
async def get_match_day_by_scorer_token(scorer_token: str, db: AsyncSession = Depends(get_db)):
    """Scorer read of a match day by its 12-char scorer token.

    Returns the private view (includes scorer_token) so the client can then
    score its matches with the X-Scorer-Token header.
    """
    result = await db.execute(select(MatchDay).where(MatchDay.scorer_token == scorer_token))
    match_day = result.scalar_one_or_none()
    if not match_day:
        raise HTTPException(status_code=404, detail="Invalid scorer token")
    return await _match_day_bundle(match_day, db, private=True)


@app.delete("/api/matchdays/{match_day_id}")
async def delete_match_day(match_day_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    result = await db.execute(select(MatchDay).where(MatchDay.id == match_day_id))
    match_day = result.scalar_one_or_none()
    if not match_day:
        raise HTTPException(status_code=404, detail="Match day not found")

    if not await is_owner_or_superadmin(user, match_day):
        raise HTTPException(status_code=403, detail="Access denied")

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


# ==================== User Management (superadmin only) ====================

@app.get("/api/admin/users")
async def admin_list_users(request: Request, db: AsyncSession = Depends(get_db)):
    await require_superadmin(request, db)

    users_result = await db.execute(select(User).order_by(User.created_at))
    users = users_result.scalars().all()

    counts_result = await db.execute(
        select(MatchDay.owner_id, func.count()).group_by(MatchDay.owner_id)
    )
    md_counts = dict(counts_result.all())

    return {"users": [
        {**u.to_dict(), "match_days": md_counts.get(u.id, 0)} for u in users
    ]}


@app.post("/api/admin/users/{user_id}/reset-password")
async def admin_reset_password(user_id: str, payload: AdminPasswordReset, request: Request, db: AsyncSession = Depends(get_db)):
    await require_superadmin(request, db)

    if len(payload.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target.is_superadmin:
        # The superadmin password is env-synced (ADMIN_PASSWORD) — keep one source of truth.
        raise HTTPException(status_code=400, detail="Superadmin password is managed via ADMIN_PASSWORD")

    target.password_hash = hash_password(payload.password)
    # Force re-login everywhere with the new password
    sessions = await db.execute(select(AdminSession).where(AdminSession.user_id == target.id))
    for sess in sessions.scalars().all():
        await db.delete(sess)
    await db.commit()

    return {"success": True}


@app.delete("/api/admin/users/{user_id}")
async def admin_delete_user(user_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    admin = await require_superadmin(request, db)

    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="You cannot delete your own account")

    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target.is_superadmin:
        raise HTTPException(status_code=400, detail="The superadmin account cannot be deleted")

    # Hand the user's match days over to the superadmin instead of deleting data
    mds = await db.execute(select(MatchDay).where(MatchDay.owner_id == target.id))
    reassigned = 0
    for md in mds.scalars().all():
        md.owner_id = admin.id
        reassigned += 1

    sessions = await db.execute(select(AdminSession).where(AdminSession.user_id == target.id))
    for sess in sessions.scalars().all():
        await db.delete(sess)

    await db.delete(target)
    await db.commit()

    return {"success": True, "match_days_reassigned": reassigned}


# ==================== WTB Club & Player Integration ====================

@app.post("/api/admin/sync-clubs")
async def sync_wtb_clubs(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)
    if not user or not user.is_superadmin:
        raise HTTPException(status_code=403, detail="Superadmin access required")

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

    user = await get_current_user(request, db)
    if not user or not user.is_superadmin:
        raise HTTPException(status_code=403, detail="Superadmin access required")

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
                        "total_pages": event["total_pages"],
                        "clubs_so_far": event["clubs_so_far"],
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
    category: str = "Herren",
    db: AsyncSession = Depends(get_db)
):
    user = await get_current_user(request, db)
    if not user or not user.is_superadmin:
        raise HTTPException(status_code=403, detail="Superadmin access required")

    result = await db.execute(select(Club).where(Club.id == club_id))
    club = result.scalar_one_or_none()
    if not club:
        raise HTTPException(status_code=404, detail="Club not found")

    try:
        players_data = await scrape_club_players(club.wtb_id, category=category)

        # Delete only players for this specific category to avoid clobbering others
        existing = (await db.execute(
            select(Player).where(Player.club_id == club_id, Player.category == category)
        )).scalars().all()
        for player in existing:
            await db.delete(player)

        for player_data in players_data:
            db.add(create_player_from_data(player_data, club_id))

        club.last_synced = datetime.utcnow()
        await db.commit()

        return {
            "success": True,
            "synced": len(players_data),
            "club_name": club.name,
            "category": category,
            "message": f"Synced {len(players_data)} {category} players for {club.name}",
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
async def get_club_players(
    club_id: str,
    category: str = "Herren",
    refresh: bool = False,
    db: AsyncSession = Depends(get_db)
):
    """
    Return players for a club filtered by category, sorted by ranking ASC (nulls last).
    Auto-scrapes on first load or when data is older than 7 days.
    Pass ?refresh=true to force a re-scrape regardless of age.
    """
    from datetime import timedelta
    club_result = await db.execute(select(Club).where(Club.id == club_id))
    club = club_result.scalar_one_or_none()
    if not club:
        raise HTTPException(status_code=404, detail="Club not found")

    count_result = await db.execute(
        select(func.count()).select_from(Player).where(
            Player.club_id == club_id, Player.category == category
        )
    )
    player_count = count_result.scalar()

    stale = (
        club.last_synced is None or
        club.last_synced < datetime.utcnow() - timedelta(days=7)
    )

    if player_count == 0 or refresh or stale:
        try:
            players_data = await scrape_club_players(club.wtb_id, category=category)
            if players_data:
                # Replace stale records for this category only
                existing = (await db.execute(
                    select(Player).where(Player.club_id == club_id, Player.category == category)
                )).scalars().all()
                for p in existing:
                    await db.delete(p)
                for player_data in players_data:
                    db.add(create_player_from_data(player_data, club_id))
                club.last_synced = datetime.utcnow()
                await db.commit()
        except Exception as e:
            logger.warning(f"Auto-sync players (category={category}) for club {club_id} failed: {e}")
            await db.rollback()

    result = await db.execute(
        select(Player)
        .where(Player.club_id == club_id, Player.category == category)
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


# ==================== WTB Fixture Import ====================

@app.get("/api/clubs/{club_id}/teams")
async def get_club_teams(
    club_id: str,
    category: str = "Herren",
    db: AsyncSession = Depends(get_db)
):
    """Get teams for a club from WTB. Requires the club to exist in DB."""
    result = await db.execute(select(Club).where(Club.id == club_id))
    club = result.scalar_one_or_none()
    if not club:
        raise HTTPException(status_code=404, detail="Club not found")

    category_filter = category if category else None
    teams = await scrape_club_teams(club.wtb_id, category_filter=category_filter)
    return {"club_id": club_id, "wtb_id": club.wtb_id, "club_name": club.name, "teams": teams}


@app.get("/api/clubs/{club_id}/teams/{team_id}/fixtures")
async def get_team_fixtures(
    club_id: str,
    team_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Get fixtures for a team, with imported status for each."""
    result = await db.execute(select(Club).where(Club.id == club_id))
    club = result.scalar_one_or_none()
    if not club:
        raise HTTPException(status_code=404, detail="Club not found")

    fixtures = await scrape_team_fixtures(club.wtb_id, team_id)

    # Check which fixtures are already imported
    meeting_ids = [f["meeting_id"] for f in fixtures if f["meeting_id"]]
    imported_ids = set()
    if meeting_ids:
        imported_result = await db.execute(
            select(MatchDay.wtb_meeting_id).where(MatchDay.wtb_meeting_id.in_(meeting_ids))
        )
        imported_ids = {row[0] for row in imported_result.all()}

    for f in fixtures:
        f["imported"] = f["meeting_id"] in imported_ids

    return {"club_id": club_id, "team_id": team_id, "fixtures": fixtures}


@app.post("/api/admin/import-fixture")
async def import_fixture(
    data: FixtureImport,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Import a WTB fixture as a MatchDay.
    - Played fixtures: scrapes Spielbericht for full match data (players, scores)
    - Future fixtures: creates shell MatchDay (no players/matches yet)
    """
    user = await get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    # Check if already imported
    existing = await db.execute(
        select(MatchDay).where(MatchDay.wtb_meeting_id == data.meeting_id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Fixture already imported")

    # Parse scheduled_date
    scheduled_date = None
    if data.scheduled_date:
        try:
            scheduled_date = datetime.fromisoformat(data.scheduled_date)
        except ValueError:
            pass

    name = f"{data.home_team} vs {data.away_team}"

    match_day = MatchDay(
        name=name,
        format=data.format,
        team_a_name=data.home_team,
        team_b_name=data.away_team,
        scheduled_date=scheduled_date,
        venue=data.venue,
        wtb_meeting_id=data.meeting_id,
        wtb_team_id=data.wtb_team_id,
        wtb_club_id=data.wtb_club_id,
        owner_id=user.id,
    )
    db.add(match_day)
    await db.flush()  # Get the match_day.id before creating matches

    matches_created = []

    # For played fixtures, scrape the Spielbericht for full match data
    if data.is_played and data.spielbericht_url:
        report = await scrape_spielbericht(data.spielbericht_url)
        if report:
            match_number = 1

            def player_display(p):
                return f"{p['name']} (LK {p['lk']})" if p.get("lk") else p["name"]

            # Create singles matches with scores
            for sm in report["singles"]:
                home_p = sm["home_players"]
                away_p = sm["away_players"]

                # Build score state from set scores
                state = create_initial_state()
                games = [[0, 0], [0, 0], [0, 0]]
                for i, s in enumerate(sm["sets"][:3]):
                    games[i] = s
                sets_a = sum(1 for s in sm["sets"] if s[0] > s[1])
                sets_b = sum(1 for s in sm["sets"] if s[1] > s[0])
                state["games"] = games
                state["sets"] = [sets_a, sets_b]
                state["current_set"] = len(sm["sets"]) - 1
                state["winner"] = sm["winner"]
                state["points"] = [0, 0]

                match = Match(
                    match_day_id=match_day.id,
                    match_number=match_number,
                    match_type="singles",
                    team_a_name=data.home_team,
                    team_b_name=data.away_team,
                    player_a1=player_display(home_p[0]) if home_p else None,
                    player_b1=player_display(away_p[0]) if away_p else None,
                    score_state=state,
                    history=[],
                    finished_at=datetime.utcnow() if sm["winner"] is not None else None,
                )
                db.add(match)
                matches_created.append(match)
                match_number += 1

            # Create doubles matches with scores
            for dm in report["doubles"]:
                home_p = dm["home_players"]
                away_p = dm["away_players"]

                state = create_initial_state()
                games = [[0, 0], [0, 0], [0, 0]]
                for i, s in enumerate(dm["sets"][:3]):
                    games[i] = s
                sets_a = sum(1 for s in dm["sets"] if s[0] > s[1])
                sets_b = sum(1 for s in dm["sets"] if s[1] > s[0])
                state["games"] = games
                state["sets"] = [sets_a, sets_b]
                state["current_set"] = len(dm["sets"]) - 1
                state["winner"] = dm["winner"]
                state["points"] = [0, 0]

                match = Match(
                    match_day_id=match_day.id,
                    match_number=match_number,
                    match_type="doubles",
                    team_a_name=data.home_team,
                    team_b_name=data.away_team,
                    player_a1=player_display(home_p[0]) if len(home_p) > 0 else None,
                    player_a2=player_display(home_p[1]) if len(home_p) > 1 else None,
                    player_b1=player_display(away_p[0]) if len(away_p) > 0 else None,
                    player_b2=player_display(away_p[1]) if len(away_p) > 1 else None,
                    score_state=state,
                    history=[],
                    finished_at=datetime.utcnow() if dm["winner"] is not None else None,
                )
                db.add(match)
                matches_created.append(match)
                match_number += 1

            # Store player lists on the match day
            all_home = []
            all_away = []
            for sm in report["singles"]:
                for p in sm["home_players"]:
                    all_home.append(player_display(p))
                for p in sm["away_players"]:
                    all_away.append(player_display(p))
            match_day.team_a_players = all_home
            match_day.team_b_players = all_away
            match_day.players = all_home + all_away

    await db.commit()
    await db.refresh(match_day)

    return {
        "success": True,
        "match_day": match_day.to_dict(),
        "matches_imported": len(matches_created),
    }


@app.post("/api/matchdays/{match_day_id}/setup")
async def setup_match_day(
    match_day_id: str,
    data: MatchDaySetup,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    user = await get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    result = await db.execute(select(MatchDay).where(MatchDay.id == match_day_id))
    match_day = result.scalar_one_or_none()
    if not match_day:
        raise HTTPException(status_code=404, detail="Match day not found")

    if not await is_owner_or_superadmin(user, match_day):
        raise HTTPException(status_code=403, detail="Access denied")

    # Check no matches exist yet
    existing_matches = await db.execute(
        select(Match).where(Match.match_day_id == match_day_id)
    )
    if existing_matches.scalars().first():
        raise HTTPException(status_code=400, detail="Match day already has matches")

    # Update match day with player info
    match_day.format = data.format
    match_day.team_a_players = data.team_a_players
    match_day.team_b_players = data.team_b_players
    match_day.players = data.team_a_players + data.team_b_players

    # Create singles matches
    player_count = 6 if data.format == "6_person" else 4
    team_a = data.team_a_players[:player_count]
    team_b = data.team_b_players[:player_count]

    matches = []
    for i in range(player_count):
        match = Match(
            match_day_id=match_day.id,
            match_number=i + 1,
            match_type="singles",
            team_a_name=match_day.team_a_name,
            team_b_name=match_day.team_b_name,
            player_a1=team_a[i] if i < len(team_a) else f"Player A{i+1}",
            player_b1=team_b[i] if i < len(team_b) else f"Player B{i+1}",
            score_state=create_initial_state(),
            history=[]
        )
        db.add(match)
        matches.append(match)

    await db.commit()
    await db.refresh(match_day)

    return {
        "success": True,
        "match_day": match_day.to_dict(),
        "matches": [m.to_dict() for m in matches]
    }


@app.post("/api/admin/sync-fixtures")
async def sync_fixtures(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Re-scrape fixtures for a team and update imported MatchDays with date/venue changes."""
    user = await get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    # Get wtb_club_id and wtb_team_id from query params
    wtb_club_id = request.query_params.get("wtb_club_id")
    wtb_team_id = request.query_params.get("wtb_team_id")

    if not wtb_club_id or not wtb_team_id:
        raise HTTPException(status_code=400, detail="wtb_club_id and wtb_team_id required")

    # Scrape current fixtures
    fixtures = await scrape_team_fixtures(wtb_club_id, wtb_team_id)

    # Find imported MatchDays for this team
    result = await db.execute(
        select(MatchDay).where(
            MatchDay.wtb_team_id == wtb_team_id,
            MatchDay.wtb_club_id == wtb_club_id,
        )
    )
    imported = {md.wtb_meeting_id: md for md in result.scalars().all()}

    changes = []
    for fixture in fixtures:
        mid = fixture["meeting_id"]
        if mid not in imported:
            continue

        md = imported[mid]
        fixture_date = None
        if fixture["scheduled_date"]:
            try:
                fixture_date = datetime.fromisoformat(fixture["scheduled_date"])
            except ValueError:
                pass

        # Check for date changes
        if fixture_date and md.scheduled_date and fixture_date != md.scheduled_date:
            changes.append({
                "meeting_id": mid,
                "field": "scheduled_date",
                "old": md.scheduled_date.isoformat(),
                "new": fixture_date.isoformat(),
                "name": md.name,
            })
            md.scheduled_date = fixture_date

        # Check for venue changes
        if fixture["venue"] and fixture["venue"] != (md.venue or ""):
            changes.append({
                "meeting_id": mid,
                "field": "venue",
                "old": md.venue or "",
                "new": fixture["venue"],
                "name": md.name,
            })
            md.venue = fixture["venue"]

    if changes:
        await db.commit()

    return {"success": True, "changes": changes}


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

        while True:
            try:
                await websocket.receive_text()
            except WebSocketDisconnect:
                break
    finally:
        manager.disconnect(websocket, match_id)
