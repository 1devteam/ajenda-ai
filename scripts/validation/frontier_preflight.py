#!/usr/bin/env python3
"""Run the deterministic repository-quality preflight required by Frontier GRAFT+."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
Runner = Callable[..., subprocess.CompletedProcess[str]]

CHECKS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ruff_lint", ("ruff", "check", "backend/", "tests/", "scripts/validation/")),
    ("ruff_format", ("ruff", "format", "--check", "backend/", "tests/", "scripts/validation/")),
    ("mypy", ("mypy", "backend/")),
    ("contract_drift", (sys.executable, "scripts/validation/contract_drift_check.py")),
    ("runtime_authority_inventory", (sys.executable, "scripts/validation/runtime_authority_inventory_check.py")),
    ("migration_seed_contract", (sys.executable, "scripts/validation/migration_seed_contract_check.py")),
    ("ability_rollout_contract", (sys.executable, "scripts/validation/ability_rollout_contract_check.py")),
)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def run_frontier_preflight(*, runner: Runner = subprocess.run) -> dict[str, Any]:
    """Return compact machine evidence for the same static checks used by CI."""

    rows: list[dict[str, Any]] = []
    for check_id, command in CHECKS:
        result = runner(
            list(command),
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        stdout = result.stdout or ""
        stderr = result.stderr or ""
        row: dict[str, Any] = {
            "id": check_id,
            "rc": int(result.returncode),
            "out": _sha256(stdout),
            "err": _sha256(stderr),
        }
        if result.returncode:
            failure = (stderr or stdout)[-2000:]
            if failure:
                row["tail"] = failure
        rows.append(row)

    return {
        "v": 1,
        "k": "graft_frontier_preflight",
        "ok": all(row["rc"] == 0 for row in rows),
        "c": rows,
    }


def main() -> int:
    report = run_frontier_preflight()
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
