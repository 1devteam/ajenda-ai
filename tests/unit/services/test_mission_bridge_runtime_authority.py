from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from backend.domain.mission import MISSION_TASK_GRAPH_METADATA_KEY
from backend.services.mission_bridge_runtime_authority import (
    _action_from_graph_node,
    _bridge_capability_name,
    _credential_reference_from_graph_node,
    _effective_side_effect_for_bridge,
    provision_bridge_runtime_authority,
)
from backend.services.tools.action_registry import get_default_action_registry
from backend.services.tools.schemas import SideEffectClass

pytestmark = pytest.mark.unit


def test_action_from_graph_node_reads_tool_invocation_action() -> None:
    node = {
        "input_contract": {
            "tool_invocation": {"action": "web.search", "input": {"query": "test"}},
        }
    }
    assert _action_from_graph_node(node) == "web.search"


def test_bridge_capability_name_is_deterministic() -> None:
    assert _bridge_capability_name("gtm.lead_enrich") == "bridge_gtm_lead_enrich"


def test_crm_bridge_persists_external_read_for_explicit_crm_context() -> None:
    definition = get_default_action_registry(rebuild=True).get("sales.research")
    assert (
        _effective_side_effect_for_bridge(
            definition=definition,
            action_name="sales.research",
            tool_input={"context": {"require_external_crm": True}},
        )
        == SideEffectClass.EXTERNAL_READ
    )


def test_crm_bridge_persists_external_write_for_graph_credential_reference() -> None:
    definition = get_default_action_registry(rebuild=True).get("gtm.crm_upsert")
    assert (
        _effective_side_effect_for_bridge(
            definition=definition,
            action_name="gtm.crm_upsert",
            tool_input={"record_type": "contact", "data": {"email": "real@example.com"}},
            credential_reference={
                "credential_id": "hubspot-crm",
                "provider": "external_crm",
                "credential_type": "api_key",
            },
        )
        == SideEffectClass.EXTERNAL_WRITE
    )


def test_graph_credential_reference_is_read_from_input_contract() -> None:
    assert _credential_reference_from_graph_node(
        {
            "input_contract": {
                "credential_reference": {
                    "credential_id": "hubspot-crm",
                    "provider": "external_crm",
                }
            }
        }
    ) == {"credential_id": "hubspot-crm", "provider": "external_crm"}


def test_provision_bridge_runtime_authority_requires_task_graph() -> None:
    mission_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    mission = SimpleNamespace(id=mission_id, metadata_json={})
    db = MagicMock()
    repo = MagicMock()
    repo.get_for_tenant.return_value = mission

    with patch("backend.services.mission_bridge_runtime_authority.MissionRepository", return_value=repo):
        with pytest.raises(HTTPException) as exc:
            provision_bridge_runtime_authority(
                db=db,
                mission_id=mission_id,
                tenant_id=tenant_id,
                admitted_by="test-user",
            )

    assert exc.value.status_code == 400
    assert "task graph" in exc.value.detail


def test_provision_bridge_runtime_authority_returns_node_authorities() -> None:
    mission_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    capability_id = uuid.uuid4()
    adapter_id = uuid.uuid4()
    mission = SimpleNamespace(
        id=mission_id,
        metadata_json={
            MISSION_TASK_GRAPH_METADATA_KEY: {
                "nodes": [
                    {
                        "key": "ability-web-search",
                        "input_contract": {
                            "tool_invocation": {"action": "web.search", "input": {"query": "test"}},
                        },
                    }
                ]
            }
        },
    )
    db = MagicMock()
    repo = MagicMock()
    repo.get_for_tenant.return_value = mission
    capability = SimpleNamespace(id=capability_id, name="bridge_web_search")
    adapter = SimpleNamespace(id=adapter_id)

    with (
        patch("backend.services.mission_bridge_runtime_authority.MissionRepository", return_value=repo),
        patch(
            "backend.services.mission_bridge_runtime_authority._ensure_bridge_authority",
            return_value=(capability, adapter),
        ),
    ):
        result = provision_bridge_runtime_authority(
            db=db,
            mission_id=mission_id,
            tenant_id=tenant_id,
            admitted_by="test-user",
        )

    assert result["mission_id"] == str(mission_id)
    assert result["node_authorities"] == [
        {
            "node_key": "ability-web-search",
            "action": "web.search",
            "capability_id": str(capability_id),
            "adapter_id": str(adapter_id),
            "capability_name": "bridge_web_search",
        }
    ]
