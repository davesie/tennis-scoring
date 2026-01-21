from pydantic import BaseModel
from typing import Optional, List
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


class MatchDayCreate(BaseModel):
    name: str = "Match Day"
    format: str = "6_person"  # "6_person" or "4_person"
    players: List[str] = []
    team_a_name: str = "Team A"
    team_b_name: str = "Team B"
    team_a_players: List[str] = []
    team_b_players: List[str] = []


class MatchPlayersUpdate(BaseModel):
    player_a1: Optional[str] = None
    player_a2: Optional[str] = None
    player_b1: Optional[str] = None
    player_b2: Optional[str] = None


class MatchScoreSet(BaseModel):
    """Set final score directly for matches not watched live."""
    sets: List[List[int]]  # e.g., [[6, 4], [3, 6], [6, 2]] for a 2-1 win
    winner: int  # 0 or 1


class MatchResponse(BaseModel):
    id: str
    share_code: str
    match_type: str
    team_a_name: str
    team_b_name: str
    player_a1: Optional[str]
    player_b1: Optional[str]
    player_a2: Optional[str]
    player_b2: Optional[str]
    score_state: dict
    best_of: int
    super_tiebreak_final_set: bool
    created_at: Optional[datetime]
    updated_at: Optional[datetime]
    finished_at: Optional[datetime]

    class Config:
        from_attributes = True
