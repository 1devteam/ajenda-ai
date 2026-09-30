from __future__ import annotations

import json
import os
import re
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
RUNNER = REPO_ROOT / "scripts" / "validation" / "live_runtime_matrix.sh"
MATRIX = REPO_ROOT / "docs" / "validation" / "live-runtime-matrix.md"
RECOVERY_ROWS = {"RG-08", "RG-09", "RG-11", "FR-02", "FR-03", "FR-05"}
RUNNER_BACKING_VALUES = {"runner_only", "runner_and_contract", "runner_and_integration", "runner_contract_integration"}


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
headers_file = Path(args[args.index("-D") + 1])
body_file = Path(args[args.index("-o") + 1])

url = None
for idx, value in enumerate(args):
    if value in {"GET", "POST", "DELETE"} and idx + 1 < len(args):
        url = args[idx + 1]
        break
if url is None:
    raise SystemExit("unable to determine request URL")

tenant_header = None
auth_header = None
for idx, value in enumerate(args):
    if value == "-H" and idx + 1 < len(args):
        header = args[idx + 1]
        if header.startswith("X-Tenant-Id: "):
            tenant_header = header.split(": ", 1)[1]
        elif header.startswith("Authorization: "):
            auth_header = header.split(": ", 1)[1]

status = "200"
body = '{"status":"ok"}\\n'

if url.endswith("/v1/observability/metrics"):
    body = "ajenda_up 1\\n"
elif url.endswith("/v1/system/status"):
    if not tenant_header:
        status = "400"
        body = '{"detail":"MISSING_TENANT_ID"}\\n'
    elif tenant_header == "not-a-uuid":
        status = "400"
        body = '{"detail":"INVALID_TENANT_ID"}\\n'
    elif not auth_header:
        status = "401"
        body = '{"detail":"AUTHENTICATION_REQUIRED"}\\n'
elif "/v1/tasks/" in url and url.endswith("/queue"):
    status = "200"
    body = '{"status":"queued"}\\n'

headers_file.write_text(f"HTTP/1.1 {status} OK\\n", encoding="utf-8")
body_file.write_text(body, encoding="utf-8")
print(status, end="")
""",
    )


def _run_runner(
    tmp_path: Path,
    *args: str,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
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


def test_recovery_runner_row_blocks_without_seeded_operator_inputs(
    tmp_path: Path,
) -> None:
    result = _run_runner(
        tmp_path,
        "--scenario",
        "RG-08",
        extra_env={"AJENDA_VALIDATION_ENV": "isolated"},
    )

    assert result.returncode == 1
    artifact_root = _artifact_root(tmp_path)
    scenario_dir = artifact_root / "RG-08"

    assert (scenario_dir / "run_outcome.txt").read_text(encoding="utf-8").strip() == "blocked"
    assert (scenario_dir / "evidence_status.txt").read_text(encoding="utf-8").strip() == "missing"
    assert (scenario_dir / "evidence_basis.txt").read_text(encoding="utf-8").strip() == "unsupported"
    assert not (scenario_dir / "recovery_call").exists()

    scenario_results = (artifact_root / "scenario_results.tsv").read_text(encoding="utf-8")
    assert "RG-08\tblocked\tmissing\tunsupported\tisolated" in scenario_results

    summary = json.loads((artifact_root / "summary.json").read_text(encoding="utf-8"))
    assert summary["counts"]["blocked"] == 1
    assert summary["evidence_basis_counts"]["unsupported"] == 1
    assert summary["evidence_basis_counts"]["runner_backed"] == 0
    assert summary["counts"]["fail"] == 0


@pytest.mark.parametrize("scenario_id", ["FR-02", "FR-03", "FR-05"])
def test_recovery_fr_row_requires_seeded_operator_inputs(
    tmp_path: Path,
    scenario_id: str,
) -> None:
    result = _run_runner(
        tmp_path,
        "--scenario",
        scenario_id,
        extra_env={"AJENDA_VALIDATION_ENV": "isolated"},
    )

    assert result.returncode == 1
    artifact_root = _artifact_root(tmp_path)
    scenario_dir = artifact_root / scenario_id

    assert (scenario_dir / "run_outcome.txt").read_text(encoding="utf-8").strip() == "blocked"
    assert (scenario_dir / "evidence_status.txt").read_text(encoding="utf-8").strip() == "missing"
    assert (scenario_dir / "evidence_basis.txt").read_text(encoding="utf-8").strip() == "unsupported"
    assert not (scenario_dir / "recovery_call").exists()

    scenario_results = (artifact_root / "scenario_results.tsv").read_text(encoding="utf-8")
    assert f"{scenario_id}\tblocked\tmissing\tunsupported\tisolated" in scenario_results

    summary = json.loads((artifact_root / "summary.json").read_text(encoding="utf-8"))
    assert summary["counts"]["blocked"] == 1
    assert summary["evidence_basis_counts"]["unsupported"] == 1
    assert summary["counts"]["fail"] == 0


def test_recovery_input_block_does_not_mask_other_blocked_failure(
    tmp_path: Path,
) -> None:
    result = _run_runner(
        tmp_path,
        "--scenario",
        "FR-02",
        "--scenario",
        "RG-04",
        extra_env={"AJENDA_VALIDATION_ENV": "isolated"},
    )

    assert result.returncode == 1
    artifact_root = _artifact_root(tmp_path)

    fr_dir = artifact_root / "FR-02"
    assert (fr_dir / "run_outcome.txt").read_text(encoding="utf-8").strip() == "blocked"
    assert (fr_dir / "evidence_basis.txt").read_text(encoding="utf-8").strip() == "unsupported"

    rg_dir = artifact_root / "RG-04"
    assert (rg_dir / "run_outcome.txt").read_text(encoding="utf-8").strip() == "blocked"

    summary = json.loads((artifact_root / "summary.json").read_text(encoding="utf-8"))
    assert summary["counts"]["blocked"] == 2
    assert summary["evidence_basis_counts"]["unsupported"] == 2
    assert summary["counts"]["fail"] == 0


def test_seeded_recovery_input_executes_endpoint_but_never_synthesizes_missing_state(
    tmp_path: Path,
) -> None:
    result = _run_runner(
        tmp_path,
        "--scenario",
        "RG-08",
        extra_env={
            "AJENDA_VALIDATION_ENV": "isolated",
            "AJENDA_TENANT_ID": "00000000-0000-0000-0000-000000000222",
            "AJENDA_AUTH_HEADER": "Bearer platform-token",
            "AJENDA_DB_URL": "postgresql://unavailable/test",
            "AJENDA_REDIS_URL": "redis://unavailable:6379/0",
            "AJENDA_CLAIMED_RECOVERY_TASK_ID": "00000000-0000-0000-0000-000000000111",
        },
    )

    assert result.returncode == 1
    scenario_dir = _artifact_root(tmp_path) / "RG-08"
    assert (scenario_dir / "recovery_call" / "status.txt").read_text(encoding="utf-8").strip() == "200"
    assert (scenario_dir / "run_outcome.txt").read_text(encoding="utf-8").strip() == "evidence_incomplete"
    assert (scenario_dir / "evidence_basis.txt").read_text(encoding="utf-8").strip() == "runner_backed"


def test_rg05_invalid_envelope_runner_support_records_pass_and_manifest_entries(
    tmp_path: Path,
) -> None:
    result = _run_runner(tmp_path, "--scenario", "RG-05")

    assert result.returncode == 0
    artifact_root = _artifact_root(tmp_path)
    scenario_dir = artifact_root / "RG-05"

    assert (scenario_dir / "run_outcome.txt").read_text(encoding="utf-8").strip() == "pass"
    assert (scenario_dir / "evidence_status.txt").read_text(encoding="utf-8").strip() == "complete"

    scenario_results = (artifact_root / "scenario_results.tsv").read_text(encoding="utf-8")
    assert "RG-05\tpass\tcomplete\trunner_backed\tlocal" in scenario_results

    summary = json.loads((artifact_root / "summary.json").read_text(encoding="utf-8"))
    assert summary["counts"]["pass"] == 1
    assert summary["evidence_basis_counts"]["runner_backed"] == 1
    assert summary["counts"]["fail"] == 0


def test_tenant_mutation_scenario_is_blocked_when_required_environment_variables_are_missing(
    tmp_path: Path,
) -> None:
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
    assert summary["evidence_basis_counts"]["unsupported"] == 1
    assert summary["evidence_basis_counts"]["runner_backed"] == 0


def test_queue_admission_records_evidence_incomplete_when_required_proof_surfaces_are_missing(
    tmp_path: Path,
) -> None:
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
    assert "RG-04\tevidence_incomplete\tpartial\trunner_backed\tlocal" in scenario_results

    summary = json.loads((artifact_root / "summary.json").read_text(encoding="utf-8"))
    assert summary["counts"]["evidence_incomplete"] == 1
    assert summary["validation_env"] == "local"


def _matrix_rows() -> dict[str, list[str]]:
    rows: dict[str, list[str]] = {}
    for line in MATRIX.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|") or line.startswith("|---"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if cells and re.fullmatch(r"[A-Z]{2}-\d{2}", cells[0]):
            rows[cells[0]] = cells
    return rows


def _runner_array(name: str) -> set[str]:
    text = RUNNER.read_text(encoding="utf-8")
    match = re.search(rf"{name}=\((.*?)\)", text, re.DOTALL)
    assert match is not None, f"missing {name} declaration"
    return set(re.findall(r'"([A-Z]{2}-\d{2})"', match.group(1)))


def test_recovery_rows_are_runner_and_integration_backed_in_matrix() -> None:
    rows = _matrix_rows()

    for row_id in RECOVERY_ROWS:
        assert row_id in rows
        validation_backing = rows[row_id][6]
        assert validation_backing == "runner_and_integration"
        assert validation_backing in RUNNER_BACKING_VALUES


def test_recovery_rows_are_supported_and_declared_runner_backed() -> None:
    supported = _runner_array("SUPPORTED_SCENARIOS")
    runner_backed = _runner_array("RUNNER_BACKED_SCENARIOS")
    recovery_scenarios = _runner_array("RECOVERY_SCENARIOS")

    assert RECOVERY_ROWS <= supported
    assert RECOVERY_ROWS <= recovery_scenarios
    assert RECOVERY_ROWS <= runner_backed
