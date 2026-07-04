#!/usr/bin/env bash
# One-shot local dev prep: align origins, sync secrets, start core services.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PROFILE="${1:-vite}"

case "$PROFILE" in
  vite|compose) ;;
  -h|--help)
    echo "Usage: $(basename "$0") [vite|compose]"
    exit 0
    ;;
  *)
    echo "ERROR: profile must be vite or compose" >&2
    exit 1
    ;;
esac

bash "$ROOT_DIR/scripts/dev/sync-local-env.sh" --profile "$PROFILE"
bash "$ROOT_DIR/scripts/dev/sync-local-secrets.sh" --bootstrap
bash "$ROOT_DIR/scripts/dev/sync-local-secrets.sh" --recreate-api

if ! rg -q '^AJENDA_WORKER_TENANT_MODE=multi' "$ROOT_DIR/deploy/compose/.env.prod" 2>/dev/null; then
  printf '\nAJENDA_WORKER_TENANT_MODE=multi\nAJENDA_WORKER_TENANT_REFRESH_SECONDS=30\n' \
    >>"$ROOT_DIR/deploy/compose/.env.prod"
fi

docker compose -p compose --env-file "$ROOT_DIR/deploy/compose/.env.prod" \
  -f "$ROOT_DIR/deploy/compose/docker-compose.prod.yml" \
  up -d --build api db redis worker

if [[ "$PROFILE" == "vite" ]]; then
  echo "[local-dev-setup] Start frontend: cd frontend && npm run dev"
  echo "[local-dev-setup] UI: http://localhost:5173"
else
  echo "[local-dev-setup] UI: http://localhost:8080"
fi

echo "[local-dev-setup] API: http://localhost:8000"
echo "[local-dev-setup] Credential checklist: bash scripts/dev/credentials-setup-guide.sh --profile $PROFILE"