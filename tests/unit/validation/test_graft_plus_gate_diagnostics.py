"""Regression tests for GRAFT+ aggregate gate diagnostics and checkpoints."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[3] / "scripts" / "validation" / "graft_plus_gate.py"
SPEC = importlib.util.spec_from_file_location("ajenda_graft_plus_gate_diagnostics", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


@pytest.fixture
def gate_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    report_path = tmp_path / "gate.json"
    monkeypatch.setattr(MODULE, "_REPORT_PATH", report_path)
    monkeypatch.setattr(MODULE, "_ACTIVE_REPORT", {"status": "incomplete", "steps": []})
    return report_path


def test_step_success_is_recorded_once(gate_report: Path) -> None:
    result = MODULE._run("success", [sys.executable, "-c", "print('worked')"])
    report = json.loads(gate_report.read_text(encoding="utf-8"))
    assert result["status"] == "passed"
    assert len(report["steps"]) == 1
    assert report["steps"][0]["returncode"] == 0
    assert "worked" in report["steps"][0]["stdout_tail"]


def test_failed_step_persists_command_exit_and_stderr(gate_report: Path) -> None:
    result = MODULE._run("failed", [sys.executable, "-c", "import sys; print('broken', file=sys.stderr); sys.exit(7)"])
    report = json.loads(gate_report.read_text(encoding="utf-8"))
    assert result["status"] == "failed"
    assert report["steps"][0]["returncode"] == 7
    assert report["steps"][0]["command"] == result["command"]
    assert "broken" in report["steps"][0]["stderr_tail"]


def test_checkpoint_exists_before_child_finishes(gate_report: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    observed = []
    original_popen = MODULE.subprocess.Popen

    def inspect_checkpoint(*args, **kwargs):
        observed.append(json.loads(gate_report.read_text(encoding="utf-8")))
        return original_popen(*args, **kwargs)

    monkeypatch.setattr(MODULE.subprocess, "Popen", inspect_checkpoint)
    MODULE._run("checkpoint", [sys.executable, "-c", "pass"])
    assert observed[0]["steps"][0]["status"] == "running"
    assert observed[0]["steps"][0]["command"][1:] == ["-c", "pass"]
