#!/usr/bin/env bash
# Apply Wave A operator-reads matrix onto current checkout (run from repo root).
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"
PATCH="$ROOT/artifacts/wave-a/0001-feat-composition-Wave-A-operator-reads-LinkedIn-GitH.patch"
if [[ ! -f "$PATCH" ]]; then
  echo "missing $PATCH" >&2
  exit 1
fi
if grep -q 'PATCH_PLACEHOLDER' "$PATCH" 2>/dev/null; then
  echo "patch is still a placeholder — need real unified diff" >&2
  exit 1
fi
git apply --index "$PATCH"
git status --short
echo "Wave A patch applied to index. Review, then commit."
