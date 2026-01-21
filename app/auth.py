"""Authentication helpers for the Tennis Scoring app."""

import os
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Request, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from .database import get_db
from .models import AdminSession, Match, MatchDay

# Admin password from environment variable
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")

# Cookie name for admin sessions
ADMIN_SESSION_COOKIE = "admin_session"


def verify_admin_password(password: str) -> bool:
    """Check if the provided password matches the admin password."""
    if not ADMIN_PASSWORD:
        return False
    return secrets.compare_digest(password, ADMIN_PASSWORD)


async def create_admin_session(db: AsyncSession) -> AdminSession:
    """Create a new admin session."""
    session = AdminSession()
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def get_admin_session(request: Request, db: AsyncSession) -> Optional[AdminSession]:
    """Get the current admin session from the request cookie."""
    session_id = request.cookies.get(ADMIN_SESSION_COOKIE)
    if not session_id:
        return None

    result = await db.execute(
        select(AdminSession).where(
            AdminSession.id == session_id,
            AdminSession.expires_at > datetime.utcnow()
        )
    )
    return result.scalar_one_or_none()


async def delete_admin_session(session_id: str, db: AsyncSession) -> None:
    """Delete an admin session."""
    result = await db.execute(
        select(AdminSession).where(AdminSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    if session:
        await db.delete(session)
        await db.commit()


def get_scorer_token(request: Request) -> Optional[str]:
    """Extract scorer token from request header or query parameter."""
    # Check header first
    token = request.headers.get("X-Scorer-Token")
    if token:
        return token

    # Fallback to query parameter
    return request.query_params.get("scorer_token")


async def require_admin(request: Request, db: AsyncSession = Depends(get_db)) -> AdminSession:
    """Dependency that requires admin authentication."""
    session = await get_admin_session(request, db)
    if not session:
        raise HTTPException(status_code=401, detail="Admin authentication required")
    return session


async def verify_scorer_for_match(
    match_id: str,
    request: Request,
    db: AsyncSession
) -> Match:
    """
    Verify that the request has valid scorer credentials for the given match.

    Authorization succeeds if:
    1. The user is an admin (has valid admin session), OR
    2. The scorer_token matches the match's scorer_token, OR
    3. The match is part of a match day and the token matches the match day's scorer_token

    Returns the match if authorized, raises HTTPException otherwise.
    """
    # First, get the match
    result = await db.execute(select(Match).where(Match.id == match_id))
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    # Check if user is admin
    admin_session = await get_admin_session(request, db)
    if admin_session:
        return match

    # Get the scorer token from the request
    token = get_scorer_token(request)
    if not token:
        raise HTTPException(
            status_code=401,
            detail="Scorer authentication required. Provide X-Scorer-Token header."
        )

    # Check if token matches match's own scorer token
    if match.scorer_token and secrets.compare_digest(token, match.scorer_token):
        return match

    # Check if match is part of a match day and token matches match day's scorer token
    if match.match_day_id:
        md_result = await db.execute(
            select(MatchDay).where(MatchDay.id == match.match_day_id)
        )
        match_day = md_result.scalar_one_or_none()
        if match_day and match_day.scorer_token and secrets.compare_digest(token, match_day.scorer_token):
            return match

    raise HTTPException(
        status_code=403,
        detail="Invalid scorer token for this match"
    )


async def require_scorer_for_match(
    match_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> Match:
    """Dependency that requires scorer authorization for a specific match."""
    return await verify_scorer_for_match(match_id, request, db)
