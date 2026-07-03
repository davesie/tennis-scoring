from sqlalchemy import Column, Integer, String, Boolean, DateTime, JSON, ForeignKey, Index
from sqlalchemy.orm import relationship
from datetime import datetime, timedelta
import uuid

from .database import Base
from .scoring import create_initial_state, format_set_cells, get_point_display, compute_match_stats


def generate_uuid():
    return str(uuid.uuid4())


def generate_share_code():
    return str(uuid.uuid4())[:8]


def generate_scorer_token():
    return str(uuid.uuid4())[:12]


def generate_session_expiry():
    return datetime.utcnow() + timedelta(days=7)


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=generate_uuid)
    email = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    display_name = Column(String, nullable=True)
    is_superadmin = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login_at = Column(DateTime, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "email": self.email,
            "display_name": self.display_name,
            "is_superadmin": self.is_superadmin,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_login_at": self.last_login_at.isoformat() if self.last_login_at else None,
        }


class AdminSession(Base):
    __tablename__ = "admin_sessions"

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, default=generate_session_expiry, nullable=False)


class MatchDay(Base):
    __tablename__ = "match_days"

    id = Column(String, primary_key=True, default=generate_uuid)
    share_code = Column(String, unique=True, default=generate_share_code, index=True)
    scorer_token = Column(String, unique=True, default=generate_scorer_token, index=True)
    name = Column(String, default="Match Day")
    format = Column(String, default="6_person")  # "6_person" or "4_person"

    # Players (stored as JSON list)
    players = Column(JSON, default=list)  # List of player names

    # Team assignments (for team-based scoring)
    team_a_name = Column(String, default="Team A")
    team_b_name = Column(String, default="Team B")
    team_a_players = Column(JSON, default=list)  # Player names on Team A
    team_b_players = Column(JSON, default=list)  # Player names on Team B

    # Club references (for loading full roster in doubles pairing)
    club_a_id = Column(String, ForeignKey("clubs.id"), nullable=True)
    club_b_id = Column(String, ForeignKey("clubs.id"), nullable=True)

    # Team category (WTB league category, e.g. "Herren", "Damen", "Herren 30")
    category = Column(String, nullable=True)

    # Ownership and visibility
    owner_id = Column(String, ForeignKey("users.id"), nullable=True)
    is_public = Column(Boolean, default=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    # WTB fixture import fields
    scheduled_date = Column(DateTime, nullable=True)  # Fixture date/time from WTB
    venue = Column(String, nullable=True)  # Spielort
    wtb_meeting_id = Column(String, nullable=True, unique=True, index=True)  # From Spielbericht links
    wtb_team_id = Column(String, nullable=True)  # Team ID from URL (e.g. "3496556")
    wtb_club_id = Column(String, nullable=True)  # Club wtb_id (e.g. "20099")

    def to_dict(self):
        return {
            "id": self.id,
            "share_code": self.share_code,
            "name": self.name,
            "format": self.format,
            "players": self.players,
            "team_a_name": self.team_a_name,
            "team_b_name": self.team_b_name,
            "team_a_players": self.team_a_players,
            "team_b_players": self.team_b_players,
            "club_a_id": self.club_a_id,
            "club_b_id": self.club_b_id,
            "category": self.category,
            "owner_id": self.owner_id,
            "is_public": self.is_public,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "scheduled_date": self.scheduled_date.isoformat() if self.scheduled_date else None,
            "venue": self.venue,
            "wtb_meeting_id": self.wtb_meeting_id,
            "wtb_team_id": self.wtb_team_id,
            "wtb_club_id": self.wtb_club_id,
        }

    def to_dict_private(self):
        return {**self.to_dict(), "scorer_token": self.scorer_token}


class Match(Base):
    __tablename__ = "matches"

    id = Column(String, primary_key=True, default=generate_uuid)
    share_code = Column(String, unique=True, default=generate_share_code, index=True)
    scorer_token = Column(String, unique=True, default=generate_scorer_token, index=True)
    match_day_id = Column(String, ForeignKey("match_days.id"), nullable=True)
    match_number = Column(Integer, nullable=True)  # Order in match day
    match_type = Column(String, default="singles")  # singles or doubles

    # Team names
    team_a_name = Column(String, default="Team A")
    team_b_name = Column(String, default="Team B")

    # Player names for singles
    player_a1 = Column(String, nullable=True)
    player_b1 = Column(String, nullable=True)

    # Additional players for doubles
    player_a2 = Column(String, nullable=True)
    player_b2 = Column(String, nullable=True)

    # Current score state (uses scoring.create_initial_state as single source of truth)
    score_state = Column(JSON, default=create_initial_state)

    # Match history for undo
    history = Column(JSON, default=list)

    # Append-only per-point log for statistics (each: winner, server, set, outcome, ts)
    point_log = Column(JSON, default=list)

    # Match settings
    best_of = Column(Integer, default=3)  # Best of 3 sets
    super_tiebreak_final_set = Column(Boolean, default=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)  # Set when first point is scored
    finished_at = Column(DateTime, nullable=True)

    def get_duration_seconds(self):
        """Calculate match duration in seconds."""
        if self.started_at and self.finished_at:
            return int((self.finished_at - self.started_at).total_seconds())
        return None

    def get_duration_formatted(self):
        """Get match duration as formatted string (e.g., '1h 23m')."""
        seconds = self.get_duration_seconds()
        if seconds is None:
            return None
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        if hours > 0:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"

    def to_dict(self, include_stats=False):
        d = {
            "id": self.id,
            "share_code": self.share_code,
            "match_day_id": self.match_day_id,
            "match_number": self.match_number,
            "match_type": self.match_type,
            "team_a_name": self.team_a_name,
            "team_b_name": self.team_b_name,
            "player_a1": self.player_a1,
            "player_b1": self.player_b1,
            "player_a2": self.player_a2,
            "player_b2": self.player_b2,
            "score_state": self.score_state,
            "score_cells": format_set_cells(self.score_state or {}),
            "point_display": dict(zip(("a", "b"), get_point_display(self.score_state or {}))),
            "best_of": self.best_of,
            "super_tiebreak_final_set": self.super_tiebreak_final_set,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "duration_seconds": self.get_duration_seconds(),
            "duration_formatted": self.get_duration_formatted(),
        }
        finished = (self.score_state or {}).get("winner") is not None
        # Stats summary is public once the match is finished (post-match summary
        # for everyone); during play it is sent only to scorer-facing responses.
        if include_stats or finished:
            d["stats"] = compute_match_stats(self.point_log or [])
        # The raw point log goes only to the scorer (used to drive the live panel).
        if include_stats:
            d["point_log"] = self.point_log or []
        return d


class Club(Base):
    """WTB Tennis Club."""
    __tablename__ = "clubs"

    id = Column(String, primary_key=True, default=generate_uuid)
    wtb_id = Column(String, unique=True, nullable=False, index=True)  # e.g., "20004"
    name = Column(String, nullable=False)  # e.g., "TA TSV Crailsheim"
    location = Column(String)  # e.g., "Crailsheim"
    district = Column(String)  # e.g., "WTB Bezirk A"
    url = Column(String)  # Full URL to club page
    last_synced = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationship
    players = relationship("Player", back_populates="club", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id,
            "wtb_id": self.wtb_id,
            "name": self.name,
            "location": self.location,
            "district": self.district,
            "last_synced": self.last_synced.isoformat() if self.last_synced else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Player(Base):
    """WTB Registered Player (Herren only)."""
    __tablename__ = "players"

    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String, nullable=False)  # e.g., "Max Mustermann"
    birth_year = Column(Integer, nullable=True)  # e.g., 1995
    category = Column(String, default="Herren")  # Only "Herren" for now
    wtb_id_nummer = Column(String, nullable=True)  # ID number from WTB
    ranking = Column(Integer, nullable=True)  # Rang from WTB (lower = higher seed)
    lk = Column(String, nullable=True)  # Leistungsklasse from WTB (e.g., "23", "NT")
    is_captain = Column(Boolean, default=False)  # MF = Mannschaftsführer (team captain)
    club_id = Column(String, ForeignKey("clubs.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationship
    club = relationship("Club", back_populates="players")

    # Index for fast name searching
    __table_args__ = (
        Index('ix_players_name_search', 'name'),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "birth_year": self.birth_year,
            "category": self.category,
            "wtb_id_nummer": self.wtb_id_nummer,
            "ranking": self.ranking,
            "lk": self.lk,
            "is_captain": self.is_captain,
            "club_id": self.club_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
