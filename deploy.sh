#!/usr/bin/env bash
# =============================================================================
# Citadel (OmniPath v2) — Staging Deploy Script
# Usage: ./deploy.sh [--skip-pull] [--service backend]
#
# Always does a clean build to ensure new code is picked up.
# Built with Pride for Obex Blackvault
# =============================================================================
set -euo pipefail

COMPOSE_FILE="docker-compose.staging.yml"
SERVICE="${2:-}"          # Optional: limit to a specific service
SKIP_PULL="${1:-}"        # Pass --skip-pull to skip git pull

# ── 1. Pull latest code ───────────────────────────────────────────────────────
if [[ "$SKIP_PULL" != "--skip-pull" ]]; then
    echo "📥 Pulling latest code from origin/main..."
    git pull origin main
fi

# ── 2. Build ──────────────────────────────────────────────────────────────────
echo "🔨 Building ${SERVICE:-all services} (no-cache)..."
if [[ -n "$SERVICE" ]]; then
    docker compose -f "$COMPOSE_FILE" build --no-cache "$SERVICE"
else
    docker compose -f "$COMPOSE_FILE" build --no-cache
fi

# ── 3. Deploy ─────────────────────────────────────────────────────────────────
echo "🚀 Deploying ${SERVICE:-all services}..."
if [[ -n "$SERVICE" ]]; then
    docker compose -f "$COMPOSE_FILE" up -d --force-recreate "$SERVICE"
else
    docker compose -f "$COMPOSE_FILE" up -d --force-recreate
fi

# ── 4. Health check ───────────────────────────────────────────────────────────
echo "⏳ Waiting 30s for backend to start..."
sleep 30

echo "🔍 Health check..."
HEALTH=$(curl -sf https://nested-ai.net/health 2>/dev/null || echo '{"status":"unreachable"}')
echo "$HEALTH" | python3 -m json.tool 2>/dev/null || echo "$HEALTH"

STATUS=$(echo "$HEALTH" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','unknown'))" 2>/dev/null || echo "unknown")

if [[ "$STATUS" == "ok" ]]; then
    echo "✅ Deploy complete — Citadel is healthy"
else
    echo "❌ Health check failed — check logs:"
    echo "   docker logs citadel-backend 2>&1 | tail -30"
    exit 1
fi
