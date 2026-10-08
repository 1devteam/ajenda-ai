from __future__ import annotations

import subprocess

from scripts.validation.frontier_preflight import CHECKS, run_frontier_preflight


def _runner(returncodes: dict[str, int]):
    def run(command, **_kwargs):
        check_id = next(check_id for check_id, check_command in CHECKS if list(check_command) == list(command))
        rc = returncodes.get(check_id, 0)
        return subprocess.CompletedProcess(
            command, rc, stdout=f"{check_id}:out", stderr="" if rc == 0 else f"{check_id}:err"
        )

    return run


def test_frontier_preflight_passes_only_when_all_checks_pass() -> None:
    report = run_frontier_preflight(runner=_runner({}))

    assert report["k"] == "graft_frontier_preflight"
    assert report["ok"] is True
    assert [row["id"] for row in report["c"]] == [check_id for check_id, _command in CHECKS]
    assert all(row["rc"] == 0 for row in report["c"])


def test_frontier_preflight_fails_closed_and_preserves_failure_evidence() -> None:
    report = run_frontier_preflight(runner=_runner({"mypy": 1}))

    assert report["ok"] is False
    mypy = next(row for row in report["c"] if row["id"] == "mypy")
    assert mypy["rc"] == 1
    assert "mypy:err" in mypy["tail"]
    assert len(mypy["out"]) == 64
    assert len(mypy["err"]) == 64
