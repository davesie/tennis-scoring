#!/bin/bash
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== Tennis Scoring Deployment ===${NC}"
echo ""

# Get script directory (works even if called from elsewhere)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ==========================================
# 1. BACKUP DATABASE
# ==========================================
echo -e "${YELLOW}[1/4] Backing up database...${NC}"

BACKUP_DIR="./backups"
TIMESTAMP=$(date +%Y-%m-%d_%H%M%S)
BACKUP_FILE="tennis_backup_${TIMESTAMP}.db"

mkdir -p "$BACKUP_DIR"

# Copy database from Docker volume using a temporary container
if docker volume ls | grep -q "tennis_scoring_tennis_data\|tennis-scoring_tennis_data"; then
    # Try both possible volume naming conventions
    VOLUME_NAME=$(docker volume ls --format '{{.Name}}' | grep -E "tennis.scoring.*tennis_data" | head -1)

    if [ -n "$VOLUME_NAME" ]; then
        docker run --rm \
            -v "${VOLUME_NAME}:/source:ro" \
            -v "$(pwd)/${BACKUP_DIR}:/backup" \
            alpine:latest \
            sh -c "cp /source/tennis.db /backup/${BACKUP_FILE} 2>/dev/null || echo 'No database to backup yet'"

        if [ -f "${BACKUP_DIR}/${BACKUP_FILE}" ]; then
            BACKUP_SIZE=$(du -h "${BACKUP_DIR}/${BACKUP_FILE}" | cut -f1)
            echo -e "  ${GREEN}✓${NC} Backup created: ${BACKUP_DIR}/${BACKUP_FILE} (${BACKUP_SIZE})"
        else
            echo -e "  ${YELLOW}!${NC} No existing database to backup (first deployment?)"
        fi
    else
        echo -e "  ${YELLOW}!${NC} Volume not found (first deployment?)"
    fi
else
    echo -e "  ${YELLOW}!${NC} No tennis data volume found (first deployment?)"
fi

# ==========================================
# 2. PULL LATEST CODE
# ==========================================
echo ""
echo -e "${YELLOW}[2/4] Pulling latest code from GitHub...${NC}"

git pull origin main
echo -e "  ${GREEN}✓${NC} Code updated"

# ==========================================
# 3. REBUILD CONTAINER
# ==========================================
echo ""
echo -e "${YELLOW}[3/4] Rebuilding tennis-scoring container...${NC}"

docker compose build tennis-scoring
echo -e "  ${GREEN}✓${NC} Container rebuilt"

# ==========================================
# 4. RESTART SERVICES
# ==========================================
echo ""
echo -e "${YELLOW}[4/4] Restarting services...${NC}"

docker compose up -d tennis-scoring
echo -e "  ${GREEN}✓${NC} Services restarted"

# ==========================================
# STATUS & LOGS
# ==========================================
echo ""
echo -e "${GREEN}=== Deployment Complete ===${NC}"
echo ""
echo "Container status:"
docker compose ps
echo ""
echo "Recent logs (last 20 lines):"
docker compose logs --tail=20 tennis-scoring
