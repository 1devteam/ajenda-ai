from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "validation" / "create_recovery_operator_session.py"


def test_session_requires_isolated_confirmation() -> None:
    env = os.environ.copy()
    env.update({"AJENDA_ENV": "staging", "AJENDA_VALIDATION_ENV": "isolated"})
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--tenant-id", "00000000-0000-0000-0000-000000000001"],
        cwd=SCRIPT.parents[2],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "confirm-isolated" in result.stderr


def test_session_refuses_production() -> None:
    env = os.environ.copy()
    env.update({"AJENDA_ENV": "production", "AJENDA_VALIDATION_ENV": "isolated"})
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--tenant-id",
            "00000000-0000-0000-0000-000000000001",
            "--confirm-isolated",
        ],
        cwd=SCRIPT.parents[2],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "production" in result.stderr
