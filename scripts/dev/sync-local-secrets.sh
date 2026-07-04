#!/usr/bin/env bash
# Keep ~/.ajenda/runtime-secrets.env as the single master for local API keys,
# then upsert them into deploy/compose/.env.prod for Docker services.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SECRETS_FILE="${AJENDA_RUNTIME_SECRETS_FILE:-$HOME/.ajenda/runtime-secrets.env}"
ENV_FILE="${AJENDA_RUNTIME_ENV_FILE:-$ROOT_DIR/deploy/compose/.env.prod}"
EXAMPLE_FILE="$ROOT_DIR/scripts/dev/runtime-secrets.env.example"
BOOTSTRAP=false
RECREATE_API=false

log() {
  printf '[sync-local-secrets] %s\n' "$*"
}

fail() {
  printf '[sync-local-secrets] ERROR: %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<USAGE
Usage: $(basename "$0") [--bootstrap] [--recreate-api]

Master secrets file: ~/.ajenda/runtime-secrets.env
Runtime env target:  deploy/compose/.env.prod

  --bootstrap     Create/update master file from existing ~/.ajenda/*.env and .env.prod
  --recreate-api  After sync, recreate the api container to load new env

Typical local workflow:
  bash scripts/dev/sync-local-env.sh --profile vite
  bash scripts/dev/sync-local-secrets.sh --bootstrap
  bash scripts/dev/sync-local-secrets.sh --recreate-api
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --bootstrap)
      BOOTSTRAP=true
      shift
      ;;
    --recreate-api)
      RECREATE_API=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "unknown argument: $1"
      ;;
  esac
done

[[ -f "$ENV_FILE" ]] || fail "missing runtime env file: $ENV_FILE (run sync-local-env.sh first)"

SYNC_RESULT="$(python3 - "$SECRETS_FILE" "$ENV_FILE" "$EXAMPLE_FILE" "$BOOTSTRAP" <<'PY'
from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    from cryptography.fernet import Fernet
except ImportError:
    Fernet = None  # type: ignore[misc, assignment]

secrets_path = Path(sys.argv[1]).expanduser()
env_path = Path(sys.argv[2])
example_path = Path(sys.argv[3])
bootstrap = sys.argv[4].lower() == "true"

PLACEHOLDER_RE = re.compile(
    r"^(|CHANGE_ME.*|sk_(test|live)_CHANGE_ME|pk_(test|live)_CHANGE_ME|"
    r"whsec(_test)?_CHANGE_ME|price_(test_)?(starter|pro|CHANGE_ME).*|re_CHANGE_ME)$",
    re.IGNORECASE,
)

MANAGED_KEYS = [
    "AJENDA_OIDC_CLIENT_ID",
    "AJENDA_OIDC_CLIENT_SECRET",
    "AJENDA_SESSION_SIGNING_SECRET",
    "AJENDA_SALESFORCE_CLIENT_ID",
    "AJENDA_SALESFORCE_CLIENT_SECRET",
    "AJENDA_WEBHOOK_SECRET_ENCRYPTION_KEY",
    "AJENDA_RUNTIME_SECRET_ENCRYPTION_KEY",
    "AJENDA_HUBSPOT_PLATFORM_MASTER_KEY_ENABLED",
    "AJENDA_HUBSPOT_PLATFORM_MASTER_KEY",
    "AJENDA_HUBSPOT_PLATFORM_MASTER_AUTO_PROVISION",
    "AJENDA_LLM_API_KEY",
    "AJENDA_LLM_BASE_URL",
    "AJENDA_LLM_MODEL",
    "AJENDA_EMAIL_PLATFORM_MASTER_KEY_ENABLED",
    "AJENDA_EMAIL_PLATFORM_SMTP_SECRET",
    "AJENDA_EMAIL_PLATFORM_MASTER_AUTO_PROVISION",
    "STRIPE_SECRET_KEY",
    "STRIPE_PUBLISHABLE_KEY",
    "STRIPE_WEBHOOK_SECRET",
    "STRIPE_PRICE_STARTER",
    "STRIPE_PRICE_PRO",
    "AJENDA_RESEND_API_KEY",
]

ALIASES = {
    "AJENDA_OIDC_CLIENT_ID": ["AJENDA_GOOGLE_CLI_CLIENT_ID"],
    "AJENDA_OIDC_CLIENT_SECRET": ["AJENDA_GOOGLE_CLI_CLIENT_SECRET"],
}


def parse_env_text(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        if value:
            out[key.strip()] = value
    return out


def parse_env_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    return parse_env_text(path.read_text(encoding="utf-8"))


def is_real(value: str | None) -> bool:
    if value is None:
        return False
    text = str(value).strip()
    if not text:
        return False
    return not PLACEHOLDER_RE.match(text)


def write_env_file(path: Path, values: dict[str, str], *, header: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [header.rstrip(), ""]
    for key in MANAGED_KEYS:
        val = values.get(key, "")
        if val:
            lines.append(f"{key}={val}")
        else:
            lines.append(f"# {key}=")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    path.chmod(0o600)


def upsert_env(path: Path, updates: dict[str, str]) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    seen: set[str] = set()
    applied: list[str] = []

    for line in lines:
        replaced = False
        for key, value in updates.items():
            if line.startswith(f"{key}="):
                out.append(f"{key}={value}")
                seen.add(key)
                applied.append(key)
                replaced = True
                break
        if not replaced:
            out.append(line)

    for key, value in updates.items():
        if key not in seen:
            out.append(f"{key}={value}")
            applied.append(key)

    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return applied


def generate_fernet() -> str:
    if Fernet is None:
        raise SystemExit(
            "cryptography package required for --bootstrap. "
            "Install with: python3 -m pip install cryptography"
        )
    return Fernet.generate_key().decode()


def generate_session_secret() -> str:
    import secrets

    return secrets.token_urlsafe(48)


def collect_bootstrap_values() -> dict[str, str]:
    sources: list[Path] = [
        secrets_path,
        env_path,
        Path.home() / ".ajenda" / "google-cli.env",
        Path.home() / ".ajenda" / "salesforce-cli.env",
        Path.home() / ".ajenda" / "e2e.env",
    ]
    merged: dict[str, str] = {}
    for path in sources:
        data = parse_env_file(path)
        for key, value in data.items():
            if is_real(value) and key not in merged:
                merged[key] = value
        for key, aliases in ALIASES.items():
            if is_real(merged.get(key)):
                continue
            for alias in aliases:
                alias_val = data.get(alias)
                if is_real(alias_val):
                    merged[key] = alias_val
                    break

    if not is_real(merged.get("AJENDA_SESSION_SIGNING_SECRET")):
        merged["AJENDA_SESSION_SIGNING_SECRET"] = generate_session_secret()
    if not is_real(merged.get("AJENDA_WEBHOOK_SECRET_ENCRYPTION_KEY")):
        merged["AJENDA_WEBHOOK_SECRET_ENCRYPTION_KEY"] = generate_fernet()
    if not is_real(merged.get("AJENDA_RUNTIME_SECRET_ENCRYPTION_KEY")):
        merged["AJENDA_RUNTIME_SECRET_ENCRYPTION_KEY"] = generate_fernet()

    hubspot_pak = merged.get("AJENDA_E2E_HUBSPOT_PAK") or merged.get("AJENDA_HUBSPOT_PLATFORM_MASTER_KEY")
    if is_real(hubspot_pak):
        merged["AJENDA_HUBSPOT_PLATFORM_MASTER_KEY"] = hubspot_pak
        merged.setdefault("AJENDA_HUBSPOT_PLATFORM_MASTER_KEY_ENABLED", "true")
        merged.setdefault("AJENDA_HUBSPOT_PLATFORM_MASTER_AUTO_PROVISION", "true")

    return {key: merged[key] for key in MANAGED_KEYS if is_real(merged.get(key))}


header = """# Ajenda local runtime secrets (master copy)
# Synced into deploy/compose/.env.prod by: bash scripts/dev/sync-local-secrets.sh
# Never commit this file."""

if bootstrap or not secrets_path.is_file():
    if not example_path.is_file():
        raise SystemExit(f"missing example file: {example_path}")
    values = collect_bootstrap_values()
    write_env_file(secrets_path, values, header=header)
    print(f"BOOTSTRAP|{secrets_path}|{len(values)}")

secrets = parse_env_file(secrets_path)
updates = {key: secrets[key] for key in MANAGED_KEYS if is_real(secrets.get(key))}
if not updates:
    raise SystemExit(
        f"No secrets to sync from {secrets_path}. "
        "Edit the file or run with --bootstrap."
    )

applied = upsert_env(env_path, updates)
print(f"SYNCED|{env_path}|{','.join(applied)}")
PY
)" || fail "failed to sync secrets"

while IFS= read -r line; do
  case "$line" in
    BOOTSTRAP\|*)
      IFS='|' read -r _ path count <<<"$line"
      log "bootstrapped master secrets: $path ($count keys)"
      ;;
    SYNCED\|*)
      IFS='|' read -r _ path keys <<<"$line"
      log "synced into runtime env: $path"
      log "keys: ${keys//,/, }"
      ;;
  esac
done <<<"$SYNC_RESULT"

log "master file: $SECRETS_FILE (edit here when keys change)"
log "E2E tokens stay in ~/.ajenda/e2e.env — refresh with: python3 scripts/generate_e2e_tokens.py"

if [[ "$RECREATE_API" == "true" ]]; then
  log "recreating api container..."
  docker compose -p compose --env-file "$ENV_FILE" \
    -f "$ROOT_DIR/deploy/compose/docker-compose.prod.yml" \
    up -d api --force-recreate
fi