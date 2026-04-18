from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
RUNNER = REPO_ROOT / "scripts" / "validation" / "live_runtime_matrix.sh"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _install_fake_curl(bin_dir: Path) -> None:
    _write_executable(
        bin_dir / "curl",
        """#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

args = sys.argv[1:]
headers_file = Path(args[args.index('-D') + 1])
body_file = Path(args[args.index('-o') + 1])
url = args[-2]
headers_file.write_text('HTTP/1.1 200 OK\\n', encoding='utf-8')
if url.endswith('/v1/observability/metrics'):
    body_file.write_text('ajenda_up 1\\n', encoding='utf-8')
else:
    body_file.write_text('{"status":"ok"}\\n', encoding='utf-8')
print('200', end='')
""",
    )


def _run_runner(tmp_path: Path, *args: str, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _install_fake_curl(bin_dir)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["VALIDATION_ROOT"] = str(tmp_path / "artifacts")
    env["VALIDATION_TS"] = "20260418T010203Z"
    env["AJENDA_API_URL"] = "http://example.test"
    if extra_env:
        env.update(extra_env)

    return subprocess.run(
        ["bash", str(RUNNER), *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _artifact_root(tmp_path: Path) -> Path:
    return tmp_path / "artifacts" / "20260418T010203Z"


def test_global_mutation_scenario_is_environment_ineligible_outside_isolated_or_staging(tmp_path: Path) -> None:
    result = _run_runner(
        tmp_path,
        "--scenario",
        "RG-08",
        extra_env={"AJENDA_VALIDATION_ENV": "local"},
    )

    assert result.returncode == 1
    artifact_root = _artifact_root(tmp_path)
    scenario_dir = artifact_root / "RG-08"

    assert (scenario_dir / "run_outcome.txt").read_text(encoding="utf-8").strip() == "environment_ineligible"
    assert (scenario_dir / "evidence_status.txt").read_text(encoding="utf-8").strip() == "missing"

    scenario_results = (artifact_root / "scenario_results.tsv").read_text(encoding="utf-8")
    assert "RG-08\tenvironment_ineligible\tmissing\tlocal" in scenario_results

    summary = json.loads((artifact_root / "summary.json").read_text(encoding="utf-8"))
    assert summary["counts"]["environment_ineligible"] == 1
    assert summary["counts"]["fail"] == 0


def test_tenant_mutation_scenario_is_blocked_when_required_environment_variables_are_missing(tmp_path: Path) -> None:
    result = _run_runner(tmp_path, "--scenario", "RG-04")

    assert result.returncode == 1
    artifact_root = _artifact_root(tmp_path)
    scenario_dir = artifact_root / "RG-04"

    assert (scenario_dir / "run_outcome.txt").read_text(encoding="utf-8").strip() == "blocked"
    assert (scenario_dir / "evidence_status.txt").read_text(encoding="utf-8").strip() == "missing"
    notes = (scenario_dir / "notes.txt").read_text(encoding="utf-8")
    assert "AJENDA_SAMPLE_TASK_ID" in notes
    assert "AJENDA_TENANT_ID" in notes
    assert "AJENDA_AUTH_HEADER" in notes

    summary = json.loads((artifact_root / "summary.json").read_text(encoding="utf-8"))
    assert summary["counts"]["blocked"] == 1
    assert summary["counts"]["pass"] == 0


def test_queue_admission_records_evidence_incomplete_when_required_proof_surfaces_are_missing(tmp_path: Path) -> None:
    result = _run_runner(
        tmp_path,
        "--scenario",
        "RG-04",
        extra_env={
            "AJENDA_SAMPLE_TASK_ID": "00000000-0000-0000-0000-000000000111",
            "AJENDA_TENANT_ID": "00000000-0000-0000-0000-000000000222",
            "AJENDA_AUTH_HEADER": "Bearer fake-token",
        },
    )

    assert result.returncode == 1
    artifact_root = _artifact_root(tmp_path)
    scenario_dir = artifact_root / "RG-04"

    assert (scenario_dir / "run_outcome.txt").read_text(encoding="utf-8").strip() == "evidence_incomplete"
    assert (scenario_dir / "evidence_status.txt").read_text(encoding="utf-8").strip() == "partial"
    assert (scenario_dir / "status.txt").read_text(encoding="utf-8").strip() == "200"

    scenario_results = (artifact_root / "scenario_results.tsv").read_text(encoding="utf-8")
    assert "RG-04\tevidence_incomplete\tpartial\tlocal" in scenario_results

    summary = json.loads((artifact_root / "summary.json").read_text(encoding="utf-8"))
    assert summary["counts"]["evidence_incomplete"] == 1
    assert summary["validation_env"] == "local"
