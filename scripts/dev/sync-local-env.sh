#!/usr/bin/env bash
# Align deploy/compose/.env.prod origin-dependent vars with a local dev profile.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MATRIX_FILE="${AJENDA_LOCAL_DEV_MATRIX:-$ROOT_DIR/deploy/compose/local-dev.matrix.yaml}"
ENV_FILE="${AJENDA_RUNTIME_ENV_FILE:-$ROOT_DIR/deploy/compose/.env.prod}"
PROFILE=""

log() {
  printf '[sync-local-env] %s\n' "$*"
}

fail() {
  printf '[sync-local-env] ERROR: %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<USAGE
Usage: $(basename "$0") --profile vite|compose

Reads deploy/compose/local-dev.matrix.yaml and upserts origin-aligned values into
deploy/compose/.env.prod (CORS, signup verify URL, OIDC allowlist, provider OAuth redirects).

Environment:
  AJENDA_LOCAL_DEV_MATRIX   Matrix YAML path (default: deploy/compose/local-dev.matrix.yaml)
  AJENDA_RUNTIME_ENV_FILE  Target env file (default: deploy/compose/.env.prod)

After syncing, prints external OAuth callback URLs to register in Google Cloud and Salesforce.
For console links and env-var checklist (no secrets printed):
  bash scripts/dev/credentials-setup-guide.sh --profile vite
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile)
      PROFILE="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "unknown argument: $1 (see --help)"
      ;;
  esac
done

[[ -n "$PROFILE" ]] || fail "--profile is required (vite or compose)"
[[ "$PROFILE" == "vite" || "$PROFILE" == "compose" ]] || fail "--profile must be vite or compose"
[[ -f "$MATRIX_FILE" ]] || fail "missing matrix file: $MATRIX_FILE"

if [[ ! -f "$ENV_FILE" ]]; then
  log "creating $ENV_FILE from deploy/compose/.env.staging.example"
  cp "$ROOT_DIR/deploy/compose/.env.staging.example" "$ENV_FILE"
fi

SYNC_RESULT="$(python3 - "$MATRIX_FILE" "$ENV_FILE" "$PROFILE" <<'PY'
import sys
from pathlib import Path

try:
    import yaml
except ImportError as exc:
    raise SystemExit(
        "PyYAML is required. Install with: pip install pyyaml (or python3 -m pip install pyyaml)"
    ) from exc

matrix_path = Path(sys.argv[1])
env_path = Path(sys.argv[2])
profile_name = sys.argv[3]

matrix = yaml.safe_load(matrix_path.read_text(encoding="utf-8"))
profiles = matrix.get("profiles") or {}
profile = profiles.get(profile_name)
if not profile:
    known = ", ".join(sorted(profiles))
    raise SystemExit(f"unknown profile '{profile_name}' in {matrix_path}; known: {known}")

env_updates = profile.get("env") or {}
if not env_updates:
    raise SystemExit(f"profile '{profile_name}' has no env block in {matrix_path}")

lines = env_path.read_text(encoding="utf-8").splitlines()
out: list[str] = []
seen: set[str] = set()
for line in lines:
    replaced = False
    for key, value in env_updates.items():
        prefix = f"{key}="
        if line.startswith(prefix):
            out.append(f"{key}={value}")
            seen.add(key)
            replaced = True
            break
    if not replaced:
        out.append(line)

for key, value in env_updates.items():
    if key not in seen:
        out.append(f"{key}={value}")

env_path.write_text("\n".join(out) + "\n", encoding="utf-8")

origin = profile.get("customer_ui_origin", "")
port = profile.get("customer_ui_port", "")
label = profile.get("label", profile_name)
print(f"SYNCED|{origin}|{port}|{label}")

callbacks = profile.get("external_callbacks") or {}
for section, payload in callbacks.items():
    if not isinstance(payload, dict):
        continue
    for field, values in payload.items():
        if field in {"console_url", "console_hint"}:
            continue
        if isinstance(values, list):
            for item in values:
                print(f"CALLBACK|{section}|{field}|{item}")
        elif isinstance(values, str):
            print(f"CALLBACK|{section}|{field}|{values}")
PY
)"

if [[ $? -ne 0 ]]; then
  fail "failed to sync env from matrix"
fi

ORIGIN=""
PORT=""
LABEL=""
CALLBACK_LINES=()
while IFS= read -r line; do
  case "$line" in
    SYNCED\|*)
      IFS='|' read -r _ ORIGIN PORT LABEL <<<"$line"
      ;;
    CALLBACK\|*)
      CALLBACK_LINES+=("$line")
      ;;
  esac
done <<<"$SYNC_RESULT"

log "profile: $PROFILE ($LABEL)"
log "customer UI origin: $ORIGIN (port $PORT)"
log "updated: $ENV_FILE"

cat <<EOF

External OAuth callback checklist (register before testing sign-in / Credentials UI)
==================================================================================

Google Cloud OAuth client ($ORIGIN)
  Console: https://console.cloud.google.com/apis/credentials
EOF

google_js=()
google_redirects=()
for entry in "${CALLBACK_LINES[@]}"; do
  IFS='|' read -r _ section field value <<<"$entry"
  if [[ "$section" == "google_cloud" && "$field" == "javascript_origins" ]]; then
    google_js+=("$value")
  elif [[ "$section" == "google_cloud" && "$field" == "redirect_uris" ]]; then
    google_redirects+=("$value")
  fi
done

printf '  Authorized JavaScript origins:\n'
for origin_entry in "${google_js[@]}"; do
  printf '    - %s\n' "$origin_entry"
done
printf '  Authorized redirect URIs:\n'
for redirect in "${google_redirects[@]}"; do
  printf '    - %s\n' "$redirect"
done

cat <<EOF

Salesforce Connected App
  OAuth settings → Callback URL:
EOF

for entry in "${CALLBACK_LINES[@]}"; do
  IFS='|' read -r _ section field value <<<"$entry"
  if [[ "$section" == "salesforce" && "$field" == "callback_urls" ]]; then
    printf '    - %s\n' "$value"
  fi
done

for provider in linkedin github; do
  provider_redirects=()
  for entry in "${CALLBACK_LINES[@]}"; do
    IFS='|' read -r _ section field value <<<"$entry"
    if [[ "$section" == "$provider" ]]; then
      provider_redirects+=("$value")
    fi
  done
  if [[ ${#provider_redirects[@]} -gt 0 ]]; then
    printf '\n%s (optional — Credentials UI)\n' "${provider^}"
    for redirect in "${provider_redirects[@]}"; do
      printf '    - %s\n' "$redirect"
    done
  fi
done

cat <<EOF

Next steps
----------
  - Open the customer UI at $ORIGIN (use localhost consistently; avoid 127.0.0.1)
  - Recreate API after env change:
      docker compose --env-file $ENV_FILE -f $ROOT_DIR/deploy/compose/docker-compose.prod.yml up -d api --force-recreate
EOF

if [[ "$PROFILE" == "vite" ]]; then
  cat <<EOF
  - Start Vite: cd frontend && npm run dev  (proxies /v1 → http://localhost:8000)
EOF
else
  cat <<EOF
  - Rebuild stack if frontend image changed:
      docker compose --env-file $ENV_FILE -f $ROOT_DIR/deploy/compose/docker-compose.prod.yml up -d --build
EOF
fi

cat <<EOF
  - Credential console links + env checklist:
      bash $ROOT_DIR/scripts/dev/credentials-setup-guide.sh --profile $PROFILE
  - Sync master secrets into this env file (edit ~/.ajenda/runtime-secrets.env once):
      bash $ROOT_DIR/scripts/dev/sync-local-secrets.sh --bootstrap --recreate-api
EOF