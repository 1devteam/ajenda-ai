from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "validation" / "seed_recovery_matrix.py"


def _run(*args: str, extra_env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(extra_env)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=SCRIPT.parents[2],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_seeder_requires_explicit_isolated_confirmation() -> None:
    result = _run(extra_env={"AJENDA_VALIDATION_ENV": "isolated", "AJENDA_ENV": "staging"})

    assert result.returncode == 1
    assert "--confirm-isolated" in result.stderr or "--confirm-isolated" in result.stdout


def test_seeder_refuses_production_even_with_confirmation() -> None:
    result = _run(
        "--confirm-isolated",
        extra_env={
            "AJENDA_VALIDATION_ENV": "isolated",
            "AJENDA_ENV": "production",
        },
    )

    assert result.returncode == 1
    assert "production" in (result.stderr + result.stdout).lower()


def test_seeder_requires_isolated_validation_environment() -> None:
    result = _run(extra_env={"AJENDA_VALIDATION_ENV": "staging", "AJENDA_ENV": "staging"})

    assert result.returncode == 1
    assert "isolated" in (result.stderr + result.stdout).lower()
