"""Syntax guards for deployment shell scripts."""

from __future__ import annotations

import subprocess
from pathlib import Path

DEPLOY_SCRIPTS_DIR = Path("deploy/scripts")

EXPECTED_DEPLOY_SCRIPTS = frozenset(
    {
        "healthcheck.sh",
        "live-runtime-proof.sh",
        "readinesscheck.sh",
        "rollback.sh",
        "run-migrations.sh",
        "start-api.sh",
        "start-worker.sh",
    }
)


def _shell_scripts() -> list[Path]:
    return sorted(DEPLOY_SCRIPTS_DIR.glob("*.sh"))


def test_expected_deploy_shell_scripts_are_present() -> None:
    actual = {path.name for path in _shell_scripts()}

    missing = EXPECTED_DEPLOY_SCRIPTS - actual

    assert not missing, f"Missing expected deploy shell scripts: {sorted(missing)}"


def test_deploy_shell_scripts_parse_with_bash() -> None:
    for script_path in _shell_scripts():
        result = subprocess.run(
            ["bash", "-n", str(script_path)],
            capture_output=True,
            check=False,
            text=True,
        )

        assert result.returncode == 0, (
            f"Shell syntax check failed for {script_path}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
