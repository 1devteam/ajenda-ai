from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[3] / "scripts" / "validation" / "graph_selective_ci.py"
SPEC = importlib.util.spec_from_file_location("graph_selective_ci", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

build_shadow_plan = MODULE.build_shadow_plan


def _manifest(**overrides):
    manifest = {
        "schema_version": "1.0",
        "required_tests": [],
        "required_gates": [],
        "review_gates": [],
        "manual_review": [],
    }
    manifest.update(overrides)
    return manifest


def test_plan_separates_unit_and_integration_tests():
    plan = build_shadow_plan(
        _manifest(
            required_tests=[
                "tests/unit/services/test_execution_coordinator.py",
                "tests/integration/runtime/test_worker_executes_echo_task_real.py",
            ],
            required_gates=["unit-tests", "integration-tests"],
        )
    )

    assert plan["unit_tests"] == ["tests/unit/services/test_execution_coordinator.py"]
    assert plan["integration_tests"] == ["tests/integration/runtime/test_worker_executes_echo_task_real.py"]
    assert plan["full_suite_fallback"] is False


def test_manual_review_requires_full_suite_fallback():
    plan = build_shadow_plan(
        _manifest(manual_review=["Review unmapped changed files; the canonical graph does not yet model them."])
    )

    assert plan["full_suite_fallback"] is True
    assert "manual review is required" in plan["fallback_reasons"]


def test_migration_and_live_runtime_obligations_trigger_fallback():
    plan = build_shadow_plan(
        _manifest(required_gates=["migration-round-trip"], review_gates=["live-runtime-proof"])
    )

    assert plan["full_suite_fallback"] is True
    assert "migration safety is required" in plan["fallback_reasons"]
    assert "review-only runtime proof is requested" in plan["fallback_reasons"]


def test_unknown_gate_fails_closed():
    try:
        build_shadow_plan(_manifest(required_gates=["made-up-gate"]))
    except RuntimeError as exc:
        assert "unknown required gate" in str(exc)
    else:
        raise AssertionError("unknown gates must fail closed")
