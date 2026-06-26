#!/usr/bin/env bash
# Guide creation of a Google OAuth Desktop client for Ajenda Gmail CLI auth.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PROJECT_NUMBER="${AJENDA_GCP_PROJECT_NUMBER:-38457754291}"
CLIENT_JSON="${AJENDA_GOOGLE_CLI_CLIENT_JSON:-$HOME/.ajenda/google-cli-client.json}"

log() {
  printf '[google-cli-oauth] %s\n' "$*"
}

log "Ajenda Gmail CLI OAuth client setup"
log "GCP project number: ${PROJECT_NUMBER}"
log ""
log "Google Cloud does not expose a stable public API to create consumer OAuth clients."
log "Create the client in Console, then load it with init-client:"
log ""
log "  1. Enable Gmail API:"
log "     https://console.cloud.google.com/apis/library/gmail.googleapis.com?project=${PROJECT_NUMBER}"
log "  2. OAuth consent screen -> add scopes:"
log "     - https://www.googleapis.com/auth/gmail.readonly"
log "     - https://www.googleapis.com/auth/gmail.send"
log "  3. Credentials -> Create credentials -> OAuth client ID -> Desktop app"
log "     Name: ajenda-gmail-cli"
log "  4. Download JSON to: ${CLIENT_JSON}"
log "     chmod 600 ${CLIENT_JSON}"
log "  5. Load exports:"
log "     eval \"\$(python3 ${ROOT_DIR}/scripts/google/gmail_cli_auth.py init-client ${CLIENT_JSON} | grep '^export ')\""
log "  6. Authenticate:"
log "     python3 ${ROOT_DIR}/scripts/google/gmail_cli_auth.py auth"
log ""
log "Alternative: reuse the existing Web OIDC client and add redirect URI:"
log "  http://127.0.0.1:8765/oauth2/callback"
log "  https://console.cloud.google.com/apis/credentials?project=${PROJECT_NUMBER}"
log ""
log "Then export AJENDA_OIDC_CLIENT_ID / AJENDA_OIDC_CLIENT_SECRET (or AJENDA_GOOGLE_CLI_*)."