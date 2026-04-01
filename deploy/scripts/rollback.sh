#!/usr/bin/env bash
# rollback.sh — Ajenda AI production rollback script
#
# Usage:
#   ./rollback.sh [--namespace <ns>] [--revision <n>]
#
# Examples:
#   ./rollback.sh                          # Roll back both api and worker to previous revision
#   ./rollback.sh --revision 3             # Roll back to specific revision
#   ./rollback.sh --namespace ajenda-staging
#
# Prerequisites:
#   - kubectl configured with cluster access
#   - Sufficient RBAC permissions to update Deployments
#
# Previous defect: this file contained only an echo statement and was non-functional.
set -euo pipefail

NAMESPACE="ajenda"
REVISION=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --namespace|-n) NAMESPACE="$2"; shift 2 ;;
    --revision|-r)  REVISION="$2";  shift 2 ;;
    *) echo "Unknown argument: $1"; exit 1 ;;
  esac
done

echo "=== Ajenda AI Rollback ==="
echo "Namespace : ${NAMESPACE}"
echo "Revision  : ${REVISION:-previous}"
echo ""

# Verify kubectl is available and cluster is reachable
if ! kubectl cluster-info --namespace "${NAMESPACE}" &>/dev/null; then
  echo "ERROR: Cannot reach Kubernetes cluster. Check KUBECONFIG." >&2
  exit 1
fi

# Show current state before rollback
echo "--- Current deployment state ---"
kubectl rollout history deployment/ajenda-api    --namespace "${NAMESPACE}" 2>/dev/null || true
kubectl rollout history deployment/ajenda-worker --namespace "${NAMESPACE}" 2>/dev/null || true
echo ""

ROLLBACK_ARGS=()
if [[ -n "${REVISION}" ]]; then
  ROLLBACK_ARGS+=("--to-revision=${REVISION}")
fi

echo "--- Rolling back ajenda-api ---"
kubectl rollout undo deployment/ajenda-api \
  --namespace "${NAMESPACE}" \
  "${ROLLBACK_ARGS[@]}"

echo "--- Rolling back ajenda-worker ---"
kubectl rollout undo deployment/ajenda-worker \
  --namespace "${NAMESPACE}" \
  "${ROLLBACK_ARGS[@]}"

echo ""
echo "--- Waiting for rollout to complete ---"
kubectl rollout status deployment/ajenda-api    --namespace "${NAMESPACE}" --timeout=120s
kubectl rollout status deployment/ajenda-worker --namespace "${NAMESPACE}" --timeout=120s

echo ""
echo "--- Post-rollback state ---"
kubectl get pods --namespace "${NAMESPACE}" -l 'app in (ajenda-api,ajenda-worker)'

echo ""
echo "=== Rollback complete ==="
