# Tennis Scoring

A real-time tennis scoring web application with a TV-style scoreboard display. Perfect for amateur tennis players to track match scores and share live updates with friends.

## Features

- **Real-time scoring** - WebSocket-based live updates for all viewers
- **TV-style scoreboard** - Clean, professional display inspired by broadcast tennis
- **Singles & Doubles** - Support for both match types
- **Full tennis rules** - Points, games, sets, deuce, tiebreaks, and super tiebreaks
- **Shareable links** - Anyone can watch the match in real-time without login
- **Mobile responsive** - Optimized for on-court use with large touch targets
- **Undo functionality** - Correct scoring mistakes easily
- **Self-hostable** - Simple Docker deployment

## Tennis Rules Implemented

- **Points**: 0, 15, 30, 40, game
- **Deuce**: At 40-40, must win by 2 consecutive points (advantage → game)
- **Games**: First to 6 games wins a set (must win by 2)
- **Tiebreak**: At 6-6, play to 7 points (must win by 2)
- **Super Tiebreak**: Optional 3rd set format, play to 10 points (must win by 2)
- **Sets**: Best of 3

## Quick Start

### Using Docker (Recommended)

```bash
# Clone the repository
git clone <repository-url>
cd tennis_scoring

# Start with Docker Compose
docker-compose up -d

# Access the app at http://localhost:8000
```

### Using Podman

```bash
# Build the image
podman build -t tennis-scoring .

# Run the container
podman run -d -p 8000:8000 -v tennis_data:/app/data tennis-scoring
```

### Local Development (with uv)

[uv](https://docs.astral.sh/uv/) is the recommended way to manage this project.

```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install dependencies
uv sync

# Set admin password (required for creating match days)
export ADMIN_PASSWORD=your-secret-password

# Run the application (development with auto-reload)
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Run the application (production)
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Local Development (with pip)

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Set admin password (required for creating match days)
export ADMIN_PASSWORD=your-secret-password

# Run the application
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Usage

1. **Create a Match**: Visit the homepage and set up team names and match type
2. **Score Points**: Use the large buttons to add points for each team
3. **Share**: Copy the shareable link to let others watch in real-time
4. **Undo**: Made a mistake? Use the undo button to correct it

## Tech Stack

- **Backend**: Python 3.11 + FastAPI
- **Real-time**: WebSockets
- **Database**: SQLite (async with aiosqlite)
- **Frontend**: Vanilla HTML/CSS/JavaScript
- **Container**: Docker

## Project Structure

```
tennis_scoring/
├── app/
│   ├── __init__.py
│   ├── main.py          # FastAPI application
│   ├── models.py        # SQLAlchemy models
│   ├── schemas.py       # Pydantic schemas
│   ├── scoring.py       # Tennis scoring logic
│   └── database.py      # Database configuration
├── static/
│   └── css/
│       └── style.css    # Styles including TV scoreboard
├── templates/
│   ├── index.html       # Home/create match page
│   └── match.html       # Scoring and spectator view
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── README.md
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Home page |
| GET | `/match/{id}` | Scorer view |
| GET | `/watch/{code}` | Spectator view |
| POST | `/api/matches` | Create new match |
| GET | `/api/matches/{id}` | Get match data |
| POST | `/api/matches/{id}/score` | Score a point |
| POST | `/api/matches/{id}/undo` | Undo last point |
| POST | `/api/matches/{id}/reset` | Reset match |
| WS | `/ws/{id}` | Real-time updates |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite+aiosqlite:///./tennis.db` | Database connection string |
| `ADMIN_EMAIL` | `admin@localhost` | Superadmin login email (synced on every boot) |
| `ADMIN_PASSWORD` | (required) | Superadmin password (synced on every boot) |
| `DB_BACKUP_KEEP` | `5` | Startup database backups to keep (oldest pruned) |
| `REGISTRATION_MODE` | `open` | `open`, `code` (invite code required) or `closed` |
| `REGISTRATION_CODE` | (empty) | The shared invite code when mode is `code` |

## Accounts & Testing

**Admin (superadmin):** the account is synced from `ADMIN_EMAIL` + `ADMIN_PASSWORD`
on every boot — created if missing, promoted if the email belongs to a normal
user, and the password is reset to the env value. So to set it up (or recover a
forgotten password): set both vars in Coolify → redeploy → log in at
`/admin/login`. The startup log states exactly what happened
("Superadmin created/updated: …").

**Normal user:** open `/register` and create an account with any email (no
verification). With `REGISTRATION_MODE=code`, new users must also enter the
shared `REGISTRATION_CODE` (hand it out privately); `closed` disables
self-registration entirely. Registered users get their own dashboard at `/admin` and own the
match days they create; the superadmin sees everything.

**Testing both roles side by side:** log in as admin in your normal browser
window and as a registered user in a private/incognito window (sessions are
cookie-based). The Flutter app at `/app` logs in via the same accounts
(`POST /api/auth/login`), and scorer/watcher links need no account at all.

## Data Persistence & Updating Production

All data lives in a single SQLite file — in Docker that's `/app/data/tennis.db`
(from the image's default `DATABASE_URL`).

**The one hard requirement:** the deployment must mount a **persistent volume at
`/app/data`**. Without it, every rebuild starts from an empty database. In
Coolify: your app → **Persistent Storage** → a volume with destination
`/app/data`. Verify this on the production app *before* deploying a new
version to it.

**Automatic backups:** on every startup (i.e. every deploy/restart) the app
copies the database to `tennis.backup-<timestamp>.db` next to the live file —
inside the volume — before running schema migrations, and keeps the newest 5
(`DB_BACKUP_KEEP`). The deploy log shows `Database backed up to …`.

**Manual backup / restore** (Coolify → app → Terminal):

```bash
# backup
cp /app/data/tennis.db /app/data/manual-backup.db
# restore (then restart the app)
cp /app/data/tennis.backup-<timestamp>.db /app/data/tennis.db
```

**Schema migrations are additive:** new tables/columns are added in place at
startup (`init_db()` / `ensure_superadmin()`); existing rows are never dropped.
Upgrading a pre-2.x database is supported — existing match days are backfilled
to the superadmin and stay publicly visible.

## Deploying with Coolify

[Coolify](https://coolify.io) is a self-hosted PaaS that can build and run this app directly from GitHub with zero manual Docker commands.

### Steps

1. In Coolify: **New Resource → Application → GitHub repo** — select this repository
2. Set **Build Pack: Dockerfile**
3. Set **Port**: `8000`
4. Under **Environment Variables**, add:
   - `ADMIN_EMAIL` = your admin login email
   - `ADMIN_PASSWORD` = your secure password
   - `DATABASE_URL` = `sqlite+aiosqlite:///./data/tennis.db` (optional — this is the Dockerfile default)
5. Under **Persistent Storage**, add a volume mounted at `/app/data` — this preserves your SQLite database across deploys
6. Click **Deploy**

### Secrets strategy

Coolify injects environment variables at container runtime — they are **never stored in your image or your git repo**. You do not need a private repository to keep `ADMIN_PASSWORD` secret. Set it in the Coolify dashboard and it stays there.

| Option | Verdict |
|--------|---------|
| Coolify env vars (recommended) | ✅ Simple, secure — secrets never touch the repo |
| Private GitHub repo | Adds code privacy, does not replace env vars |
| `.env` committed to repo | ⚠️ Not recommended — secrets end up in git history |

### Updating

Push to your configured branch → Coolify automatically rebuilds and redeploys.

---

## VPS Deployment with Docker + Traefik

Minimum requirements: 1 vCore, 512MB RAM (2 vCores + 2GB RAM is plenty)

### 1. Server Setup (Ubuntu/Debian)

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
newgrp docker

# Install Git
sudo apt install -y git

# Setup firewall
sudo ufw allow 22
sudo ufw allow 80
sudo ufw allow 443
sudo ufw enable
```

### 2. Deploy (one command!)

```bash
# Clone the repository
git clone https://github.com/YOUR_USERNAME/tennis-scoring.git
cd tennis-scoring

# Create .env file (edit with your values)
cp .env.example .env
nano .env  # or: vim .env

# Start everything (Traefik + App)
docker compose up -d --build
```

That's it! The app will be available at `https://your-domain.com` with automatic SSL.

### Updating the App

```bash
cd ~/tennis-scoring
git pull
docker compose up -d --build tennis-scoring
```

Note: Use `--build tennis-scoring` to only rebuild the app, not Traefik.

### Useful Commands

```bash
# View logs
docker compose logs -f tennis-scoring

# View Traefik logs (for SSL issues)
docker compose logs -f traefik

# Restart everything
docker compose restart

# Stop everything
docker compose down

# Full rebuild (if you changed Dockerfile)
docker compose up -d --build --force-recreate tennis-scoring
```

### Architecture

```
Internet → Traefik (ports 80/443, auto-SSL) → Tennis Scoring App (port 8000)
```

Traefik automatically:
- Obtains and renews Let's Encrypt SSL certificates
- Routes traffic based on domain name
- Handles HTTP → HTTPS redirect
- Supports WebSocket connections for real-time updates

## License

MIT
