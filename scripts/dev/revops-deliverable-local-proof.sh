#!/usr/bin/env bash
# Deterministic local proof for the RevOps mission deliverable slice.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python}"

cd "$ROOT_DIR"

if ! "$PYTHON_BIN" -c "import pytest" >/dev/null 2>&1; then
  echo "[revops-local-proof] pytest is unavailable; run: pip install -e \".[dev]\"" >&2
  exit 2
fi

# Keep this proof local and effect-free even if the caller's shell contains
# provider credentials or non-production simulation settings.
export AJENDA_ENV="test"
export AJENDA_ALLOW_SIMULATED_EXTERNAL="false"

echo "[revops-local-proof] running typed assembly, API, tenant, approval, effect, and receipt proofs"

"$PYTHON_BIN" -m pytest   tests/unit/services/test_revops_mission_deliverable.py   tests/unit/api/test_mission_deliverable_route.py   tests/unit/repositories/test_execution_task_repository.py   tests/unit/tools/test_gtm_actions.py::test_gtm_email_send_simulated_when_no_credential   tests/unit/tools/test_gtm_actions.py::test_gtm_email_send_review_block_emits_canonical_attempt_artifact   tests/unit/tools/test_gtm_actions.py::test_gtm_email_send_uses_network_egress_for_real_send   tests/unit/tools/test_gtm_actions.py::test_gtm_email_send_propagates_idempotency_key_to_provider   -v   --tb=short

echo "[revops-local-proof] PASS — no external effect was performed"
