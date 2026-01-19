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

### Local Development

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

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

## License

MIT
