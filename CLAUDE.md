# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Real-time tennis scoring web application with TV-style scoreboard display. Uses WebSockets for live updates, allowing spectators to watch matches in real-time via shareable links.

## Development Commands

```bash
# Local development with auto-reload
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Production
uvicorn app.main:app --host 0.0.0.0 --port 8000

# Docker
docker-compose up -d

# Podman alternative
podman build -t tennis-scoring .
podman run -d -p 8000:8000 -v tennis_data:/app/data tennis-scoring
```

**Note:** No test suite exists yet. No linter or formatter is configured.

## Architecture

**Stack:** Python 3.11 + FastAPI + SQLAlchemy (async) + SQLite + Jinja2 templates + vanilla JS + WebSockets

### Key Files

- `app/main.py` - FastAPI routes, WebSocket connection manager, all API endpoints
- `app/scoring.py` - Tennis scoring state machine (points, games, sets, tiebreaks, deuce logic)
- `app/models.py` - SQLAlchemy models: `Match` and `MatchDay`
- `app/schemas.py` - Pydantic request/response schemas
- `app/database.py` - Async database configuration
- `templates/match.html` - Scoring page with WebSocket client for real-time updates
- `templates/matchday.html` - Dashboard showing all matches in a match day

### Data Flow

1. User creates match via form → POST `/api/matches` → Match record in SQLite
2. Scorer clicks point button → POST `/api/matches/{id}/score` → `scoring.py` processes state transition → WebSocket broadcasts to all connected viewers
3. State history (max 50 entries) enables undo functionality

### Score State Structure

```python
{
    "points": [0, 0],                    # Current game points
    "games": [[0, 0], [0, 0], [0, 0]],  # Games per set
    "sets": [0, 0],                      # Sets won
    "current_set": 0,                    # 0-indexed
    "serving": 0,                        # 0=Team A, 1=Team B
    "is_tiebreak": False,
    "tiebreak_points": [0, 0],
    "winner": None,                      # None, 0, or 1
    "deuce_advantage": None              # None, 0, or 1
}
```

### Match Day Formats

- **6-person:** 6 singles + 3 doubles (players 1-6 paired as 1v1, 2v2...6v6 for singles; (1,2)v(1,2), (3,4)v(3,4), (5,6)v(5,6) for doubles)
- **4-person:** 4 singles + 2 doubles

### WebSocket Pattern

`ConnectionManager` class in `main.py` tracks active connections per match ID and broadcasts score updates to all viewers. Message format:
```json
{"type": "score_update", "match": {...}, "summary": {...}}
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite+aiosqlite:///./data/tennis.db` | Database connection string |
