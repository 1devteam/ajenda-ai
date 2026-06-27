"""Shared capability/adapter fixtures for credentialed tool.invoke integration tests."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from backend.domain.capability import Capability
from backend.domain.capability_adapter import CapabilityAdapter


def seed_capability_adapter_authority(
    session: Session,
    *,
    tenant_id: str,
    action_name: str,
    side_effect_classification: str,
    extra_tools: tuple[str, ...] = (),
) -> dict[str, dict[str, str]]:
    capability_id = uuid.uuid4()
    adapter_id = uuid.uuid4()
    required_tools = sorted({action_name, *extra_tools})
    risk_level = "high" if side_effect_classification.startswith("external_") else "medium"
    approval_requirements = (
        {"required": True} if side_effect_classification in {"external_write", "external_send", "external_publish"} else {}
    )
    capability = Capability(
        id=capability_id,
        tenant_id=tenant_id,
        name=f"integration_{action_name.replace('.', '_')}",
        version="1.0.0",
        description=f"Integration capability for {action_name}",
        supported_task_types=["tool.invoke", action_name],
        required_tools=required_tools,
        risk_level=risk_level,
        enabled=True,
    )
    adapter = CapabilityAdapter(
        id=adapter_id,
        tenant_id=tenant_id,
        name=f"integration_{action_name.replace('.', '_')}_adapter",
        version="1.0.0",
        capability_id=capability_id,
        capability_name=capability.name,
        capability_version=capability.version,
        supported_task_types=["tool.invoke", action_name],
        required_tools=required_tools,
        risk_level=risk_level,
        approval_requirements=approval_requirements,
        side_effect_classification=side_effect_classification,
        enabled=True,
    )
    session.add(capability)
    session.add(adapter)
    session.flush()
    return {
        "capability_reference": {"capability_id": str(capability_id)},
        "adapter_reference": {"adapter_id": str(adapter_id)},
    }


def side_effect_authorization(*, allowed_actions: list[str], approved_by: str = "integration") -> dict[str, Any]:
    return {
        "execution_constraints": {
            "side_effect_authorization": {
                "schema_version": 1,
                "allowed_actions": allowed_actions,
                "reason": "integration test authority",
                "approved_by": approved_by,
            }
        }
    }