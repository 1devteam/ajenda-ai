#!/usr/bin/env bash
# Schema-aware ECS service rollback.
#
# This script changes service task definitions only. It never invokes Alembic or
# claims that application rollback reverses a schema migration.
set -euo pipefail

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

require() {
  local name="$1"
  [[ -n "${!name:-}" ]] || fail "${name} must be set"
}

for required in \
  AJENDA_ECS_SCHEMA_COMPATIBILITY_APPROVED \
  AJENDA_ECS_CLUSTER \
  AJENDA_ECS_API_SERVICE \
  AJENDA_ECS_API_TASK_DEFINITION \
  AJENDA_ECS_WORKER_SERVICE \
  AJENDA_ECS_WORKER_TASK_DEFINITION \
  AJENDA_ECS_ASSURANCE_SERVICE \
  AJENDA_ECS_ASSURANCE_TASK_DEFINITION \
  AJENDA_ECS_API_BASE_URL; do
  require "$required"
done

[[ "$AJENDA_ECS_SCHEMA_COMPATIBILITY_APPROVED" == "1" ]] || fail "Schema compatibility approval is required before application rollback"
command -v aws >/dev/null || fail "AWS CLI is required"
command -v curl >/dev/null || fail "curl is required for readiness verification"

rollback_service() {
  local service="$1"
  local task_definition="$2"
  printf '%s\n' "Rolling ${service} to ${task_definition}"
  aws ecs update-service \
    --cluster "$AJENDA_ECS_CLUSTER" \
    --service "$service" \
    --task-definition "$task_definition" \
    --force-new-deployment \
    --no-cli-pager >/dev/null
  aws ecs wait services-stable --cluster "$AJENDA_ECS_CLUSTER" --services "$service"
}

rollback_service "$AJENDA_ECS_API_SERVICE" "$AJENDA_ECS_API_TASK_DEFINITION"
rollback_service "$AJENDA_ECS_WORKER_SERVICE" "$AJENDA_ECS_WORKER_TASK_DEFINITION"
rollback_service "$AJENDA_ECS_ASSURANCE_SERVICE" "$AJENDA_ECS_ASSURANCE_TASK_DEFINITION"

if [[ -n "${AJENDA_ECS_FRONTEND_SERVICE:-}" || -n "${AJENDA_ECS_FRONTEND_TASK_DEFINITION:-}" ]]; then
  require AJENDA_ECS_FRONTEND_SERVICE
  require AJENDA_ECS_FRONTEND_TASK_DEFINITION
  rollback_service "$AJENDA_ECS_FRONTEND_SERVICE" "$AJENDA_ECS_FRONTEND_TASK_DEFINITION"
fi

curl --fail --silent --show-error --max-time "${AJENDA_ECS_READINESS_TIMEOUT_SECONDS:-20}" "${AJENDA_ECS_API_BASE_URL%/}/readiness" >/dev/null
printf '%s\n' "Application rollback complete. The database schema was not changed."
