#!/usr/bin/env bash
# Controlled AWS ECS promotion for an already-provisioned Ajenda environment.
#
# This command never runs Terraform, provisions database roles, or decides that
# an image is safe. It receives exact task-definition revisions created from
# immutable artifacts, runs the dedicated migrator, then promotes services.
set -euo pipefail

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

require() {
  local name="$1"
  [[ -n "${!name:-}" ]] || fail "${name} must be set"
}

require_positive_integer() {
  local name="$1"
  [[ "${!name}" =~ ^[1-9][0-9]*$ ]] || fail "${name} must be a positive integer"
}

require_capacity_range() {
  local service="$1"
  local minimum="$2"
  local desired="$3"
  local maximum="$4"
  (( minimum <= desired && desired <= maximum )) || fail "${service} requires minimum <= desired <= maximum"
}

for required in \
  AJENDA_ECS_PROMOTION_APPROVED \
  AJENDA_ECS_CLUSTER \
  AJENDA_ECS_SUBNETS \
  AJENDA_ECS_SECURITY_GROUPS \
  AJENDA_ECS_MIGRATOR_TASK_DEFINITION \
  AJENDA_ECS_API_SERVICE \
  AJENDA_ECS_API_TASK_DEFINITION \
  AJENDA_ECS_API_DESIRED_COUNT \
  AJENDA_ECS_API_MIN_COUNT \
  AJENDA_ECS_API_MAX_COUNT \
  AJENDA_ECS_WORKER_SERVICE \
  AJENDA_ECS_WORKER_TASK_DEFINITION \
  AJENDA_ECS_WORKER_DESIRED_COUNT \
  AJENDA_ECS_WORKER_MIN_COUNT \
  AJENDA_ECS_WORKER_MAX_COUNT \
  AJENDA_ECS_ASSURANCE_SERVICE \
  AJENDA_ECS_ASSURANCE_TASK_DEFINITION \
  AJENDA_ECS_ASSURANCE_DESIRED_COUNT \
  AJENDA_ECS_API_BASE_URL; do
  require "$required"
done

[[ "$AJENDA_ECS_PROMOTION_APPROVED" == "1" ]] || fail "set AJENDA_ECS_PROMOTION_APPROVED=1 after release review"
for count in \
  AJENDA_ECS_API_DESIRED_COUNT \
  AJENDA_ECS_API_MIN_COUNT \
  AJENDA_ECS_API_MAX_COUNT \
  AJENDA_ECS_WORKER_DESIRED_COUNT \
  AJENDA_ECS_WORKER_MIN_COUNT \
  AJENDA_ECS_WORKER_MAX_COUNT \
  AJENDA_ECS_ASSURANCE_DESIRED_COUNT; do
  require_positive_integer "$count"
done
require_capacity_range api "$AJENDA_ECS_API_MIN_COUNT" "$AJENDA_ECS_API_DESIRED_COUNT" "$AJENDA_ECS_API_MAX_COUNT"
require_capacity_range worker "$AJENDA_ECS_WORKER_MIN_COUNT" "$AJENDA_ECS_WORKER_DESIRED_COUNT" "$AJENDA_ECS_WORKER_MAX_COUNT"
command -v aws >/dev/null || fail "AWS CLI is required"
command -v curl >/dev/null || fail "curl is required for readiness verification"

network_configuration="awsvpcConfiguration={subnets=[${AJENDA_ECS_SUBNETS}],securityGroups=[${AJENDA_ECS_SECURITY_GROUPS}],assignPublicIp=DISABLED}"
started_by="ajenda-promote-$(date -u +%Y%m%dT%H%M%SZ)"

printf '%s\n' "Starting dedicated migrator task for ${AJENDA_ECS_MIGRATOR_TASK_DEFINITION}"
migrator_task_arn="$(aws ecs run-task \
  --cluster "$AJENDA_ECS_CLUSTER" \
  --launch-type FARGATE \
  --task-definition "$AJENDA_ECS_MIGRATOR_TASK_DEFINITION" \
  --network-configuration "$network_configuration" \
  --started-by "$started_by" \
  --query 'tasks[0].taskArn' \
  --output text)"
[[ -n "$migrator_task_arn" && "$migrator_task_arn" != "None" ]] || fail "ECS did not return a migrator task ARN"

aws ecs wait tasks-stopped --cluster "$AJENDA_ECS_CLUSTER" --tasks "$migrator_task_arn"
migrator_exit_code="$(aws ecs describe-tasks \
  --cluster "$AJENDA_ECS_CLUSTER" \
  --tasks "$migrator_task_arn" \
  --query 'tasks[0].containers[0].exitCode' \
  --output text)"
[[ "$migrator_exit_code" == "0" ]] || fail "migrator task failed (exit ${migrator_exit_code}); no runtime service was changed"

promote_service() {
  local service="$1"
  local task_definition="$2"
  local desired_count="$3"
  printf '%s\n' "Promoting ${service} to ${task_definition} with desired count ${desired_count}"
  aws ecs update-service \
    --cluster "$AJENDA_ECS_CLUSTER" \
    --service "$service" \
    --task-definition "$task_definition" \
    --desired-count "$desired_count" \
    --force-new-deployment \
    --no-cli-pager >/dev/null
  aws ecs wait services-stable --cluster "$AJENDA_ECS_CLUSTER" --services "$service"
}

configure_scaling() {
  local service="$1"
  local minimum="$2"
  local maximum="$3"
  aws application-autoscaling register-scalable-target \
    --service-namespace ecs \
    --resource-id "service/${AJENDA_ECS_CLUSTER}/${service}" \
    --scalable-dimension ecs:service:DesiredCount \
    --min-capacity "$minimum" \
    --max-capacity "$maximum" \
    --no-cli-pager >/dev/null
}

promote_service "$AJENDA_ECS_API_SERVICE" "$AJENDA_ECS_API_TASK_DEFINITION" "$AJENDA_ECS_API_DESIRED_COUNT"
configure_scaling "$AJENDA_ECS_API_SERVICE" "$AJENDA_ECS_API_MIN_COUNT" "$AJENDA_ECS_API_MAX_COUNT"
promote_service "$AJENDA_ECS_WORKER_SERVICE" "$AJENDA_ECS_WORKER_TASK_DEFINITION" "$AJENDA_ECS_WORKER_DESIRED_COUNT"
configure_scaling "$AJENDA_ECS_WORKER_SERVICE" "$AJENDA_ECS_WORKER_MIN_COUNT" "$AJENDA_ECS_WORKER_MAX_COUNT"
promote_service "$AJENDA_ECS_ASSURANCE_SERVICE" "$AJENDA_ECS_ASSURANCE_TASK_DEFINITION" "$AJENDA_ECS_ASSURANCE_DESIRED_COUNT"

if [[ -n "${AJENDA_ECS_FRONTEND_SERVICE:-}" || -n "${AJENDA_ECS_FRONTEND_TASK_DEFINITION:-}" ]]; then
  require AJENDA_ECS_FRONTEND_SERVICE
  require AJENDA_ECS_FRONTEND_TASK_DEFINITION
  require AJENDA_ECS_FRONTEND_DESIRED_COUNT
  require_positive_integer AJENDA_ECS_FRONTEND_DESIRED_COUNT
  promote_service "$AJENDA_ECS_FRONTEND_SERVICE" "$AJENDA_ECS_FRONTEND_TASK_DEFINITION" "$AJENDA_ECS_FRONTEND_DESIRED_COUNT"
fi

readiness_url="${AJENDA_ECS_API_BASE_URL%/}/readiness"
curl --fail --silent --show-error --max-time "${AJENDA_ECS_READINESS_TIMEOUT_SECONDS:-20}" "$readiness_url" >/dev/null

if [[ -n "${AJENDA_ECS_POST_DEPLOY_PROOF_SCRIPT:-}" ]]; then
  [[ -x "$AJENDA_ECS_POST_DEPLOY_PROOF_SCRIPT" ]] || fail "post-deploy proof script is not executable"
  "$AJENDA_ECS_POST_DEPLOY_PROOF_SCRIPT"
fi

printf '%s\n' "Promotion complete: migrator=${migrator_task_arn}; readiness=${readiness_url}"
