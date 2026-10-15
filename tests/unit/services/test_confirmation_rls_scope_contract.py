"""Regression guard for confirmation's internal proposal transaction boundary."""

from __future__ import annotations

import ast
import inspect

from backend.services.mission_composition.confirmation_phase import MissionCompositionConfirmationPhase


def test_confirmation_reactivates_tenant_after_recompilation_before_quota_write() -> None:
    source = inspect.getsource(MissionCompositionConfirmationPhase.confirm)
    tree = ast.parse(source)
    calls = [
        (node.lineno, ast.unparse(node.func), node)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    ]
    compose_lines = [line for line, func, _ in calls if func == "self.compose"]
    activation_lines = [
        line for line, func, node in calls
        if func == "activate_tenant_session"
        and len(node.args) == 2
        and ast.unparse(node.args[0]) == "self._db"
        and ast.unparse(node.args[1]) == "str(tenant_id)"
    ]
    quota_lines = [
        line for line, func, _ in calls
        if func == "quota.check_and_record_mission_creation"
    ]
    assert len(compose_lines) == 1
    assert len(activation_lines) == 1
    assert len(quota_lines) == 1
    assert compose_lines[0] < activation_lines[0] < quota_lines[0]
