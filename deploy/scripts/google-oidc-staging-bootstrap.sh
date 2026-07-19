#!/usr/bin/env bash
# Validate Google OIDC staging config and enable customer login in compose env.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${AJENDA_RUNTIME_ENV_FILE:-$ROOT_DIR/deploy/compose/.env.staging}"
SYNC_TARGET="${AJENDA_SYNC_ENV_TARGET:-$ROOT_DIR/deploy/compose/.env.prod}"

log() {
  printf '[google-oidc-staging-bootstrap] %s\n' "$*"
}

fail() {
  printf '[google-oidc-staging-bootstrap] ERROR: %s\n' "$*" >&2
  exit 1
}

[[ -f "$ENV_FILE" ]] || fail "missing env file: $ENV_FILE"

upsert_env() {
  local key="$1"
  local value="$2"
  python3 - "$ENV_FILE" "$key" "$value" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
key = sys.argv[2]
value = sys.argv[3]
lines = path.read_text(encoding="utf-8").splitlines()
out: list[str] = []
replaced = False
prefix = f"{key}="
for line in lines:
    if line.startswith(prefix):
        out.append(f"{key}={value}")
        replaced = True
    else:
        out.append(line)
if not replaced:
    out.append(f"{key}={value}")
path.write_text("\n".join(out) + "\n", encoding="utf-8")
PY
}

env_value() {
  local key="$1"
  python3 - "$ENV_FILE" "$key" <<'PY'
import sys
from pathlib import Path
import re

path = Path(sys.argv[1])
key = sys.argv[2]
text = path.read_text(encoding="utf-8")
match = re.search(rf"^{re.escape(key)}=(.*)$", text, flags=re.MULTILINE)
print(match.group(1).strip() if match else "", end="")
PY
}

CLIENT_ID="${GOOGLE_OAUTH_CLIENT_ID:-$(env_value AJENDA_OIDC_CLIENT_ID)}"
CLIENT_SECRET="${GOOGLE_OAUTH_CLIENT_SECRET:-$(env_value AJENDA_OIDC_CLIENT_SECRET)}"

if [[ -z "$CLIENT_ID" || -z "$CLIENT_SECRET" ]]; then
  cat >&2 <<'EOF'
Missing Google OAuth credentials.

1. Open https://console.cloud.google.com/apis/credentials
2. Create OAuth client ID → Web application
3. Authorized JavaScript origins: http://localhost:8080
4. Authorized redirect URIs:    http://localhost:8080/auth/callback
5. Re-run with:
   GOOGLE_OAUTH_CLIENT_ID=....apps.googleusercontent.com \
   GOOGLE_OAUTH_CLIENT_SECRET=GOCSPX-.... \
   bash deploy/scripts/google-oidc-staging-bootstrap.sh
EOF
  exit 2
fi

log "checking Google OIDC discovery document"
python3 - <<'PY' "$CLIENT_ID"
import json
import sys
import urllib.request

client_id = sys.argv[1]
with urllib.request.urlopen("https://accounts.google.com/.well-known/openid-configuration", timeout=10) as resp:
    doc = json.load(resp)
required = ("authorization_endpoint", "token_endpoint", "jwks_uri", "issuer")
missing = [key for key in required if not doc.get(key)]
if missing:
    raise SystemExit(f"missing discovery fields: {', '.join(missing)}")
print(f"issuer={doc['issuer']}")
print(f"authorization_endpoint={doc['authorization_endpoint']}")
print(f"token_endpoint={doc['token_endpoint']}")
print(f"client_id={client_id[:12]}...")
PY

SESSION_SECRET="$(env_value AJENDA_SESSION_SIGNING_SECRET)"
if [[ -z "$SESSION_SECRET" || ${#SESSION_SECRET} -lt 32 ]]; then
  SESSION_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
  log "generated AJENDA_SESSION_SIGNING_SECRET"
fi

upsert_env AJENDA_OIDC_ISSUER "https://accounts.google.com"
upsert_env AJENDA_OIDC_JWKS_URI "https://www.googleapis.com/oauth2/v3/certs"
upsert_env AJENDA_OIDC_PROVIDER "google"
upsert_env AJENDA_OIDC_CLIENT_ID "$CLIENT_ID"
upsert_env AJENDA_OIDC_CLIENT_SECRET "$CLIENT_SECRET"
upsert_env AJENDA_OIDC_ID_TOKEN_AUDIENCE "$CLIENT_ID"
upsert_env AJENDA_OIDC_LOGIN_ENABLED "true"
upsert_env AJENDA_OIDC_REDIRECT_URI_ALLOWLIST \
  "http://localhost:5173/auth/callback,http://127.0.0.1:5173/auth/callback,http://localhost:8080/auth/callback,http://127.0.0.1:8080/auth/callback"
upsert_env AJENDA_SESSION_SIGNING_SECRET "$SESSION_SECRET"

cp "$ENV_FILE" "$SYNC_TARGET"
log "synced $ENV_FILE -> $SYNC_TARGET"

log "restart api to apply config:"
printf '  docker compose --env-file %s -f %s/deploy/compose/docker-compose.prod.yml up -d api --force-recreate\n' \
  "$SYNC_TARGET" "$ROOT_DIR"

log "then open http://localhost:8080/signin and use Continue with Google"