#!/usr/bin/env bash
# Print console links and env-var checklist for obtaining Ajenda credentials.
# Never prints secret values — only SET / MISSING / PLACEHOLDER status.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MATRIX_FILE="${AJENDA_LOCAL_DEV_MATRIX:-$ROOT_DIR/deploy/compose/local-dev.matrix.yaml}"
ENV_FILE="${AJENDA_RUNTIME_ENV_FILE:-$ROOT_DIR/deploy/compose/.env.prod}"
PROFILE="vite"

usage() {
  cat <<USAGE
Usage: $(basename "$0") [--profile vite|compose]

Shows where to obtain API keys and OAuth credentials (with console links),
which env vars to set, and whether each is already configured locally.

Does not print secret values.

Related:
  bash scripts/dev/sync-local-env.sh --profile vite   # align redirect URIs
  bash scripts/google/create_cli_oauth_client.sh      # Gmail CLI OAuth setup
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
      printf 'ERROR: unknown argument: %s\n' "$1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

[[ "$PROFILE" == "vite" || "$PROFILE" == "compose" ]] || {
  printf 'ERROR: --profile must be vite or compose\n' >&2
  exit 1
}

python3 - "$ROOT_DIR" "$MATRIX_FILE" "$ENV_FILE" "$PROFILE" <<'PY'
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError as exc:
    raise SystemExit(
        "PyYAML is required. Install with: python3 -m pip install pyyaml"
    ) from exc

root = Path(sys.argv[1])
matrix_path = Path(sys.argv[2])
env_path = Path(sys.argv[3])
profile_name = sys.argv[4]

PLACEHOLDER_RE = re.compile(
    r"^(|CHANGE_ME.*|sk_(test|live)_CHANGE_ME|pk_(test|live)_CHANGE_ME|"
    r"whsec(_test)?_CHANGE_ME|price_(test_)?(starter|pro|CHANGE_ME).*|re_CHANGE_ME)$",
    re.IGNORECASE,
)


def expand(path_str: str | None) -> Path | None:
    if not path_str:
        return None
    return Path(path_str.replace("~", str(Path.home())))


def parse_env(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip("'").strip('"')
        if value.endswith('"') and not value.startswith('"'):
            # Multiline JSON blobs in e2e.env — treat as set if non-empty opener.
            value = value or raw
        out[key.strip()] = value
    return out


def status(value: str | None) -> str:
    if value is None or not str(value).strip():
        return "MISSING"
    if PLACEHOLDER_RE.match(str(value).strip()):
        return "PLACEHOLDER"
    return "SET"


def print_var(name: str, env: dict[str, str], indent: str = "    ") -> None:
    st = status(env.get(name))
    print(f"{indent}{name}: {st}")


matrix = yaml.safe_load(matrix_path.read_text(encoding="utf-8"))
profiles = matrix.get("profiles") or {}
profile = profiles.get(profile_name)
if not profile:
    known = ", ".join(sorted(profiles))
    raise SystemExit(f"unknown profile '{profile_name}'; known: {known}")

origin = profile.get("customer_ui_origin", "")
label = profile.get("label", profile_name)
callbacks = profile.get("external_callbacks") or {}
sources = matrix.get("credential_sources") or {}

runtime_env = parse_env(env_path)

print("Ajenda credentials setup guide")
print("==============================")
print(f"Profile: {profile_name} ({label})")
print(f"Customer UI: {origin}")
print(f"Runtime env: {env_path}")
print()
print("This guide lists console links and env vars. Secret values are never shown.")
print("Sync redirect URIs first:")
print(f"  bash scripts/dev/sync-local-env.sh --profile {profile_name}")
print("Push master secrets into Docker env (one-time bootstrap, then re-run after key changes):")
print("  bash scripts/dev/sync-local-secrets.sh --bootstrap --recreate-api")
print(f"  Master file: {Path.home() / '.ajenda' / 'runtime-secrets.env'}")
print("Test inboxes for live email proof:")
print(f"  {Path.home() / '.ajenda' / 'test-emails.env'}")
print("  bash scripts/dev/email-send-proof.sh")
print()

# OAuth redirect checklist for active profile
print("OAuth redirect URIs to register (profile-specific)")
print("--------------------------------------------------")
google = callbacks.get("google_cloud") or {}
if google.get("console_url"):
    print(f"Google Cloud credentials: {google['console_url']}")
if isinstance(google.get("javascript_origins"), list):
    print("  Authorized JavaScript origins:")
    for item in google["javascript_origins"]:
        print(f"    - {item}")
if isinstance(google.get("redirect_uris"), list):
    print("  Authorized redirect URIs:")
    for item in google["redirect_uris"]:
        print(f"    - {item}")

sf = callbacks.get("salesforce") or {}
if sf:
    src = sources.get("salesforce") or {}
    console = (src.get("console") or {}).get("connected_apps")
    if console:
        print(f"\nSalesforce Connected Apps: {console}")
    if isinstance(sf.get("callback_urls"), list):
        print("  Callback URLs:")
        for item in sf["callback_urls"]:
            print(f"    - {item}")

print()

for key, spec in sources.items():
    if spec.get("enabled") is False:
        continue
    spec_label = spec.get("label", key)
    required = spec.get("required_for_local", False)
    badge = "required for local dev" if required else "optional"
    print(f"{spec_label} [{badge}]")
    print("-" * len(f"{spec_label} [{badge}]"))

    console = spec.get("console") or {}
    for ckey, url in console.items():
        if url:
            title = ckey.replace("_", " ").title()
            print(f"  {title}: {url}")

    rel_env = spec.get("env_file")
    if rel_env:
        path = root / rel_env if not Path(rel_env).is_absolute() else Path(rel_env)
        env = runtime_env if path.resolve() == env_path.resolve() else parse_env(path)
        print(f"  Env file: {path}")
        for var in spec.get("env_vars") or []:
            print_var(var, env)

    cli_file = expand(spec.get("cli_env_file"))
    if cli_file:
        cli_env = parse_env(cli_file)
        print(f"  CLI env file: {cli_file}")
        for var in spec.get("cli_env_vars") or []:
            print_var(var, cli_env)

    e2e_file = expand(spec.get("e2e_env_file"))
    if e2e_file:
        e2e_env = parse_env(e2e_file)
        print(f"  E2E env file: {e2e_file}")
        for var in spec.get("e2e_env_vars") or []:
            print_var(var, e2e_env)

    gen = spec.get("generate_cmd")
    if gen:
        print(f"  Generate: {gen}")

    notes = (spec.get("notes") or "").strip()
    if notes:
        for line in notes.splitlines():
            print(f"  Note: {line.strip()}")
    print()

print("After updating deploy/compose/.env.prod, recreate the API:")
print(
    f"  docker compose --env-file {env_path} "
    f"-f {root / 'deploy/compose/docker-compose.prod.yml'} up -d api --force-recreate"
)
print()
print("Per-tenant tokens (Gmail, HubSpot, etc.) are registered in the product UI:")
print(f"  {origin}/credentials")
PY