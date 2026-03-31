#!/usr/bin/env bash
set -euo pipefail

curl -fsS "http://127.0.0.1:${AJENDA_PORT:-8000}/system/readiness" >/dev/null
