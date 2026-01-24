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

# Check if venv exists, create if not
if [ ! -d "venv" ]; then
    echo -e "${YELLOW}Creating virtual environment...${NC}"
    python3 -m venv venv
    echo -e "${GREEN}✓${NC} Virtual environment created"
fi

# Activate venv
source venv/bin/activate

# Install/update dependencies
echo -e "${YELLOW}Installing dependencies...${NC}"
pip install -q -r requirements.txt
echo -e "${GREEN}✓${NC} Dependencies installed"

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

# Run uvicorn
uvicorn app.main:app --host 0.0.0.0 --port 8000
