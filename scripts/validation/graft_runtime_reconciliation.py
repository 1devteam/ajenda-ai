#!/usr/bin/env python3
"""Validate a tenant-scoped exported runtime snapshot without mutating runtime."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.services.runtime_reconciliation_contract import (
    ReconciliationFinding as ReconciliationFinding,
)
from backend.services.runtime_reconciliation_contract import (
    RuntimeReconciliationSnapshot as RuntimeReconciliationSnapshot,
)
from backend.services.runtime_reconciliation_contract import (
    RuntimeStage as RuntimeStage,
)
from backend.services.runtime_reconciliation_contract import (
    STAGES as STAGES,
)
from backend.services.runtime_reconciliation_contract import (
    SnapshotProvenance as SnapshotProvenance,
)
from backend.services.runtime_reconciliation_contract import (
    reconcile_snapshot as reconcile_snapshot,
)
from backend.services.runtime_reconciliation_contract import (
    seal_snapshot as seal_snapshot,
)
from backend.services.runtime_reconciliation_contract import (
    snapshot_digest as snapshot_digest,
)

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path, help="Tenant-scoped exported reconciliation snapshot JSON")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        snapshot = RuntimeReconciliationSnapshot.model_validate_json(args.snapshot.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError) as exc:
        print(f"FAIL: invalid reconciliation snapshot: {exc}")
        return 1
    report = reconcile_snapshot(snapshot)
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(f"Runtime reconciliation: {report['status']} ({report['unresolved_finding_count']} unresolved findings)")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
