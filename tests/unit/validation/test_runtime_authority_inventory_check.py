from __future__ import annotations

from pathlib import Path

from scripts.validation import runtime_authority_inventory_check as authority_check


def test_current_runtime_authority_inventory_is_fully_reviewed() -> None:
    observed = authority_check.inventory_runtime_authority()

    assert authority_check.validate_inventory(observed) == []
    classifications = {authority_check.REVIEWED_CALL_SITES[item.key].classification for item in observed}
    assert classifications == {
        "canonical_boundary",
        "canonical_daemon_spine",
        "competing_http_spine",
        "exception_bypass",
    }


def test_inventory_exposes_both_current_claim_and_dispatch_spines() -> None:
    observed = authority_check.inventory_runtime_authority()
    reviewed = {item.key: authority_check.REVIEWED_CALL_SITES[item.key] for item in observed}

    daemon = {key for key, value in reviewed.items() if value.classification == "canonical_daemon_spine"}
    http_bridge = {key for key, value in reviewed.items() if value.classification == "competing_http_spine"}

    assert any(key.path.endswith("worker_loop.py") and key.sink == "dispatcher_execute" for key in daemon)
    assert any(key.path.endswith("worker_runtime_service.py") and key.sink == "queue_claim" for key in daemon)
    assert any(
        key.path.endswith("worker_run_admission_service.py") and key.sink == "queue_claim" for key in http_bridge
    )
    assert any(
        key.path.endswith("worker_run_admission_service.py") and key.sink == "dispatcher_execute" for key in http_bridge
    )


def test_inventory_fails_closed_on_new_direct_action_invocation(tmp_path: Path) -> None:
    source = tmp_path / "rogue_runtime.py"
    source.write_text(
        "def execute_without_runtime(registry, invocation, context):\n"
        "    return registry.invoke(invocation, context)\n",
        encoding="utf-8",
    )

    observed = authority_check.inventory_runtime_authority(tmp_path)
    errors = authority_check.validate_inventory(observed, reviewed={})

    assert len(errors) == 1
    assert "unreviewed authority sink" in errors[0]
    assert "action_invoke" in errors[0]


def test_inventory_detects_aliased_dispatcher_and_direct_handler(tmp_path: Path) -> None:
    source = tmp_path / "rogue_aliases.py"
    source.write_text(
        "from backend.workers.task_dispatcher import TaskDispatcher as TD\n"
        "from backend.workers.handlers.tool_invoke import tool_invoke_handler as run_tool\n"
        "def bypass(task, context, session_factory, queue):\n"
        "    runner = TD(session_factory=session_factory, queue=queue, worker_id='w', tenant_id='t')\n"
        "    runner.execute(task_id=task.id, lease_id='lease')\n"
        "    return run_tool(task, context)\n",
        encoding="utf-8",
    )

    observed = authority_check.inventory_runtime_authority(tmp_path)

    assert {item.key.sink for item in observed} == {"dispatcher_execute", "tool_handler_direct"}
    assert len(authority_check.validate_inventory(observed, reviewed={})) == 2


def test_inventory_fails_when_reviewed_authority_disappears() -> None:
    key = authority_check.CallSiteKey("backend/example.py", "Example.run", "queue_claim")
    reviewed = {
        key: authority_check.ReviewedCallSite(
            classification="competing_http_spine",
            disposition="remove",
        )
    }

    errors = authority_check.validate_inventory([], reviewed=reviewed)

    assert errors == [f"reviewed authority sink disappeared or moved without reconciliation: {key}"]


def test_main_emits_machine_readable_inventory(capsys) -> None:  # type: ignore[no-untyped-def]
    original_argv = authority_check.sys.argv
    authority_check.sys.argv = ["runtime_authority_inventory_check.py", "--json"]
    try:
        assert authority_check.main() == 0
    finally:
        authority_check.sys.argv = original_argv

    output = capsys.readouterr().out
    assert '"classification": "competing_http_spine"' in output
    assert '"classification": "canonical_daemon_spine"' in output
    assert "PASS: runtime authority inventory matches" in output
