"""Regression guard for confirmation's internal proposal transaction boundary."""

from __future__ import annotations

import ast
import inspect
import textwrap

from backend.services.mission_composition.compile_phase import MissionCompositionCompilePhase
from backend.services.mission_composition.confirmation_phase import MissionCompositionConfirmationPhase


def test_confirmation_keeps_revalidation_and_reviewed_writes_in_caller_transaction() -> None:
    source = inspect.getsource(MissionCompositionConfirmationPhase.confirm)
    tree = ast.parse(textwrap.dedent(source))
    calls = [(node.lineno, ast.unparse(node.func), node) for node in ast.walk(tree) if isinstance(node, ast.Call)]
    compose_lines = [line for line, func, _ in calls if func == "self.compose"]
    quota_lines = [line for line, func, _ in calls if func == "quota.check_and_record_mission_creation"]
    proposal_write_lines = [line for line, func, _ in calls if func == "put_proposal" and line < min(quota_lines)]
    assert len(compose_lines) == 1
    assert len(quota_lines) == 1
    assert proposal_write_lines
    assert "persist=False" in source
    assert compose_lines[0] < min(proposal_write_lines) < quota_lines[0]


def test_confirmation_receipt_writes_do_not_independently_commit() -> None:
    source = inspect.getsource(MissionCompositionConfirmationPhase.confirm)
    tree = ast.parse(textwrap.dedent(source))
    calls = [(node.lineno, ast.unparse(node.func), node) for node in ast.walk(tree) if isinstance(node, ast.Call)]
    proposal_writes = sorted(line for line, func, _ in calls if func == "put_proposal")
    evidence_lines = sorted(
        line for line, func, _ in calls if func == "RuntimeEvidenceLedger(self._db, flush=False).append_fact"
    )

    assert len(proposal_writes) == 3
    assert len(evidence_lines) == 1
    assert "commit=False" in source
    assert max(proposal_writes) < evidence_lines[0]


def test_confirmation_creates_a_revalidated_record_instead_of_reusing_reviewed_proposal_id() -> None:
    source = inspect.getsource(MissionCompositionConfirmationPhase.confirm)
    assert '"revalidated_from_proposal_id": client_proposal_id' in source
    assert '"revision_reason": "confirmation_revalidation"' in source
    assert 'model_copy(update={"proposal_id": client_proposal_id})' not in source
    assert "require_durable=True" in source


def test_confirmation_revalidates_assessment_lineage_with_its_need_reference() -> None:
    source = inspect.getsource(MissionCompositionConfirmationPhase.confirm)
    assert "business_need_assessment_reference" in source
    assert 'compose_kwargs["business_need_assessment_reference"] = assessment_reference' in source


def test_compile_keeps_recomposition_and_graph_writes_in_caller_transaction() -> None:
    source = inspect.getsource(MissionCompositionCompilePhase.compile_for_mission)
    tree = ast.parse(textwrap.dedent(source))
    calls = [(node.lineno, ast.unparse(node.func), node) for node in ast.walk(tree) if isinstance(node, ast.Call)]
    compose_lines = [line for line, func, _ in calls if func == "self.compose"]
    plan_write_lines = [
        line
        for line, func, _ in calls
        if func == "self._mission_plan_repository(self._db).create_or_get_active_for_mission"
    ]
    assert len(compose_lines) == 1
    assert len(plan_write_lines) == 1
    proposal_write_lines = [line for line, func, _ in calls if func == "put_proposal"]
    assert proposal_write_lines
    assert "persist=False" in source
    assert compose_lines[0] < min(proposal_write_lines) < plan_write_lines[0]


def test_compile_retains_prior_composition_as_revalidation_lineage() -> None:
    source = inspect.getsource(MissionCompositionCompilePhase.compile_for_mission)
    assert '"revalidated_from_proposal_id": prior_proposal_id' in source
    assert '"revision_reason": "compile_revalidation"' in source
    assert "require_durable=True" in source


def test_compile_revalidates_assessment_lineage_with_its_need_reference() -> None:
    source = inspect.getsource(MissionCompositionCompilePhase.compile_for_mission)
    assert "business_need_assessment_reference" in source
    assert 'compose_kwargs["business_need_assessment_reference"] = assessment_reference' in source
