#!/usr/bin/env bash
set -euo pipefail

export AJENDA_DATABASE_URL="${AJENDA_DATABASE_URL:-postgresql+psycopg://ajenda_test:ajenda_test@localhost:5432/ajenda_test}"
export AJENDA_QUEUE_URL="${AJENDA_QUEUE_URL:-redis://localhost:6379/0}"
export AJENDA_ENV="${AJENDA_ENV:-test}"
export AJENDA_LOG_LEVEL="${AJENDA_LOG_LEVEL:-WARNING}"
export AJENDA_LOG_JSON="${AJENDA_LOG_JSON:-false}"
export AJENDA_APP_NAME="${AJENDA_APP_NAME:-Ajenda AI Test}"
export AJENDA_OIDC_ISSUER="${AJENDA_OIDC_ISSUER:-}"
export AJENDA_OIDC_AUDIENCE="${AJENDA_OIDC_AUDIENCE:-ajenda-api}"
export AJENDA_QUEUE_ADAPTER="${AJENDA_QUEUE_ADAPTER:-redis}"
export AJENDA_RATE_LIMIT_REQUESTS="${AJENDA_RATE_LIMIT_REQUESTS:-10000}"
export AJENDA_RATE_LIMIT_WINDOW_SECONDS="${AJENDA_RATE_LIMIT_WINDOW_SECONDS:-60}"
export AJENDA_REDACT_KEYS="${AJENDA_REDACT_KEYS:-password,secret,token,api_key,authorization,cookie,set-cookie}"

alembic upgrade head
alembic downgrade base
alembic upgrade head
python -m pytest tests/integration/ -v --tb=short -m "integration" --timeout=60
