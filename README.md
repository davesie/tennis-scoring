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
| `ADMIN_PASSWORD` | (required) | Password for admin access to create match days |

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
