#!/bin/bash
set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}=== Tennis Scoring Deployment (Native) ===${NC}"
echo ""

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ==========================================
# 1. BACKUP DATABASE
# ==========================================
echo -e "${YELLOW}[1/3] Backing up database...${NC}"

BACKUP_DIR="./backups"
TIMESTAMP=$(date +%Y-%m-%d_%H%M%S)
BACKUP_FILE="tennis_backup_${TIMESTAMP}.db"

mkdir -p "$BACKUP_DIR"

if [ -f "data/tennis.db" ]; then
    cp "data/tennis.db" "${BACKUP_DIR}/${BACKUP_FILE}"
    BACKUP_SIZE=$(du -h "${BACKUP_DIR}/${BACKUP_FILE}" | cut -f1)
    echo -e "  ${GREEN}✓${NC} Backup created: ${BACKUP_DIR}/${BACKUP_FILE} (${BACKUP_SIZE})"
else
    echo -e "  ${YELLOW}!${NC} No database to backup (first deployment?)"
fi

# ==========================================
# 2. PULL LATEST CODE
# ==========================================
echo ""
echo -e "${YELLOW}[2/3] Pulling latest code from GitHub...${NC}"

git pull origin main
echo -e "  ${GREEN}✓${NC} Code updated"

# ==========================================
# 3. UPDATE DEPENDENCIES
# ==========================================
echo ""
echo -e "${YELLOW}[3/3] Updating dependencies...${NC}"

# Check if uv is installed
if ! command -v uv &> /dev/null; then
    echo "  Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    source "$HOME/.local/bin/env" 2>/dev/null || export PATH="$HOME/.local/bin:$PATH"
fi

uv sync
echo -e "  ${GREEN}✓${NC} Dependencies synced"

# ==========================================
# DONE
# ==========================================
echo ""
echo -e "${GREEN}=== Deployment Complete ===${NC}"
echo ""
echo "To start the app:"
echo "  ./start.sh"
echo ""
echo "Or to run in background:"
echo "  nohup ./start.sh > app.log 2>&1 &"
echo ""

# Check if app is already running
PID=$(pgrep -f "uvicorn app.main:app" || true)
if [ -n "$PID" ]; then
    echo -e "${YELLOW}Note: App is currently running (PID: $PID)${NC}"
    echo "To restart, run:"
    echo "  kill $PID && nohup ./start.sh > app.log 2>&1 &"
fi
