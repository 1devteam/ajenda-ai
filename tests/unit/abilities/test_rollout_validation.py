from __future__ import annotations

import pytest

from backend.services.abilities.manifest import AbilityManifest
from backend.services.abilities.rollout_validation import (
    validate_action_manifest_alignment,
    validate_manifest,
    validate_manifest_collection,
)
from backend.services.tools.action_registry import ActionDefinition
from backend.services.tools.schemas import (
    ActionResult,
    ActionRuntimeContext,
    RecordSearchInput,
    SideEffectClass,
    ToolInvocation,
)


def _handler(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    return ActionResult(
        action=invocation.action,
        provider="local_records",
        side_effect_class=SideEffectClass.INTERNAL_READ,
        output={"ok": True},
        evidence=[],
        summary=f"validated for {context.tenant_id}",
    )


def _action(**overrides: object) -> ActionDefinition:
    payload: dict[str, object] = {
        "name": "record.search",
        "handler": _handler,
        "side_effect_class": SideEffectClass.INTERNAL_READ,
        "provider": "local_records",
        "required_permissions": ("records:read",),
        "required_tools": ("record.search",),
        "input_model": RecordSearchInput,
    }
    payload.update(overrides)
    return ActionDefinition(**payload)


def _manifest(**overrides: object) -> AbilityManifest:
    payload: dict[str, object] = {
        "ability_id": "record-search",
        "display_name": "Record Search",
        "action_name": "record.search",
        "provider": "local_records",
        "capability_name": "records",
        "capability_version": "1",
        "adapter_name": "local-records",
        "adapter_version": "1",
        "input_schema_ref": "backend.services.tools.schemas.RecordSearchInput",
        "output_schema_ref": "backend.services.tools.schemas.ActionResult",
        "side_effect_class": SideEffectClass.INTERNAL_READ,
        "risk_level": "low",
        "required_permissions": ["records:read"],
        "required_tools": ["record.search"],
        "approval_required": False,
        "idempotency_required": False,
        "evidence_required": True,
        "readback_required": False,
        "enabled_by_default": False,
    }
    payload.update(overrides)
    return AbilityManifest.model_validate(payload)


def test_validate_manifest_round_trips_manifest_contract() -> None:
    manifest = _manifest()

    validated = validate_manifest(manifest)

    assert validated == manifest


def test_alignment_accepts_matching_registered_action() -> None:
    validate_action_manifest_alignment(action_definition=_action(), manifest=_manifest())


def test_alignment_rejects_action_name_mismatch() -> None:
    with pytest.raises(ValueError, match="action_name"):
        validate_action_manifest_alignment(
            action_definition=_action(name="record.read"),
            manifest=_manifest(),
        )


def test_alignment_rejects_provider_mismatch() -> None:
    with pytest.raises(ValueError, match="provider"):
        validate_action_manifest_alignment(
            action_definition=_action(provider="other"),
            manifest=_manifest(),
        )


def test_alignment_rejects_side_effect_mismatch_without_resolver() -> None:
    with pytest.raises(ValueError, match="side_effect_class"):
        validate_action_manifest_alignment(
            action_definition=_action(side_effect_class=SideEffectClass.NONE),
            manifest=_manifest(),
        )


def test_alignment_allows_dynamic_side_effect_resolver_with_conservative_max_class() -> None:
    validate_action_manifest_alignment(
        action_definition=_action(
            side_effect_class=SideEffectClass.INTERNAL_READ,
            side_effect_resolver=lambda invocation: SideEffectClass.INTERNAL_READ,
        ),
        manifest=_manifest(
            max_side_effect_class=SideEffectClass.INTERNAL_READ,
            resolver_side_effect_classes=(SideEffectClass.INTERNAL_READ,),
        ),
    )


def test_alignment_rejects_required_permission_mismatch() -> None:
    with pytest.raises(ValueError, match="required_permissions"):
        validate_action_manifest_alignment(
            action_definition=_action(required_permissions=("records:write",)),
            manifest=_manifest(),
        )


def test_manifest_collection_rejects_unknown_action() -> None:
    with pytest.raises(ValueError, match="unknown action"):
        validate_manifest_collection(manifests=[_manifest()], registered_actions={})


def test_manifest_collection_rejects_duplicate_manifest() -> None:
    action = _action()

    with pytest.raises(ValueError, match="duplicate ability manifest"):
        validate_manifest_collection(
            manifests=[_manifest(), _manifest()],
            registered_actions={"record.search": action},
        )


def test_manifest_collection_can_require_all_registered_actions() -> None:
    registered = {
        "record.search": _action(),
        "record.read": _action(name="record.read"),
    }

    with pytest.raises(ValueError, match="missing ability manifests"):
        validate_manifest_collection(
            manifests=[_manifest()],
            registered_actions=registered,
            require_all_registered=True,
        )


def test_resolver_backed_action_requires_max_side_effect_class() -> None:
    action = _action(
        name="http.request",
        provider="http",
        side_effect_class=SideEffectClass.EXTERNAL_READ,
        side_effect_resolver=lambda invocation: SideEffectClass.EXTERNAL_WRITE,
        required_permissions=(),
        required_tools=(),
    )
    manifest = _manifest(
        action_name="http.request",
        provider="http",
        side_effect_class=SideEffectClass.EXTERNAL_READ,
        required_permissions=[],
        required_tools=[],
    )

    with pytest.raises(ValueError, match="max_side_effect_class"):
        validate_action_manifest_alignment(action_definition=action, manifest=manifest)


def test_resolver_backed_action_accepts_conservative_max_side_effect_class() -> None:
    action = _action(
        name="http.request",
        provider="http",
        side_effect_class=SideEffectClass.EXTERNAL_READ,
        side_effect_resolver=lambda invocation: SideEffectClass.EXTERNAL_WRITE,
        required_permissions=(),
        required_tools=(),
    )
    manifest = _manifest(
        action_name="http.request",
        provider="http",
        side_effect_class=SideEffectClass.EXTERNAL_READ,
        max_side_effect_class=SideEffectClass.EXTERNAL_WRITE,
        resolver_side_effect_classes=(SideEffectClass.EXTERNAL_READ, SideEffectClass.EXTERNAL_WRITE),
        required_permissions=[],
        required_tools=[],
        approval_required=True,
        idempotency_required=True,
        readback_required=True,
    )

    validate_action_manifest_alignment(action_definition=action, manifest=manifest)


def test_resolver_backed_action_rejects_understated_default_side_effect() -> None:
    action = _action(
        name="record.write",
        side_effect_class=SideEffectClass.INTERNAL_WRITE,
        side_effect_resolver=lambda invocation: SideEffectClass.INTERNAL_WRITE,
    )
    manifest = _manifest(
        action_name="record.write",
        side_effect_class=SideEffectClass.INTERNAL_READ,
        max_side_effect_class=SideEffectClass.INTERNAL_WRITE,
        resolver_side_effect_classes=(SideEffectClass.INTERNAL_WRITE,),
        approval_required=True,
        readback_required=True,
    )

    with pytest.raises(ValueError, match="default side_effect_class"):
        validate_action_manifest_alignment(action_definition=action, manifest=manifest)


def test_alignment_rejects_input_schema_ref_mismatch() -> None:
    with pytest.raises(ValueError, match="input_schema_ref"):
        validate_action_manifest_alignment(
            action_definition=_action(),
            manifest=_manifest(input_schema_ref="backend.services.tools.schemas.HttpRequestInput"),
        )


def test_alignment_accepts_no_input_action_with_none_schema_ref() -> None:
    validate_action_manifest_alignment(
        action_definition=_action(input_model=None),
        manifest=_manifest(input_schema_ref="none"),
    )


def test_resolver_backed_action_rejects_internal_max_when_external_write_possible() -> None:
    action = _action(
        name="http.request",
        provider="http",
        side_effect_class=SideEffectClass.EXTERNAL_READ,
        side_effect_resolver=lambda invocation: SideEffectClass.EXTERNAL_WRITE,
        required_permissions=(),
        required_tools=(),
    )

    with pytest.raises(ValueError, match="maximum"):
        _manifest(
            action_name="http.request",
            provider="http",
            side_effect_class=SideEffectClass.EXTERNAL_READ,
            max_side_effect_class=SideEffectClass.INTERNAL_WRITE,
            resolver_side_effect_classes=(SideEffectClass.EXTERNAL_READ, SideEffectClass.EXTERNAL_WRITE),
            required_permissions=[],
            required_tools=[],
            approval_required=True,
            idempotency_required=True,
            readback_required=True,
        )

    manifest = _manifest(
        action_name="http.request",
        provider="http",
        side_effect_class=SideEffectClass.EXTERNAL_READ,
        max_side_effect_class=SideEffectClass.EXTERNAL_WRITE,
        resolver_side_effect_classes=(SideEffectClass.EXTERNAL_READ, SideEffectClass.EXTERNAL_WRITE),
        required_permissions=[],
        required_tools=[],
        approval_required=True,
        idempotency_required=True,
        readback_required=True,
    )

    validate_action_manifest_alignment(action_definition=action, manifest=manifest)


def test_resolver_backed_action_requires_declared_resolver_side_effect_classes() -> None:
    action = _action(
        name="http.request",
        provider="http",
        side_effect_class=SideEffectClass.EXTERNAL_READ,
        side_effect_resolver=lambda invocation: SideEffectClass.EXTERNAL_WRITE,
        required_permissions=(),
        required_tools=(),
    )
    manifest = _manifest(
        action_name="http.request",
        provider="http",
        side_effect_class=SideEffectClass.EXTERNAL_READ,
        max_side_effect_class=SideEffectClass.EXTERNAL_WRITE,
        resolver_side_effect_classes=(),
        required_permissions=[],
        required_tools=[],
        approval_required=True,
        idempotency_required=True,
        readback_required=True,
    )

    with pytest.raises(ValueError, match="resolver_side_effect_classes"):
        validate_action_manifest_alignment(action_definition=action, manifest=manifest)


def test_alignment_rejects_output_schema_ref_mismatch() -> None:
    with pytest.raises(ValueError, match="output_schema_ref"):
        validate_action_manifest_alignment(
            action_definition=_action(),
            manifest=_manifest(output_schema_ref="backend.services.tools.schemas.EvidenceItem"),
        )
