"""Phase A contract tests for ADR-0007 vertical role catalog.

Declarative only: no queue, lease, dispatcher, or parallel runtime coordinator.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.auth.permissions import Permission
from backend.domain.compliance import ComplianceCategory
from backend.services.abilities.catalog import ABILITY_MANIFESTS_BY_ACTION
from backend.services.abilities.manifest import AbilityRiskLevel
from backend.services.abilities.vertical_role_catalog import (
    VERTICAL_OPS_PACK,
    VERTICAL_ROLE_SPECS_BY_KEY,
    RoleBindingStatus,
    VerticalRoleBinding,
    VerticalRolePack,
    VerticalRoleSpec,
    get_vertical_role,
    list_runtime_bound_action_names,
)
from backend.services.tools.schemas import SideEffectClass

REPO_ROOT = Path(__file__).resolve().parents[3]
CATALOG_PATH = REPO_ROOT / "backend" / "services" / "abilities" / "vertical_role_catalog.py"

EXPECTED_ROLE_KEYS = {
    "vertical.orchestrator",
    "vertical.planning",
    "vertical.research",
    "vertical.social",
    "vertical.email",
    "vertical.support",
    "vertical.ads",
    "vertical.code",
    "vertical.finance",
}

FORBIDDEN_IMPORT_MODULES = {
    "backend.workers.worker_loop",
    "backend.workers.task_dispatcher",
    "backend.services.execution_coordinator",
    "backend.services.mission_bridge",
    "celery",
}


def _minimal_binding(**overrides: object) -> VerticalRoleBinding:
    payload: dict[str, object] = {
        "action_name": "test.action",
        "binding_status": RoleBindingStatus.CATALOG_ONLY,
        "capability_name": "test_capability",
        "capability_version": "1",
        "adapter_name": "test-adapter",
        "adapter_version": "1",
        "side_effect_class": SideEffectClass.NONE,
        "risk_level": AbilityRiskLevel.LOW,
        "required_permissions": (),
        "approval_required": False,
        "idempotency_required": False,
        "evidence_required": True,
        "evidence_expectations": ("action_result_evidence",),
        "readback_required": False,
        "enabled_by_default": False,
        "credential_required": False,
        "deferred_reason": "test deferred",
    }
    payload.update(overrides)
    return VerticalRoleBinding.model_validate(payload)


def _minimal_role(**overrides: object) -> VerticalRoleSpec:
    payload: dict[str, object] = {
        "role_key": "vertical.test",
        "display_name": "Test Role",
        "description": "Test vertical role for contract validation.",
        "risk_level": AbilityRiskLevel.LOW,
        "compliance_category": ComplianceCategory.OPERATIONAL.value,
        "default_jurisdiction": "US-ALL",
        "requires_human_review": False,
        "required_permissions": (),
        "evidence_expectations": ("summary",),
        "bindings": (_minimal_binding(),),
        "enabled_by_default": False,
        "notes": "Unit test role only.",
    }
    payload.update(overrides)
    return VerticalRoleSpec.model_validate(payload)


def test_vertical_ops_pack_is_declarative_and_non_executing() -> None:
    assert VERTICAL_OPS_PACK.pack_id == "vertical_ops.v1"
    assert VERTICAL_OPS_PACK.authority_class == "declarative"
    assert VERTICAL_OPS_PACK.grants_execution_authority is False
    assert VERTICAL_OPS_PACK.schema_version == 1


def test_vertical_ops_pack_has_nine_unique_roles() -> None:
    keys = [role.role_key for role in VERTICAL_OPS_PACK.roles]
    assert len(keys) == 9
    assert set(keys) == EXPECTED_ROLE_KEYS
    assert set(VERTICAL_ROLE_SPECS_BY_KEY) == EXPECTED_ROLE_KEYS


def test_get_vertical_role_lookup() -> None:
    role = get_vertical_role("vertical.email")
    assert role.display_name == "Email Outreach"
    assert role.authority_class == "declarative"
    with pytest.raises(ValueError, match="unknown vertical role_key"):
        get_vertical_role("vertical.does_not_exist")


def test_all_roles_use_canonical_side_effects_and_permissions() -> None:
    allowed_effects = {item.value for item in SideEffectClass}
    allowed_permissions = {item.value for item in Permission}

    for role in VERTICAL_OPS_PACK.roles:
        assert role.authority_class == "declarative"
        assert role.enabled_by_default is False
        for perm in role.required_permissions:
            assert perm in allowed_permissions
        for binding in role.bindings:
            assert binding.side_effect_class.value in allowed_effects
            for perm in binding.required_permissions:
                assert perm in allowed_permissions
            # Rejected invented classes must never appear.
            assert binding.side_effect_class.value not in {
                "financial_mutation",
                "external_write + financial",
            }


def test_high_and_critical_roles_require_human_review_and_are_disabled() -> None:
    for role in VERTICAL_OPS_PACK.roles:
        if role.risk_level in {AbilityRiskLevel.HIGH, AbilityRiskLevel.CRITICAL}:
            assert role.requires_human_review is True
            assert role.enabled_by_default is False
        if role.compliance_category in {
            ComplianceCategory.FINANCIAL.value,
            ComplianceCategory.CONSUMER_INTERACTION.value,
        }:
            assert role.requires_human_review is True


def test_runtime_bound_actions_exist_in_ability_catalog() -> None:
    runtime_actions = list_runtime_bound_action_names()
    assert runtime_actions
    for action_name in runtime_actions:
        assert action_name in ABILITY_MANIFESTS_BY_ACTION, (
            f"runtime_bound action missing ability manifest: {action_name}"
        )


def test_catalog_only_bindings_have_deferred_reasons_and_are_disabled() -> None:
    catalog_only = [
        binding
        for role in VERTICAL_OPS_PACK.roles
        for binding in role.bindings
        if binding.binding_status is RoleBindingStatus.CATALOG_ONLY
    ]
    assert catalog_only
    for binding in catalog_only:
        assert binding.deferred_reason
        assert binding.enabled_by_default is False


def test_phase_c_high_risk_roles_remain_catalog_only() -> None:
    for role_key in ("vertical.ads", "vertical.code", "vertical.finance"):
        role = get_vertical_role(role_key)
        assert all(binding.binding_status is RoleBindingStatus.CATALOG_ONLY for binding in role.bindings)


def test_phase_b_candidate_roles_have_runtime_bindings() -> None:
    for role_key in ("vertical.research", "vertical.email", "vertical.social"):
        role = get_vertical_role(role_key)
        assert any(binding.binding_status is RoleBindingStatus.RUNTIME_BOUND for binding in role.bindings)


def test_catalog_module_does_not_import_runtime_authority_surfaces() -> None:
    source = CATALOG_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
            for alias in node.names:
                imported.add(f"{node.module}.{alias.name}")
    for forbidden in FORBIDDEN_IMPORT_MODULES:
        assert forbidden not in imported
        assert not any(item == forbidden or item.startswith(f"{forbidden}.") for item in imported)
    # Parallel swarm package must not appear as an import path (doc path text is fine).
    assert not any("agent_swarm" in item for item in imported)
    # No function defs that enqueue or dispatch work.
    function_names = {node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert "queue_task" not in function_names
    assert "claim_next_task" not in function_names
    assert "dispatch" not in function_names


def test_rejects_unknown_permission() -> None:
    with pytest.raises(ValidationError, match="unknown permission"):
        _minimal_binding(required_permissions=("not:a:permission",))


def test_rejects_invalid_side_effect_class() -> None:
    with pytest.raises(ValidationError):
        _minimal_binding(side_effect_class="financial_mutation")


def test_rejects_catalog_only_without_deferred_reason() -> None:
    with pytest.raises(ValidationError, match="deferred_reason"):
        _minimal_binding(deferred_reason=None)


def test_rejects_high_risk_enabled_by_default() -> None:
    with pytest.raises(ValidationError, match="cannot be enabled by default"):
        _minimal_role(
            risk_level=AbilityRiskLevel.HIGH,
            requires_human_review=True,
            enabled_by_default=True,
            bindings=(
                _minimal_binding(
                    risk_level=AbilityRiskLevel.HIGH,
                    requires_human_review=True,
                ),
            ),
        )


def test_rejects_external_write_without_idempotency() -> None:
    with pytest.raises(ValidationError, match="idempotency_required"):
        _minimal_binding(
            side_effect_class=SideEffectClass.EXTERNAL_WRITE,
            risk_level=AbilityRiskLevel.HIGH,
            approval_required=True,
            idempotency_required=False,
            requires_human_review=True,
            credential_required=True,
            readback_deferred_reason="deferred",
        )


def test_rejects_runtime_bound_external_publish_without_credentials() -> None:
    with pytest.raises(ValidationError, match="credential_required"):
        _minimal_binding(
            binding_status=RoleBindingStatus.RUNTIME_BOUND,
            deferred_reason=None,
            side_effect_class=SideEffectClass.EXTERNAL_PUBLISH,
            risk_level=AbilityRiskLevel.HIGH,
            approval_required=True,
            idempotency_required=True,
            idempotency_contract_ref="docs/test.md",
            requires_human_review=True,
            credential_required=False,
            readback_deferred_reason="deferred",
        )


def test_rejects_pack_with_duplicate_role_keys() -> None:
    role = _minimal_role()
    with pytest.raises(ValidationError, match="unique role_key"):
        VerticalRolePack(
            pack_id="test.pack",
            version="1.0.0",
            display_name="Test",
            description="dup roles",
            roles=(role, role),
        )


def test_pack_cannot_grant_execution_authority_field() -> None:
    # Field is Literal[False]; construction with True is a type/validation failure path.
    with pytest.raises(ValidationError):
        VerticalRolePack.model_validate(
            {
                "pack_id": "evil.pack",
                "version": "1.0.0",
                "display_name": "Evil",
                "description": "must fail",
                "roles": [_minimal_role().model_dump()],
                "grants_execution_authority": True,
            }
        )
