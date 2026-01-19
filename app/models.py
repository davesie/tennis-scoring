from sqlalchemy import Column, Integer, String, Boolean, DateTime, JSON, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid

from .database import Base


def generate_uuid():
    return str(uuid.uuid4())


def generate_share_code():
    return str(uuid.uuid4())[:8]


class MatchDay(Base):
    __tablename__ = "match_days"

    id = Column(String, primary_key=True, default=generate_uuid)
    share_code = Column(String, unique=True, default=generate_share_code, index=True)
    name = Column(String, default="Match Day")
    format = Column(String, default="6_person")  # "6_person" or "4_person"

    # Players (stored as JSON list)
    players = Column(JSON, default=list)  # List of player names

    # Team assignments (for team-based scoring)
    team_a_name = Column(String, default="Team A")
    team_b_name = Column(String, default="Team B")
    team_a_players = Column(JSON, default=list)  # Player names on Team A
    team_b_players = Column(JSON, default=list)  # Player names on Team B

    created_at = Column(DateTime, default=datetime.utcnow)

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
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Match(Base):
    __tablename__ = "matches"

    id = Column(String, primary_key=True, default=generate_uuid)
    share_code = Column(String, unique=True, default=generate_share_code, index=True)
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

    # Current score state
    score_state = Column(JSON, default=lambda: {
        "points": [0, 0],  # Current game points (0, 1, 2, 3 = 0, 15, 30, 40)
        "games": [[0, 0], [0, 0], [0, 0]],  # Games per set
        "sets": [0, 0],  # Sets won
        "current_set": 0,  # 0-indexed
        "serving": 0,  # 0 = Team A, 1 = Team B
        "is_tiebreak": False,
        "is_super_tiebreak": False,
        "tiebreak_points": [0, 0],
        "winner": None,  # None, 0, or 1
        "deuce_advantage": None  # None, 0, or 1
    })

    # Match history for undo
    history = Column(JSON, default=list)

    # Match settings
    best_of = Column(Integer, default=3)  # Best of 3 sets
    super_tiebreak_final_set = Column(Boolean, default=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)

    def to_dict(self):
        return {
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
            "best_of": self.best_of,
            "super_tiebreak_final_set": self.super_tiebreak_final_set,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }
