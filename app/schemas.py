from pydantic import BaseModel
from typing import Optional, List, Literal
from datetime import datetime


class MatchCreate(BaseModel):
    match_type: str = "singles"
    team_a_name: str = "Team A"
    team_b_name: str = "Team B"
    player_a1: Optional[str] = None
    player_b1: Optional[str] = None
    player_a2: Optional[str] = None  # For doubles
    player_b2: Optional[str] = None  # For doubles
    best_of: int = 3
    super_tiebreak_final_set: bool = True


class ScorePoint(BaseModel):
    team: int  # 0 or 1


class ScoreGame(BaseModel):
    team: int  # 0 or 1


class PointOutcome(BaseModel):
    """Optional classification of how the most recent point ended."""
    outcome: Literal["ace", "winner", "unforced_error", "forced_error", "double_fault"]


class SetInitialServer(BaseModel):
    serving: int  # 0 or 1


class UserRegister(BaseModel):
    email: str
    password: str
    display_name: Optional[str] = None


class UserLogin(BaseModel):
    email: str
    password: str


class MatchDayCreate(BaseModel):
    format: str = "6_person"  # "6_person" or "4_person"
    players: List[str] = []
    team_a_name: str = "Team A"
    team_b_name: str = "Team B"
    team_a_players: List[str] = []
    team_b_players: List[str] = []
    club_a_id: Optional[str] = None
    club_b_id: Optional[str] = None
    category: Optional[str] = None
    is_public: bool = True


class DoublesPairingCreate(BaseModel):
    player_a1: str
    player_a2: str
    player_b1: str
    player_b2: str


class DoublesCreate(BaseModel):
    pairings: List[DoublesPairingCreate]


class MatchPlayersUpdate(BaseModel):
    player_a1: Optional[str] = None
    player_a2: Optional[str] = None
    player_b1: Optional[str] = None
    player_b2: Optional[str] = None


class MatchScoreSet(BaseModel):
    """Set final score directly for matches not watched live."""
    sets: List[List[int]]  # e.g., [[6, 4], [3, 6], [6, 2]] for a 2-1 win
    winner: int  # 0 or 1


class FixtureImport(BaseModel):
    meeting_id: str
    scheduled_date: Optional[str] = None  # ISO format
    home_team: str
    away_team: str
    venue: Optional[str] = None
    format: str = "6_person"
    wtb_team_id: str
    wtb_club_id: str
    is_played: bool = False  # If true, scrape Spielbericht for full match data
    spielbericht_url: Optional[str] = None  # Full URL to Spielbericht page


class MatchDaySetup(BaseModel):
    format: str = "6_person"
    team_a_players: List[str] = []
    team_b_players: List[str] = []


class MatchResponse(BaseModel):
    id: str
    share_code: str
    match_day_id: Optional[str] = None
    match_number: Optional[int] = None
    match_type: str
    team_a_name: str
    team_b_name: str
    player_a1: Optional[str]
    player_b1: Optional[str]
    player_a2: Optional[str]
    player_b2: Optional[str]
    score_state: dict
    score_cells: Optional[list] = None
    point_display: Optional[dict] = None
    best_of: int
    super_tiebreak_final_set: bool
    created_at: Optional[datetime]
    updated_at: Optional[datetime]
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime]
    duration_seconds: Optional[int] = None
    duration_formatted: Optional[str] = None
    # Public post-match summary (never includes the raw point_log)
    stats: Optional[dict] = None
    # Point-by-point timeline (public, live) — no outcome tags
    point_by_point: Optional[dict] = None

    class Config:
        from_attributes = True
