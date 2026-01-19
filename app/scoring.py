"""
Tennis Scoring Logic

Rules:
- Points: 0, 15, 30, 40, game
- Deuce: At 40-40, must win by 2 consecutive points
- Games: First to 6 games wins a set (must win by 2)
- Tiebreak: At 6-6, play to 7 points (must win by 2)
- Super Tiebreak: 3rd set, play to 10 points (must win by 2)
- Sets: Best of 3
"""

import copy
from typing import Dict, Any, Optional

POINT_NAMES = ["0", "15", "30", "40"]


def create_initial_state() -> Dict[str, Any]:
    """Create a fresh score state."""
    return {
        "points": [0, 0],
        "games": [[0, 0], [0, 0], [0, 0]],
        "sets": [0, 0],
        "current_set": 0,
        "serving": 0,
        "is_tiebreak": False,
        "is_super_tiebreak": False,
        "tiebreak_points": [0, 0],
        "winner": None,
        "deuce_advantage": None
    }


def get_point_display(state: Dict[str, Any]) -> tuple[str, str]:
    """Get display strings for current points."""
    if state["is_tiebreak"] or state["is_super_tiebreak"]:
        return str(state["tiebreak_points"][0]), str(state["tiebreak_points"][1])

    p1, p2 = state["points"]

    # Deuce situations
    if p1 >= 3 and p2 >= 3:
        if state["deuce_advantage"] == 0:
            return "AD", "-"
        elif state["deuce_advantage"] == 1:
            return "-", "AD"
        else:
            return "40", "40"

    return POINT_NAMES[min(p1, 3)], POINT_NAMES[min(p2, 3)]


def score_point(state: Dict[str, Any], team: int, super_tiebreak_final: bool = True) -> Dict[str, Any]:
    """
    Score a point for the given team (0 or 1).
    Returns the new state.
    """
    if state["winner"] is not None:
        return state

    new_state = copy.deepcopy(state)

    if new_state["is_super_tiebreak"]:
        _score_super_tiebreak_point(new_state, team)
    elif new_state["is_tiebreak"]:
        _score_tiebreak_point(new_state, team, super_tiebreak_final)
    else:
        _score_regular_point(new_state, team, super_tiebreak_final)

    return new_state


def _score_regular_point(state: Dict[str, Any], team: int, super_tiebreak_final: bool):
    """Handle scoring in a regular game."""
    other = 1 - team
    p_team = state["points"][team]
    p_other = state["points"][other]

    # Handle deuce situations
    if p_team >= 3 and p_other >= 3:
        if state["deuce_advantage"] == team:
            # Team with advantage wins game
            _win_game(state, team, super_tiebreak_final)
        elif state["deuce_advantage"] == other:
            # Back to deuce
            state["deuce_advantage"] = None
        else:
            # Gain advantage
            state["deuce_advantage"] = team
    elif p_team >= 3:
        # Win the game
        _win_game(state, team, super_tiebreak_final)
    else:
        # Regular point increment
        state["points"][team] += 1


def _win_game(state: Dict[str, Any], team: int, super_tiebreak_final: bool):
    """Handle winning a game."""
    current_set = state["current_set"]
    state["games"][current_set][team] += 1
    state["points"] = [0, 0]
    state["deuce_advantage"] = None

    games_team = state["games"][current_set][team]
    games_other = state["games"][current_set][1 - team]

    # Check for tiebreak at 6-6
    if games_team == 6 and games_other == 6:
        state["is_tiebreak"] = True
        state["tiebreak_points"] = [0, 0]
    # Check for set win (6 games with 2+ lead, or 7-6 after tiebreak)
    elif games_team >= 6 and games_team - games_other >= 2:
        _win_set(state, team, super_tiebreak_final)
    else:
        # Switch server
        state["serving"] = 1 - state["serving"]


def _score_tiebreak_point(state: Dict[str, Any], team: int, super_tiebreak_final: bool):
    """Handle scoring in a tiebreak."""
    state["tiebreak_points"][team] += 1
    total_points = sum(state["tiebreak_points"])

    # Switch server every 2 points (after first point)
    if total_points == 1 or (total_points > 1 and (total_points - 1) % 2 == 0):
        state["serving"] = 1 - state["serving"]

    # Check for tiebreak win (7+ points, win by 2)
    if state["tiebreak_points"][team] >= 7:
        if state["tiebreak_points"][team] - state["tiebreak_points"][1 - team] >= 2:
            # Win the tiebreak game
            current_set = state["current_set"]
            state["games"][current_set][team] += 1
            state["is_tiebreak"] = False
            state["tiebreak_points"] = [0, 0]
            _win_set(state, team, super_tiebreak_final)


def _score_super_tiebreak_point(state: Dict[str, Any], team: int):
    """Handle scoring in a super tiebreak (10 points, win by 2)."""
    state["tiebreak_points"][team] += 1
    total_points = sum(state["tiebreak_points"])

    # Switch server every 2 points (after first point)
    if total_points == 1 or (total_points > 1 and (total_points - 1) % 2 == 0):
        state["serving"] = 1 - state["serving"]

    # Check for super tiebreak win (10+ points, win by 2)
    if state["tiebreak_points"][team] >= 10:
        if state["tiebreak_points"][team] - state["tiebreak_points"][1 - team] >= 2:
            # Win the match
            state["sets"][team] += 1
            state["is_super_tiebreak"] = False
            state["winner"] = team


def _win_set(state: Dict[str, Any], team: int, super_tiebreak_final: bool):
    """Handle winning a set."""
    state["sets"][team] += 1
    state["points"] = [0, 0]

    # Check for match win
    sets_to_win = 2  # Best of 3
    if state["sets"][team] >= sets_to_win:
        state["winner"] = team
        return

    # Move to next set
    state["current_set"] += 1

    # Check if this is the final set and super tiebreak is enabled
    if state["current_set"] == 2 and super_tiebreak_final:
        # Third set is a super tiebreak
        state["is_super_tiebreak"] = True
        state["tiebreak_points"] = [0, 0]
    else:
        # Switch server for new set
        state["serving"] = 1 - state["serving"]


def score_game(state: Dict[str, Any], team: int, super_tiebreak_final: bool = True) -> Dict[str, Any]:
    """
    Score a whole game for the given team (0 or 1).
    This skips point-by-point scoring and awards the game directly.
    Cannot be used during tiebreaks - use score_point instead.
    Returns the new state.
    """
    if state["winner"] is not None:
        return state

    # During tiebreaks, you can't award a whole game
    if state["is_tiebreak"] or state["is_super_tiebreak"]:
        return state

    new_state = copy.deepcopy(state)

    # Reset points and award the game
    new_state["points"] = [0, 0]
    new_state["deuce_advantage"] = None
    _win_game(new_state, team, super_tiebreak_final)

    return new_state


def get_score_summary(state: Dict[str, Any]) -> Dict[str, Any]:
    """Get a formatted summary of the current score."""
    point_a, point_b = get_point_display(state)

    return {
        "sets": state["sets"],
        "games": state["games"],
        "points": {"a": point_a, "b": point_b},
        "serving": state["serving"],
        "is_tiebreak": state["is_tiebreak"],
        "is_super_tiebreak": state["is_super_tiebreak"],
        "current_set": state["current_set"],
        "winner": state["winner"],
    }
