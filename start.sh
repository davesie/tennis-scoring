#!/bin/bash
set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Create data directory if it doesn't exist
mkdir -p data

# Check if uv is installed
if ! command -v uv &> /dev/null; then
    echo -e "${YELLOW}Installing uv...${NC}"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    source "$HOME/.local/bin/env" 2>/dev/null || export PATH="$HOME/.local/bin:$PATH"
fi

# Sync dependencies (creates venv if needed)
echo -e "${YELLOW}Syncing dependencies...${NC}"
uv sync
echo -e "${GREEN}✓${NC} Dependencies synced"

# Load .env if exists
if [ -f ".env" ]; then
    export $(grep -v '^#' .env | xargs)
fi

# Set defaults
export DATABASE_URL="${DATABASE_URL:-sqlite+aiosqlite:///./data/tennis.db}"
export ADMIN_PASSWORD="${ADMIN_PASSWORD:-changeme}"

echo ""
echo -e "${GREEN}Starting Tennis Scoring App...${NC}"
echo "Database: $DATABASE_URL"
echo "Press Ctrl+C to stop"
echo ""

# Run uvicorn via uv
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
