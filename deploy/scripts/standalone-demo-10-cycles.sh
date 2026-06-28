#!/usr/bin/env bash
# Run 10 standalone brain demo cycles (Ajenda profile → retrieval → research).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$ROOT_DIR"
exec python -m pytest tests/integration/standalone/test_standalone_brain_demo_cycles.py -v --tb=short "$@"