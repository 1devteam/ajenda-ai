"""Phase C vertical templates — plan-only, fail-closed queue (ADR-0007)."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

from backend.domain.mission import Mission, normalize_mission_task_graph_contract_metadata
from backend.services.abilities.vertical_role_catalog import RoleBindingStatus, get_vertical_role
from backend.services.vertical_ops.plan_templates import (
    PHASE_C_TEMPLATE_IDS,
    get_vertical_mission_template,
    list_vertical_mission_templates,
)
from backend.services.vertical_ops.template_service import (
    VERTICAL_TEMPLATE_METADATA_KEY,
    VerticalOpsTemplateService,
)


def test_phase_c_templates_are_plan_only_and_catalog_bound() -> None:
    phase_c = list_vertical_mission_templates(phase="C")
    assert {t.template_id for t in phase_c} == PHASE_C_TEMPLATE_IDS
    for template in phase_c:
        assert template.phase == "C"
        assert template.allows_runtime_queue is False
        assert template.grants_execution_authority is False
        role = get_vertical_role(template.role_key)
        for step in template.steps:
            binding = template.resolve_binding(step.action_name)
            assert binding.binding_status is RoleBindingStatus.CATALOG_ONLY
            assert binding.deferred_reason
        assert role.requires_human_review is True
        assert role.enabled_by_default is False


def test_phase_c_bundle_has_plan_graph_without_runtime_tasks() -> None:
    service = VerticalOpsTemplateService()
    for template_id in sorted(PHASE_C_TEMPLATE_IDS):
        bundle = service.build_bundle(template_id=template_id)
        assert bundle.allows_runtime_queue is False
        assert bundle.phase == "C"
        assert bundle.planned_tasks == ()
        normalize_mission_task_graph_contract_metadata(bundle.task_graph)
        assert bundle.plan_contract["planned_steps"]
        assert any("allows_runtime_queue=False" in item for item in bundle.plan_contract["constraints"])


def test_phase_c_apply_attaches_plan_without_execution_tasks() -> None:
    service = VerticalOpsTemplateService()
    session = MagicMock()
    mission = Mission(
        tenant_id=str(uuid.uuid4()),
        objective="ads plan",
        status="planned",
        metadata_json={},
        compliance_category="operational",
        jurisdiction="US-ALL",
    )
    mission.id = uuid.uuid4()

    applied = service.apply_to_mission(
        session=session,
        mission=mission,
        template_id="vertical.ads.v1",
        create_runtime_authority=False,
    )
    assert applied.created_task_ids == ()
    assert applied.enqueued is False
    meta = mission.metadata_json[VERTICAL_TEMPLATE_METADATA_KEY]
    assert meta["phase"] == "C"
    assert meta["allows_runtime_queue"] is False
    assert meta["grants_execution_authority"] is False
    assert meta["created_task_ids"] == []


def test_phase_c_queue_fails_closed() -> None:
    service = VerticalOpsTemplateService()
    service.ensure_runtime_queue_allowed(template_id="vertical.finance.v1")

    session = MagicMock()
    queue = MagicMock()
    mission = Mission(
        tenant_id=str(uuid.uuid4()),
        objective="finance",
        status="planned",
        metadata_json={},
    )
    mission.id = uuid.uuid4()
    with pytest.raises(ValueError, match="plan-only"):
        service.apply_and_queue(
            session=session,
            queue=queue,
            mission=mission,
            template_id="vertical.code.v1",
        )


def test_phase_b_finance_sync_is_runtime_queueable() -> None:
    service = VerticalOpsTemplateService()
    bundle = service.build_bundle(template_id="vertical.finance.v1")
    assert bundle.phase == "B"
    assert bundle.allows_runtime_queue is True
    assert [node["node_key"] for node in bundle.task_graph["nodes"]] == ["finance-sync"]


def test_get_phase_c_template() -> None:
    template = get_vertical_mission_template("vertical.ads.v1")
    assert template.role_key == "vertical.ads"
    assert template.allows_runtime_queue is False
