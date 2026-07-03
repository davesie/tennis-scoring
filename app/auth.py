"""Authentication helpers for the Tennis Scoring app."""

import os
import secrets
from datetime import datetime
from typing import Optional
from dotenv import load_dotenv

import bcrypt as _bcrypt
from fastapi import Request, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from .database import get_db
from .models import AdminSession, Match, MatchDay, User

load_dotenv()

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
SESSION_COOKIE = "admin_session"


def hash_password(password: str) -> str:
    return _bcrypt.hashpw(password.encode(), _bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _bcrypt.checkpw(password.encode(), password_hash.encode())
    except Exception:
        return False


async def create_session(db: AsyncSession, user_id: str) -> AdminSession:
    session = AdminSession(user_id=user_id)
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def get_current_user(request: Request, db: AsyncSession) -> Optional[User]:
    session_id = request.cookies.get(SESSION_COOKIE)
    if not session_id:
        return None

    result = await db.execute(
        select(User)
        .join(AdminSession, AdminSession.user_id == User.id)
        .where(
            AdminSession.id == session_id,
            AdminSession.expires_at > datetime.utcnow()
        )
    )
    return result.scalar_one_or_none()


async def delete_session(session_id: str, db: AsyncSession) -> None:
    result = await db.execute(
        select(AdminSession).where(AdminSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    if session:
        await db.delete(session)
        await db.commit()


def get_scorer_token(request: Request) -> Optional[str]:
    token = request.headers.get("X-Scorer-Token")
    if token:
        return token
    return request.query_params.get("scorer_token")


async def require_user(request: Request, db: AsyncSession) -> User:
    user = await get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


async def require_superadmin(request: Request, db: AsyncSession) -> User:
    user = await require_user(request, db)
    if not user.is_superadmin:
        raise HTTPException(status_code=403, detail="Superadmin access required")
    return user


async def is_owner_or_superadmin(user: Optional[User], match_day: MatchDay) -> bool:
    if not user:
        return False
    if user.is_superadmin:
        return True
    return match_day.owner_id == user.id


async def verify_scorer_for_match(
    match_id: str,
    request: Request,
    db: AsyncSession
) -> Match:
    """
    Verify that the request has valid scorer credentials for the given match.

    Authorization succeeds if:
    1. The user is the match day owner or superadmin, OR
    2. The scorer_token matches the match's scorer_token, OR
    3. The match is part of a match day and the token matches the match day's scorer_token
    """
    result = await db.execute(select(Match).where(Match.id == match_id))
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    user = await get_current_user(request, db)

    if user:
        if user.is_superadmin:
            return match
        if match.match_day_id:
            md_result = await db.execute(
                select(MatchDay).where(MatchDay.id == match.match_day_id)
            )
            match_day = md_result.scalar_one_or_none()
            if match_day and match_day.owner_id == user.id:
                return match

    token = get_scorer_token(request)
    if not token:
        raise HTTPException(
            status_code=401,
            detail="Scorer authentication required. Provide X-Scorer-Token header."
        )

    if match.scorer_token and secrets.compare_digest(token, match.scorer_token):
        return match

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
    return await verify_scorer_for_match(match_id, request, db)
