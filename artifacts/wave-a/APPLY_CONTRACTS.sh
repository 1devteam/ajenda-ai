#!/usr/bin/env bash
# Apply Wave A contracts surgical patch (versions + outcomes).
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
PATCH="$ROOT/artifacts/wave-a/contracts_wave_a.patch"
if [[ ! -f "$PATCH" ]]; then
  echo "missing $PATCH" >&2
  exit 1
fi
git apply --index "$PATCH"
echo "Applied contracts Wave A patch."
grep -n 'JOB_CATALOG_VERSION\|read_linkedin' backend/services/mission_composition/contracts.py | head -20
