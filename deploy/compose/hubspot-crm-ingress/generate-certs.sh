#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CERT_DIR="$SCRIPT_DIR/certs"
mkdir -p "$CERT_DIR"

if [[ -f "$CERT_DIR/server.crt" && -f "$CERT_DIR/server.key" ]]; then
  echo "HubSpot ingress certs already exist in $CERT_DIR"
  exit 0
fi

openssl req -x509 -nodes -days 825 -newkey rsa:2048 \
  -keyout "$CERT_DIR/server.key" \
  -out "$CERT_DIR/server.crt" \
  -subj "/CN=hubspot-crm-ingress" \
  -addext "subjectAltName=DNS:hubspot-crm-ingress,DNS:hubspot-crm.local"

chmod 600 "$CERT_DIR/server.key"
echo "Generated self-signed TLS certs in $CERT_DIR"