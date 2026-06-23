from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_service_route_import_check_passes_with_allowlist() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/validation/service_route_import_check.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_service_route_import_check_strict_passes_after_phase_1b() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/validation/service_route_import_check.py", "--strict"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: no disallowed service-to-route imports." in result.stdout
