#!/usr/bin/env bash
set -euo pipefail

host="0.0.0.0"
port="${AJENDA_PORT:-8000}"
workers="${AJENDA_UVICORN_WORKERS:-1}"

if [[ "${workers}" =~ ^[0-9]+$ ]] && (( workers > 1 )); then
  exec uvicorn backend.main:app --host "${host}" --port "${port}" --workers "${workers}"
fi

exec uvicorn backend.main:app --host "${host}" --port "${port}"
