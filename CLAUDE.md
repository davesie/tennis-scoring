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
    "tiebreak_first_server": None,       # Who served first in current/last tiebreak
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

---

## User Roles & Access

Three roles exist, all fully implemented:

| Role | How | URL |
|------|-----|-----|
| **Admin** | Password login → session cookie | `/admin/login` → `/admin` |
| **Scorer** | 12-char token, no login needed | `/scoreday/{scorer_token}` |
| **Watcher** | 8-char share code, no login | `/watchday/{share_code}` |

- Token auth: `app/auth.py` — `verify_scorer_for_match()` checks `X-Scorer-Token` header
- Share links are shown on the match day page (`/matchday/{id}`) under "Share Match Day"

## Navigation Flow

- `GET /` → redirects to `/archive` (public landing page, no login required)
- `GET /archive` → public archive of all match days; shows "Admin Login" or "Admin Dashboard" link
- `GET /admin/login` → login form
- `GET /admin` → admin dashboard (requires auth)
- Post-logout → redirects to `/` (archive)

## Git / Branch State

- **`main`** — production-ready branch, tracks `origin/main`
- **`dev`** — active development branch; contains work from this session
- **`feature/initial-server-selection`** — previous feature branch (merged to main)

Current `dev` branch contains:
- Archive as default landing page (`GET /` → `/archive`)
- Admin login/dashboard link added to archive header
- `is_admin` context variable passed to `archive.html` template
- Theme system: light default + dark mode toggle (persists to localStorage)
- Tiebreak serving logic fix (`tiebreak_first_server` field)
- "Broadcast Court" visual redesign (archive, matchday, match pages)

## Pending / Planned Work

### Share Link Discoverability
Share links exist but could be more visible. Currently:
- Admin dashboard (`/admin`) has "Copy Scorer Link" / "Copy Spectator Link" buttons per card
- Match day page has a collapsed "Share Match Day" section at the bottom
- Archive page has no share links

## Theme System

All pages use CSS custom properties with `[data-theme]` on `<html>`:
- **Light (default):** warm off-white (`#F7F5EE`) background, dark text, Broadcast Court palette
- **Dark (toggle):** deep neutral (`#131210`) background, reuses existing dark scoreboard vars
- Toggle button (sun/moon icon) in top-right corner of every page, persists to `localStorage`
- Variables defined in `:root` (light) and `[data-theme="dark"]` (dark) in `style.css`

## Design System — "Broadcast Court"

Applied to all three public pages (`archive.html`, `matchday.html`, `match.html`). No admin page changes.

### Fonts (Google Fonts, imported in `style.css` line 1)
| Variable | Font | Use |
|---|---|---|
| `--font-display` | Barlow Condensed 400/600/700/800 | Headings, player names, team names, buttons |
| `--font-score` | Chakra Petch 400/600/700 | Score numbers, dates, timers, badges |
| `--font-body` | DM Sans 400–700 | All other text, labels |

### Key Design Tokens (`--bc-*`)
- `--bc-bg` / `--bc-text` — page background (light: `#F7F5EE`, dark: `#131210`)
- `--bc-team-a` / `--bc-team-b` — team colors (light: `#1B4FA8` / `#D44030`; dark: `#3D72D9` / `#E05545`)
- `--bc-accent` — tennis ball lime `#C6EF3E` (used for CTAs, hover, accents)
- `--bc-muted` / `--bc-border` — secondary text and dividers

### Match Scoreboard (`--match-scoreboard-*`)
The match scoreboard (`.scoreboard` on `match.html`) is **always dark** regardless of theme:
- Light mode: uses hardcoded dark values (`#16161A` bg, `#F0EDE8` text, `#C6EF3E` accent)
- Dark mode: maps to existing `--scoreboard-bg`, `--score-text` etc. dark vars
- This is achieved via `--match-scoreboard-*` variable layer in both `:root` and `[data-theme="dark"]`

### Archive Page Layout
- Fixture list (not cards) — CSS grid: `100px 1fr auto auto` columns
- Classes: `.archive-list` > `.archive-card` > `.fixture-meta`, `.fixture-name`, `.fixture-matchup`, `.fixture-status`
- `.fixture-team-a` blue, `.fixture-team-b` red, `.fixture-score-a/b` in Chakra Petch
- Status shows `FT` badge when all matches completed

### Match Day Header
- `.matchday-hero-top` wraps `<h1>` and `.live-indicator`
- `.team-scores` is a dark pill (`--bc-scoreboard-dark`) with `.team-score-a` / `.team-score-b` classes
- Team name color comes from `.team-score-a .team-name` / `.team-score-b .team-name` rules
- JS hooks `id="team-a-wins"` / `id="team-b-wins"` are unchanged — all existing JS works

## Templates Overview

| Template | Purpose |
|----------|---------|
| `templates/archive.html` | Public landing page — list of all match days |
| `templates/admin_login.html` | Admin password login |
| `templates/admin.html` | Admin dashboard — create/manage match days |
| `templates/index.html` | Create match day / single match forms (reached via `/admin`) |
| `templates/matchday.html` | Live match day view (scorer + spectator) |
| `templates/match.html` | Individual match scoring / spectator view |
