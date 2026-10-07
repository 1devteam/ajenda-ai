"""Provision tenant-scoped capability/adapter authority for mission bridge tool.invoke nodes."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.domain.capability import Capability
from backend.domain.capability_adapter import CapabilityAdapter
from backend.domain.mission import MISSION_TASK_GRAPH_METADATA_KEY
from backend.repositories.capability_adapter_repository import CapabilityAdapterRepository
from backend.repositories.capability_repository import CapabilityRepository
from backend.repositories.mission_repository import MissionRepository
from backend.services.tools.action_registry import ActionDefinition, get_default_action_registry
from backend.services.tools.schemas import CredentialReference, SideEffectClass, ToolInvocation

_BRIDGE_CAPABILITY_VERSION = "1.0.0"

_SIDE_EFFECT_RANK = {
    SideEffectClass.NONE: 0,
    SideEffectClass.INTERNAL_READ: 1,
    SideEffectClass.EXTERNAL_READ: 2,
    SideEffectClass.INTERNAL_WRITE: 3,
    SideEffectClass.EXTERNAL_WRITE: 4,
    SideEffectClass.EXTERNAL_SEND: 5,
    SideEffectClass.EXTERNAL_PUBLISH: 6,
}


def _bridge_capability_name(action_name: str) -> str:
    return f"bridge_{action_name.replace('.', '_')}"


def _adapter_side_effect_classification(side_effect_class: SideEffectClass) -> str:
    if side_effect_class == SideEffectClass.NONE:
        return "none"
    if side_effect_class == SideEffectClass.INTERNAL_READ:
        return "read_only"
    if side_effect_class == SideEffectClass.INTERNAL_WRITE:
        return "non_idempotent_write"
    if side_effect_class in {
        SideEffectClass.EXTERNAL_READ,
        SideEffectClass.EXTERNAL_WRITE,
        SideEffectClass.EXTERNAL_SEND,
        SideEffectClass.EXTERNAL_PUBLISH,
    }:
        return side_effect_class.value
    return "external_side_effect"


def _requires_runtime_authority(side_effect_class: SideEffectClass) -> bool:
    return side_effect_class.has_side_effect or side_effect_class.value.startswith("external_")


def _action_from_graph_node(node: dict[str, Any]) -> str | None:
    input_contract = node.get("input_contract")
    if not isinstance(input_contract, dict):
        return None
    tool_invocation = input_contract.get("tool_invocation")
    if isinstance(tool_invocation, dict) and isinstance(tool_invocation.get("action"), str):
        action = tool_invocation["action"].strip()
        return action or None
    if isinstance(input_contract.get("action"), str):
        action = input_contract["action"].strip()
        return action or None
    return None


def _tool_input_from_graph_node(node: dict[str, Any]) -> dict[str, Any]:
    input_contract = node.get("input_contract")
    if not isinstance(input_contract, dict):
        return {}
    tool_invocation = input_contract.get("tool_invocation")
    if isinstance(tool_invocation, dict) and isinstance(tool_invocation.get("input"), dict):
        return dict(tool_invocation["input"])
    return {}


def _credential_reference_from_graph_node(node: dict[str, Any]) -> dict[str, Any] | None:
    input_contract = node.get("input_contract")
    if not isinstance(input_contract, dict):
        return None
    credential_reference = input_contract.get("credential_reference")
    if isinstance(credential_reference, dict):
        return dict(credential_reference)
    credential_reference = node.get("credential_reference")
    return dict(credential_reference) if isinstance(credential_reference, dict) else None


def _effective_side_effect_for_bridge(
    *,
    definition: ActionDefinition,
    action_name: str,
    tool_input: dict[str, Any],
    credential_reference: dict[str, Any] | None = None,
) -> SideEffectClass:
    """Resolve the strongest side-effect this bridge adapter must authorize.

    Resolver-backed actions (e.g. web.research with include_public_search) elevate
    at invoke time; bridge provisioning must use the composed input, not only the
    action default, or capability validation rejects the task.
    """
    try:
        reference = CredentialReference.model_validate(credential_reference) if credential_reference else None
        invocation = ToolInvocation(
            action=action_name,
            input=tool_input or {},
            credential_reference=reference,
        )
        resolved = definition.side_effect_for(invocation)
    except Exception:
        resolved = definition.side_effect_class
    # Composition stores credential authority beside the tool input in the
    # graph contract. Reconstruct the resolver's external-read decision from
    # the explicit CRM context before persisting the bridge adapter class.
    if action_name in {"sales.research", "crm.research"}:
        context = tool_input.get("context") if isinstance(tool_input, dict) else None
        if isinstance(context, dict) and context.get("require_external_crm") is True:
            resolved = SideEffectClass.EXTERNAL_READ
    # Prefer the stronger of default vs resolved so adapters remain valid for both modes.
    if _SIDE_EFFECT_RANK.get(resolved, 0) >= _SIDE_EFFECT_RANK.get(definition.side_effect_class, 0):
        return resolved
    return definition.side_effect_class


def _classification_rank(classification: str) -> int:
    mapping = {
        "none": 0,
        "read_only": 1,
        "external_read": 2,
        "non_idempotent_write": 3,
        "idempotent_write": 3,
        "internal_side_effect": 3,
        "external_write": 4,
        "external_send": 5,
        "external_publish": 6,
        "external_side_effect": 2,
    }
    return mapping.get(classification, 0)


def _ensure_bridge_authority(
    *,
    db: Session,
    tenant_id: str,
    action_name: str,
    approved_by: str,
    tool_input: dict[str, Any] | None = None,
    credential_reference: dict[str, Any] | None = None,
) -> tuple[Capability, CapabilityAdapter]:
    registry = get_default_action_registry()
    try:
        definition = registry.get(action_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"unknown action for bridge authority: {action_name}") from exc

    side_effect_class = _effective_side_effect_for_bridge(
        definition=definition,
        action_name=action_name,
        tool_input=tool_input or {},
        credential_reference=credential_reference,
    )
    required_classification = _adapter_side_effect_classification(side_effect_class)
    capability_name = _bridge_capability_name(action_name)
    capability_repo = CapabilityRepository(db)
    adapter_repo = CapabilityAdapterRepository(db)

    existing_capability = capability_repo.get_visible_by_name_version(
        name=capability_name,
        version=_BRIDGE_CAPABILITY_VERSION,
        tenant_id=tenant_id,
    )
    if existing_capability is not None:
        existing_adapter = adapter_repo.get_conflict_for_scope(
            name=f"{capability_name}_adapter",
            version=_BRIDGE_CAPABILITY_VERSION,
            tenant_id=tenant_id,
        )
        if existing_adapter is not None:
            # Upgrade stale bridge adapters that were provisioned before resolver elevation.
            current = str(existing_adapter.side_effect_classification or "")
            if _classification_rank(required_classification) > _classification_rank(current):
                existing_adapter.side_effect_classification = required_classification
                if _requires_runtime_authority(side_effect_class):
                    existing_adapter.approval_requirements = {
                        "required": side_effect_class.value
                        in {
                            SideEffectClass.EXTERNAL_WRITE.value,
                            SideEffectClass.EXTERNAL_SEND.value,
                            SideEffectClass.EXTERNAL_PUBLISH.value,
                        },
                        "generated_by": "mission-bridge",
                        "approved_by": approved_by,
                    }
                db.add(existing_adapter)
                db.flush()
            return existing_capability, existing_adapter

    approval_required = side_effect_class.value in {
        SideEffectClass.EXTERNAL_WRITE.value,
        SideEffectClass.EXTERNAL_SEND.value,
        SideEffectClass.EXTERNAL_PUBLISH.value,
    }
    approval_requirements = (
        {
            "required": approval_required,
            "generated_by": "mission-bridge",
            "approved_by": approved_by,
        }
        if _requires_runtime_authority(side_effect_class)
        else {}
    )

    capability = Capability(
        tenant_id=tenant_id,
        name=capability_name,
        version=_BRIDGE_CAPABILITY_VERSION,
        description=f"Mission bridge authority for {action_name}.",
        supported_task_types=["tool.invoke", action_name],
        input_schema_hints={},
        output_schema_hints={},
        required_permissions=[],
        required_tools=[action_name],
        risk_level="medium" if _requires_runtime_authority(side_effect_class) else "low",
        approval_requirements=approval_requirements,
        evidence_expectations=[f"{action_name} evidence"],
        execution_constraints={},
        enabled=True,
        schema_version=1,
    )
    db.add(capability)
    db.flush()

    adapter = CapabilityAdapter(
        tenant_id=tenant_id,
        name=f"{capability_name}_adapter",
        version=_BRIDGE_CAPABILITY_VERSION,
        capability_id=capability.id,
        capability_name=capability.name,
        capability_version=capability.version,
        supported_task_types=["tool.invoke", action_name],
        input_contract={},
        output_contract={},
        required_permissions=[],
        required_tools=[action_name],
        execution_mode="queued",
        risk_level=capability.risk_level,
        approval_requirements=approval_requirements,
        evidence_expectations=[f"{action_name} evidence"],
        timeout_retry_hints={},
        idempotency_expectations={},
        side_effect_classification=required_classification,
        enabled=True,
        schema_version=1,
    )
    db.add(adapter)
    db.flush()
    return capability, adapter


def provision_bridge_runtime_authority(
    *,
    db: Session,
    mission_id: uuid.UUID,
    tenant_id: uuid.UUID,
    admitted_by: str,
) -> dict[str, Any]:
    """Create or resolve capability/adapter pairs for each tool.invoke graph node."""
    tenant_id_str = str(tenant_id)
    mission = MissionRepository(db).get_for_tenant(mission_id=mission_id, tenant_id=tenant_id_str)
    if mission is None:
        raise HTTPException(status_code=404, detail="mission not found for tenant")

    task_graph = (mission.metadata_json or {}).get(MISSION_TASK_GRAPH_METADATA_KEY)
    if not isinstance(task_graph, dict):
        raise HTTPException(status_code=400, detail="mission task graph is required before bridge authority")

    nodes = task_graph.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        raise HTTPException(status_code=400, detail="mission task graph nodes are required before bridge authority")

    node_authorities: list[dict[str, str]] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_key = node.get("key")
        if not isinstance(node_key, str) or not node_key.strip():
            continue
        action_name = _action_from_graph_node(node)
        if action_name is None:
            continue
        capability, adapter = _ensure_bridge_authority(
            db=db,
            tenant_id=tenant_id_str,
            action_name=action_name,
            approved_by=admitted_by,
            tool_input=_tool_input_from_graph_node(node),
            credential_reference=_credential_reference_from_graph_node(node),
        )
        node_authorities.append(
            {
                "node_key": node_key,
                "action": action_name,
                "capability_id": str(capability.id),
                "adapter_id": str(adapter.id),
                "capability_name": capability.name,
            }
        )

    if not node_authorities:
        raise HTTPException(status_code=400, detail="no tool.invoke actions found in mission task graph")

    return {
        "mission_id": str(mission_id),
        "tenant_id": tenant_id_str,
        "node_authorities": node_authorities,
    }
