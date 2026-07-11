"""Phase B vertical mission templates — plan/graph + ExecutionCoordinator path only."""

from __future__ import annotations

import ast
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from backend.domain.enums import ExecutionTaskState
from backend.domain.mission import (
    MISSION_TASK_GRAPH_METADATA_KEY,
    Mission,
    normalize_mission_task_graph_contract_metadata,
)
from backend.services.abilities.catalog import ABILITY_MANIFESTS_BY_ACTION
from backend.services.abilities.vertical_role_catalog import RoleBindingStatus, get_vertical_role
from backend.services.execution_coordinator import CoordinationResult
from backend.services.vertical_ops.plan_templates import (
    PHASE_B_TEMPLATE_IDS,
    VERTICAL_MISSION_TEMPLATES,
    get_vertical_mission_template,
)
from backend.services.vertical_ops.template_service import (
    VERTICAL_TEMPLATE_METADATA_KEY,
    VerticalOpsTemplateService,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
VERTICAL_OPS_DIR = REPO_ROOT / "backend" / "services" / "vertical_ops"

FORBIDDEN_IMPORT_PREFIXES = (
    "backend.workers.worker_loop",
    "backend.workers.task_dispatcher",
    "celery",
    "backend.services.agent_swarm",
)


def test_phase_b_templates_cover_research_email_social() -> None:
    from backend.services.vertical_ops.plan_templates import list_vertical_mission_templates

    phase_b = list_vertical_mission_templates(phase="B")
    ids = {template.template_id for template in phase_b}
    assert ids == PHASE_B_TEMPLATE_IDS
    assert ids == {
        "vertical.research.v1",
        "vertical.email.v1",
        "vertical.social.v1",
    }
    # Full catalog includes Phase C as well.
    all_ids = {template.template_id for template in VERTICAL_MISSION_TEMPLATES}
    assert PHASE_B_TEMPLATE_IDS <= all_ids


def test_phase_b_steps_are_runtime_bound_and_manifested() -> None:
    from backend.services.vertical_ops.plan_templates import list_vertical_mission_templates

    for template in list_vertical_mission_templates(phase="B"):
        role = get_vertical_role(template.role_key)
        runtime_actions = {
            binding.action_name
            for binding in role.bindings
            if binding.binding_status is RoleBindingStatus.RUNTIME_BOUND
        }
        assert template.grants_execution_authority is False
        assert template.authority_class == "declarative"
        assert template.allows_runtime_queue is True
        for step in template.steps:
            assert step.action_name in runtime_actions
            assert step.action_name in ABILITY_MANIFESTS_BY_ACTION


def test_build_bundle_default_research_is_draft_safe() -> None:
    service = VerticalOpsTemplateService()
    bundle = service.build_bundle(template_id="vertical.research.v1")

    assert bundle.grants_execution_authority is False
    assert len(bundle.planned_tasks) == 1
    assert bundle.planned_tasks[0].action_name == "web.research"
    assert bundle.planned_tasks[0].metadata_json["task_type"] == "tool.invoke"
    assert bundle.planned_tasks[0].metadata_json["tool_invocation"]["action"] == "web.research"
    assert bundle.planned_tasks[0].metadata_json["vertical_role_key"] == "vertical.research"
    normalize_mission_task_graph_contract_metadata(bundle.task_graph)
    assert bundle.plan_contract["schema_version"] == 1
    assert bundle.plan_contract["planned_steps"][0]["sequence"] == 1


def test_email_template_send_requires_idempotency_key() -> None:
    service = VerticalOpsTemplateService()
    with pytest.raises(ValueError, match="idempotency_keys"):
        service.build_bundle(
            template_id="vertical.email.v1",
            selected_step_keys=("email-draft", "email-send"),
        )

    bundle = service.build_bundle(
        template_id="vertical.email.v1",
        selected_step_keys=("email-draft", "email-send"),
        idempotency_keys={"email-send": "email-idem-1"},
        step_inputs={"email-send": {"to": "a@example.com", "subject": "Hi", "body": "Hello"}},
    )
    assert [task.action_name for task in bundle.planned_tasks] == ["gtm.email_draft", "gtm.email_send"]
    send = bundle.planned_tasks[1]
    assert send.requires_human_review is True
    assert send.metadata_json["tool_invocation"]["idempotency_key"] == "email-idem-1"
    assert "side_effect_authorization" in send.metadata_json["execution_constraints"]
    assert send.compliance_category == "consumer_interaction"


def test_social_template_requires_idempotency_and_marks_human_review() -> None:
    service = VerticalOpsTemplateService()
    with pytest.raises(ValueError, match="idempotency_keys"):
        service.build_bundle(template_id="vertical.social.v1")

    bundle = service.build_bundle(
        template_id="vertical.social.v1",
        idempotency_keys={"social-publish": "social-idem-1"},
        step_inputs={"social-publish": {"content": "hello world", "platform": "x"}},
    )
    task = bundle.planned_tasks[0]
    assert task.action_name == "gtm.social_publish"
    assert task.requires_human_review is True
    assert task.metadata_json["side_effect_class"] == "external_publish"


def test_selected_step_fails_closed_without_dependency() -> None:
    service = VerticalOpsTemplateService()
    with pytest.raises(ValueError, match="required dependencies"):
        service.build_bundle(
            template_id="vertical.email.v1",
            selected_step_keys=("email-send",),
            idempotency_keys={"email-send": "x"},
        )


def test_apply_to_mission_creates_planned_tasks_without_enqueue() -> None:
    service = VerticalOpsTemplateService()
    session = MagicMock()
    flush_count = {"n": 0}

    def _flush() -> None:
        flush_count["n"] += 1

    session.flush.side_effect = _flush

    mission = Mission(
        tenant_id=str(uuid.uuid4()),
        objective="temp",
        status="planned",
        metadata_json={},
        compliance_category="operational",
        jurisdiction="US-ALL",
    )
    mission.id = uuid.uuid4()

    added: list[object] = []

    def _add(obj: object) -> None:
        added.append(obj)
        if hasattr(obj, "id") and getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()  # type: ignore[attr-defined]

    session.add.side_effect = _add

    result = service.apply_to_mission(
        session=session,
        mission=mission,
        template_id="vertical.research.v1",
        create_runtime_authority=False,
    )

    assert result.enqueued is False
    assert result.authority_class == "governed_mutation"
    assert len(result.created_task_ids) == 1
    assert mission.metadata_json[MISSION_TASK_GRAPH_METADATA_KEY]["nodes"][0]["node_key"] == "research-internal"
    assert mission.metadata_json[VERTICAL_TEMPLATE_METADATA_KEY]["template_id"] == "vertical.research.v1"
    assert mission.metadata_json[VERTICAL_TEMPLATE_METADATA_KEY]["grants_execution_authority"] is False
    assert mission.metadata_json[VERTICAL_TEMPLATE_METADATA_KEY]["created_task_ids"] == [
        str(result.created_task_ids[0])
    ]

    from backend.domain.execution_task import ExecutionTask

    tasks = [obj for obj in added if isinstance(obj, ExecutionTask)]
    assert len(tasks) == 1
    assert tasks[0].status == ExecutionTaskState.PLANNED.value
    assert tasks[0].metadata_json["task_type"] == "tool.invoke"
    assert tasks[0].metadata_json["tool_invocation"]["action"] == "web.research"


def test_queue_planned_tasks_uses_execution_coordinator_only() -> None:
    service = VerticalOpsTemplateService()
    session = MagicMock()
    queue = MagicMock()
    task_id = uuid.uuid4()
    tenant_id = str(uuid.uuid4())

    coordinator = MagicMock()
    coordinator.queue_task.return_value = CoordinationResult(
        ok=True,
        task_id=task_id,
        state=ExecutionTaskState.QUEUED.value,
        reason=None,
    )

    import backend.services.vertical_ops.template_service as module

    original = module.ExecutionCoordinator
    coordinator_cls = MagicMock(return_value=coordinator)
    module.ExecutionCoordinator = coordinator_cls  # type: ignore[misc,assignment]
    try:
        result = service.queue_planned_tasks(
            session=session,
            queue=queue,
            tenant_id=tenant_id,
            task_ids=(task_id,),
        )
    finally:
        module.ExecutionCoordinator = original  # type: ignore[misc]

    coordinator_cls.assert_called_once_with(session, queue)
    coordinator.queue_task.assert_called_once_with(tenant_id=tenant_id, task_id=task_id)
    assert result.queued_task_ids == (task_id,)
    assert result.blocked_task_ids == ()
    assert result.authority_class == "runtime_authoritative"


def test_apply_and_queue_blocks_policy_denial() -> None:
    service = VerticalOpsTemplateService()
    session = MagicMock()
    queue = MagicMock()

    def _add(obj: object) -> None:
        if getattr(obj, "id", None) is None and hasattr(obj, "id"):
            obj.id = uuid.uuid4()  # type: ignore[attr-defined]

    session.add.side_effect = _add

    mission = Mission(
        tenant_id=str(uuid.uuid4()),
        objective="research",
        status="planned",
        metadata_json={},
    )
    mission.id = uuid.uuid4()

    coordinator = MagicMock()

    def _queue_task(*, tenant_id: str, task_id: uuid.UUID) -> CoordinationResult:
        return CoordinationResult(
            ok=False,
            task_id=task_id,
            state=ExecutionTaskState.PENDING_REVIEW.value,
            reason="policy_review_required",
        )

    coordinator.queue_task.side_effect = _queue_task

    import backend.services.vertical_ops.template_service as module

    original = module.ExecutionCoordinator
    module.ExecutionCoordinator = MagicMock(return_value=coordinator)  # type: ignore[misc,assignment]
    try:
        applied, queued = service.apply_and_queue(
            session=session,
            queue=queue,
            mission=mission,
            template_id="vertical.research.v1",
            create_runtime_authority=False,
        )
    finally:
        module.ExecutionCoordinator = original  # type: ignore[misc]

    assert len(applied.created_task_ids) == 1
    assert queued.queued_task_ids == ()
    assert queued.blocked_task_ids == applied.created_task_ids
    assert queued.results[0].reason == "policy_review_required"


def test_unknown_template_fails_closed() -> None:
    with pytest.raises(ValueError, match="unknown vertical mission template"):
        get_vertical_mission_template("vertical.does-not-exist.v1")


def test_vertical_ops_package_does_not_import_parallel_runtime() -> None:
    for path in VERTICAL_OPS_DIR.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported.add(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        for forbidden in FORBIDDEN_IMPORT_PREFIXES:
            assert not any(item == forbidden or item.startswith(f"{forbidden}.") for item in imported)
        assert "agent_swarm" not in imported


def test_template_rejects_unknown_id() -> None:
    from backend.services.abilities.vertical_role_catalog import VERTICAL_OPS_PACK
    from backend.services.vertical_ops.plan_templates import VerticalMissionTemplate, VerticalTemplateStep

    with pytest.raises(ValidationError, match="known Phase B/C"):
        VerticalMissionTemplate(
            template_id="vertical.unknown.v1",
            role_key="vertical.research",
            pack_id=VERTICAL_OPS_PACK.pack_id,
            pack_version=VERTICAL_OPS_PACK.version,
            display_name="Unknown",
            description="should fail",
            objective_template="nope",
            phase="B",
            allows_runtime_queue=True,
            steps=(
                VerticalTemplateStep(
                    step_key="x",
                    action_name="web.research",
                    title="X",
                    description="nope",
                ),
            ),
        )
