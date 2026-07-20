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
- `app/models.py` - SQLAlchemy models: `Match`, `MatchDay`, `Club`, `Player`
- `app/schemas.py` - Pydantic request/response schemas
- `app/database.py` - Async database configuration + migrations
- `app/wtb_scraper.py` - WTB website scraper for clubs and players
- `app/auth.py` - Token auth for scorer access (`verify_scorer_for_match()`)
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

### Per-Point Statistics

Per-point stats are tracked separately from the score state machine:

- **`Match.point_log`** (JSON column) — append-only list; one entry per point scored via the **Point** button (Game-button points are not logged). Each entry:
  ```python
  {"winner": 0|1, "server": 0|1, "set": int,
   "outcome": None|"ace"|"winner"|"unforced_error"|"forced_error"|"double_fault",
   "ts": "<iso>"}
  ```
- **Tagging** — `POST /api/matches/{id}/point-outcome` `{"outcome": ...}` sets the outcome on the **last** log entry (optional; the scorer can skip). `ace` is only valid when the server won the point; `double_fault` only when the receiver won.
- **Stats** — `scoring.compute_match_stats(point_log)` aggregates per-team `points_won`, `aces`, `double_faults`, `winners`, `unforced_errors`, `forced_errors`, plus `tagged`/`total` coverage.
- **Visibility** — `Match.to_dict(include_stats=False)`: the raw `point_log` + live `stats` go only to scorer-facing responses (`include_stats=True`); the public/WS payload includes a `stats` summary **only once the match is finished** (post-match summary for all). Live stats are never broadcast to spectators.
- **Undo** — `push_history()` snapshots both `score_state` and `point_log`, so undo rolls back stats too. Legacy (pre-2.1) history entries are bare score-state dicts and are handled defensively.
- **Point-by-point (v2.6)** — `scoring.build_point_by_point(point_log)` replays the log into a broadcast-style timeline (per set → per game → score chips with BP/SP/MP badges). It is **public and live** (`to_dict()` always includes `point_by_point`) but carries no outcome tags. Game-button scoring appends a `{"kind": "game", "team": …}` marker to `point_log` (no `winner` key → ignored by stats) so the timeline stays faithful with mixed scoring. Rendered on `match.html` as a "Point by Point" section with set tabs.
- **UI** — `templates/match.html`: a skippable tag sheet appears after each point (scorer only), a live stats panel (scorer), and a post-match summary table (everyone). One-tap scoring is unchanged.

### Match Day Formats

- **6-person:** 6 singles + 3 doubles (players 1-6 paired as 1v1, 2v2...6v6 for singles; (1,2)v(1,2), (3,4)v(3,4), (5,6)v(5,6) for doubles)
- **4-person:** 4 singles + 2 doubles

### WebSocket Pattern

`ConnectionManager` class in `main.py` tracks active connections per match ID and broadcasts score updates to all viewers. Message format:
```json
{"type": "score_update", "match": {...}, "summary": {...}}
```

## Versioning

**Always maintain version numbers when making changes.** The app uses semantic versioning displayed on every page.

- **Source of truth:** `version` field in `pyproject.toml`
- **Format:** `major.minor.patch+gitsha` (e.g., `1.1.0+5550783`)
  - **major** — breaking changes (data model, API incompatibility)
  - **minor** — new features
  - **patch** — bug fixes, styling tweaks
- **Display:** Fixed label in bottom-right corner of every page (`.version-label`), injected via `templates.env.globals["app_version"]`
- **Git hash** appended automatically at startup for exact build traceability
- **When to bump:** Bump the version in `pyproject.toml` with each commit — patch for fixes, minor for features, major for breaking changes

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite+aiosqlite:///./tennis.db` | Database connection string (Docker image sets `./data/tennis.db`) |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | — | Superadmin account, synced from env on every boot |
| `REGISTRATION_MODE` | `open` | `open` \| `code` (requires `REGISTRATION_CODE`) \| `closed` |
| `REGISTRATION_CODE` | — | Invite code when `REGISTRATION_MODE=code` |
| `DB_BACKUP_KEEP` | `5` | Startup SQLite backups kept next to the DB file |
| `SEED_DEMO_DATA` | off | `1`/`true` seeds demo users + match days on boot (dev only!) |

## Demo Data (dev environment)

`app/seed.py` seeds test data at startup when `SEED_DEMO_DATA=1` — set that env var
on the **dev** Coolify app only, never on main. Idempotent (skips if `anna@demo.de`
exists); dev has no persistent volume, so every redeploy reseeds fresh data.
Seeded: users `anna@demo.de` / `ben@demo.de` / `clara@demo.de` (password `demo123`,
clara has no data — safe to delete when testing user management), a finished
4-person match day (full point-by-point + stats, `/watchday/demoday1`) and a live
6-person match day with finished/live/upcoming matches (`/watchday/demoday2`,
scorer link `/scoreday/demoscorer02`). Matches are simulated point-by-point through
the real scoring engine with a fixed RNG seed, so every deploy yields identical data.

---

## Security

Hardening lives in `app/main.py` (middleware + auth routes), `app/auth.py`,
`app/wtb_scraper.py`, and `static/js/common.js`. Keep these invariants when
editing:

- **SQL injection:** all DB access goes through SQLAlchemy (parameterized).
  The only raw `text()` SQL (`app/database.py`) uses `:bound` params — never
  string-interpolate user input into `text()`.
- **XSS:** Jinja auto-escapes templates. Any value written to `innerHTML` from
  JS (player/team/club names — attacker-controllable) MUST pass through
  `escapeHtml()` (common.js) or `escHtml()` (admin.html). Prefer `.textContent`
  where possible.
- **Security headers:** a middleware sets CSP, `X-Content-Type-Options`,
  `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`, and HSTS (on
  HTTPS). `/app` (Flutter) is CSP-exempt.
- **CSP script policy (strict — no `'unsafe-inline'`):** `script-src` is
  `'self' 'nonce-<per-request>'`. The nonce is generated per request in the
  security middleware (`request.state.csp_nonce`), exposed to templates via the
  i18n context processor, and stamped on every inline `<script nonce="{{ csp_nonce }}">`.
  Because of this, **no inline event handlers** (`onclick=`, `onchange=`, …) are
  allowed anywhere — they're replaced by `data-action="fnName"` (+ `data-*`
  params) and a single delegated dispatcher in `common.js` (`registerActions({...})`,
  see `_delegate`). When adding interactive markup: never write `on*=` attributes
  (static or in JS template strings); use `data-action` and register a handler.
  JS property assignment (`el.onclick = fn`) and `addEventListener` are fine —
  CSP only blocks inline HTML handlers. `style-src` keeps `'unsafe-inline'`
  (inline styles can't execute JS).
- **Auth brute force:** `enforce_rate_limit()` caps login/register at 10/min
  per IP (in-memory). Login compares against a dummy bcrypt hash for unknown
  emails so timing can't enumerate accounts.
- **SSRF:** `scrape_spielbericht()` only fetches `https://(www.)wtb-tennis.de`
  — the URL comes from client fixture-import input. Keep the host allowlist.
- **Tokens:** scorer tokens / share codes use `secrets.token_hex` (48/32 bits).
- **Behind the proxy:** the Docker `CMD` runs uvicorn with `--proxy-headers`
  and `FORWARDED_ALLOW_IPS=*` so the app sees the real client IP (rate limit)
  and the `https` scheme (Secure cookies, HSTS). Only valid because the
  container is reachable solely through Traefik/Coolify on the Docker network.

## User Roles & Access

Three roles exist, all fully implemented:

| Role | How | URL |
|------|-----|-----|
| **Admin** | Password login → session cookie | `/admin/login` → `/admin` |
| **Scorer** | 12-char token, no login needed | `/scoreday/{scorer_token}` |
| **Watcher** | 8-char share code, no login | `/watchday/{share_code}` |

- Token auth: `app/auth.py` — `verify_scorer_for_match()` checks `X-Scorer-Token` header
- Share links: match day page has an expanded "Share Match Day" section; archive page has per-row "Share" buttons that copy spectator URLs to clipboard

## Navigation Flow

- `GET /` → public home page (`home.html`): live, today's and upcoming match
  days in three groups (`_visible_matchdays_with_stats()` classifies via
  `is_live` / `ref_date`); links to the archive
- `GET /archive` → past match days only (finished, or date before today and not
  live; stale unfinished ones show their partial n/m state)
- A match day finished *today* stays on `/` under "Today" (FT badge) and moves
  to the archive the next day
- `GET /admin/login` → login form; `GET /admin` → dashboard (requires auth);
  `GET /admin/new` → dedicated create-match-day page
- Post-logout → redirects to `/` (home)

## Git / Branch State

- **`main`** — production-ready branch, tracks `origin/main`
- **`dev`** — active development branch
- **`feature/initial-server-selection`** — previous feature branch (merged to main)

## WTB Integration

### Club & Player Sync
- **Startup sync:** `_startup_sync_clubs()` runs on app boot, scrapes all club listing pages from WTB (~13 pages, 100 clubs each)
- **Manual sync:** Admin can trigger via "Sync All Clubs from WTB" button → `POST /api/admin/sync-clubs-stream` (SSE endpoint with real-time progress)
- **Player sync:** Auto-triggered on first request to `/api/clubs/{club_id}/players` — scrapes the club's player page from WTB. Manual per-club sync also available via `POST /api/admin/sync-club-players/{club_id}`
- **Concurrent sync prevention:** Module-level `_sync_in_progress` flag prevents parallel syncs (returns 409)

### Scraper Details (`app/wtb_scraper.py`)
- Club listing: paginates `wtb-tennis.de/spielbetrieb/vereine.html` using TYPO3 form POST with offset. Bounded by `_get_total_pages()` + deduplication by `wtb_id`
- Player scraping: finds the target category (e.g. "Herren") by scanning `<a href="#collapseN">` link text — collapse IDs vary per club. Uses the **last** match to prefer the main season over sub-events like "VR-Talentiade"
- Ranking parsing: extracts leading number from cells like "2 MF". Detects "MF" flag (Mannschaftsführer / team captain) → stored as `is_captain`
- 1-second polite delay between page requests

### Models
- `Club` — `wtb_id`, `name`, `location`, `district`, `url`, `last_synced`
- `Player` — `name`, `birth_year`, `category`, `wtb_id_nummer`, `ranking`, `is_captain`, `club_id` (FK)

### Admin UI for Sync
- "Sync All Clubs from WTB" button with SSE-streamed progress ("Fetching page 3/13... 300 clubs")
- Last sync timestamp displayed below the button
- Per-club player sync via autocomplete search
- Player picker: two-panel UI (Available / Selected), sorted by WTB ranking, MF badge shown

## Internationalization (v2.7)

Two languages (en/de) via one shared catalog `static/i18n.json` ({key: {en, de}}):
- **Server:** `app/i18n.py` — `lang` cookie > Accept-Language (de* → de) > en. A Jinja `context_processor` gives every template `lang` and `t('key', **kwargs)`.
- **Browser:** `/i18n.js` (loaded before common.js) sets `window.LANG` + `window.T` (current language only); `t(key, vars)` in common.js serves all dynamic JS strings.
- **Switcher:** `.lang-toggle` button (top-right, next to theme toggle) sets the cookie and reloads.
- Long-form FAQ content uses `{% if lang == 'de' %}` blocks instead of catalog keys.
- API error `detail` strings remain English (surfaced rarely; not translated yet).

## Theme System

All pages use CSS custom properties with `[data-theme]` on `<html>`:
- **Light (default):** warm off-white (`#F7F5EE`) background, dark text, Broadcast Court palette
- **Dark (toggle):** deep neutral (`#131210`) background, reuses existing dark scoreboard vars
- Toggle button (sun/moon icon) in top-right corner of every page, persists to `localStorage`
- Variables defined in `:root` (light) and `[data-theme="dark"]` (dark) in `style.css`

## Design System — "Broadcast Court"

Applied to all pages including admin (`admin.html`, `admin_login.html` use `class="matchday-page"` on body).

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
The match scoreboard (`.scoreboard` on `match.html`) is **theme-aware** — light in light mode, dark in dark mode, always elevated:
- Light mode: white bg (`#FFFFFF`), dark text (`#1A1A1A`), gold accent (`#d4a017`), subtle shadow
- Dark mode: deep dark bg (`#16161A`), light text (`#F0EDE8`), lime accent (`#C6EF3E`), stronger shadow
- This is achieved via `--match-scoreboard-*` variable layer in both `:root` and `[data-theme="dark"]`
- The `.team-scores` pill on matchday page also uses `--match-scoreboard-*` vars for consistency

### Archive Page Layout
- Fixture list (not cards) — each row is `.archive-row` (flex) wrapping `.archive-card` (grid: `100px 1fr auto auto`) + `.fixture-share-btn`
- Classes: `.archive-list` > `.archive-row` > `.archive-card` > `.fixture-meta`, `.fixture-name`, `.fixture-matchup`, `.fixture-status`
- `.fixture-team-a` blue, `.fixture-team-b` red, `.fixture-score-a/b` in Chakra Petch
- Status shows `FT` badge when all matches completed
- `.fixture-share-btn` copies spectator URL to clipboard (hidden on mobile)

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
| `templates/matchday.html` | Live match day view (scorer + spectator) |
| `templates/match.html` | Individual match scoring / spectator view |
