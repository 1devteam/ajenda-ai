"""Regression guard for confirmation's internal proposal transaction boundary."""

from __future__ import annotations

import ast
import inspect
import textwrap
from itertools import pairwise

from backend.services.mission_composition.compile_phase import MissionCompositionCompilePhase
from backend.services.mission_composition.confirmation_phase import MissionCompositionConfirmationPhase


def test_confirmation_reactivates_tenant_after_recompilation_before_quota_write() -> None:
    source = inspect.getsource(MissionCompositionConfirmationPhase.confirm)
    tree = ast.parse(textwrap.dedent(source))
    calls = [(node.lineno, ast.unparse(node.func), node) for node in ast.walk(tree) if isinstance(node, ast.Call)]
    compose_lines = [line for line, func, _ in calls if func == "self.compose"]
    activation_lines = [
        line
        for line, func, node in calls
        if func == "activate_tenant_session"
        and len(node.args) == 2
        and ast.unparse(node.args[0]) == "self._db"
        and ast.unparse(node.args[1]) == "str(tenant_id)"
    ]
    quota_lines = [line for line, func, _ in calls if func == "quota.check_and_record_mission_creation"]
    proposal_write_lines = [line for line, func, _ in calls if func == "put_proposal" and line < min(quota_lines)]
    activation_lines.sort()
    assert len(compose_lines) == 1
    assert len(activation_lines) >= 2
    assert len(quota_lines) == 1
    assert proposal_write_lines
    # Composition commits before the durable revalidation write, and that
    # write commits again.  RLS must be restored at both boundaries.
    assert compose_lines[0] < activation_lines[0] < min(proposal_write_lines)
    assert max(proposal_write_lines) < activation_lines[1] < quota_lines[0]


def test_confirmation_reactivates_tenant_at_each_receipt_persistence_boundary() -> None:
    source = inspect.getsource(MissionCompositionConfirmationPhase.confirm)
    tree = ast.parse(textwrap.dedent(source))
    calls = [(node.lineno, ast.unparse(node.func), node) for node in ast.walk(tree) if isinstance(node, ast.Call)]
    proposal_writes = sorted(line for line, func, _ in calls if func == "put_proposal")
    activation_lines = sorted(
        line
        for line, func, node in calls
        if func == "activate_tenant_session"
        and len(node.args) == 2
        and ast.unparse(node.args[0]) == "self._db"
        and ast.unparse(node.args[1]) == "str(tenant_id)"
    )
    evidence_lines = sorted(
        line for line, func, _ in calls if func == "RuntimeEvidenceLedger(self._db, flush=False).append_fact"
    )

    assert len(proposal_writes) == 3
    assert len(evidence_lines) == 1
    # Each receipt upsert can commit and clear SET LOCAL.  It therefore has a
    # fresh tenant activation before the write, with a final activation before
    # confirmation evidence is added to the caller-owned transaction.
    for previous_write, write_line in pairwise(proposal_writes):
        preceding_activation = max(
            activation_line for activation_line in activation_lines if activation_line < write_line
        )
        assert previous_write < preceding_activation < write_line
    assert max(proposal_writes) < max(activation_lines) < evidence_lines[0]


def test_confirmation_creates_a_revalidated_record_instead_of_reusing_reviewed_proposal_id() -> None:
    source = inspect.getsource(MissionCompositionConfirmationPhase.confirm)
    assert '"revalidated_from_proposal_id": client_proposal_id' in source
    assert '"revision_reason": "confirmation_revalidation"' in source
    assert 'model_copy(update={"proposal_id": client_proposal_id})' not in source
    assert "require_durable=True" in source


def test_compile_reactivates_tenant_after_recomposition_before_plan_write() -> None:
    source = inspect.getsource(MissionCompositionCompilePhase.compile_for_mission)
    tree = ast.parse(textwrap.dedent(source))
    calls = [(node.lineno, ast.unparse(node.func), node) for node in ast.walk(tree) if isinstance(node, ast.Call)]
    compose_lines = [line for line, func, _ in calls if func == "self.compose"]
    activation_lines = [
        line
        for line, func, node in calls
        if func == "activate_tenant_session"
        and len(node.args) == 2
        and ast.unparse(node.args[0]) == "self._db"
        and ast.unparse(node.args[1]) == "tenant_id"
    ]
    plan_write_lines = [
        line
        for line, func, _ in calls
        if func == "self._mission_plan_repository(self._db).create_or_get_active_for_mission"
    ]
    activation_lines.sort()
    assert len(compose_lines) == 1
    assert len(activation_lines) >= 2
    assert len(plan_write_lines) == 1
    proposal_write_lines = [line for line, func, _ in calls if func == "put_proposal"]
    assert proposal_write_lines
    assert compose_lines[0] < activation_lines[0] < min(proposal_write_lines)
    assert max(proposal_write_lines) < activation_lines[1] < plan_write_lines[0]


def test_compile_retains_prior_composition_as_revalidation_lineage() -> None:
    source = inspect.getsource(MissionCompositionCompilePhase.compile_for_mission)
    assert '"revalidated_from_proposal_id": prior_proposal_id' in source
    assert '"revision_reason": "compile_revalidation"' in source
    assert "require_durable=True" in source
