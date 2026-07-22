"""Trust-boundary tests for side-effect authorization and task payload minting."""

from __future__ import annotations

from backend.services.mission_runtime_projection import build_execution_task_payload
from backend.services.tools.schemas import is_client_forged_side_effect_approver, side_effect_authorized


def test_client_forged_dispatch_ui_approver_rejected() -> None:
    assert is_client_forged_side_effect_approver("mission-dispatch-ui") is True
    assert is_client_forged_side_effect_approver("mission_dispatch_ui") is True
    assert is_client_forged_side_effect_approver("server:runtime_task_materialization") is False
    assert is_client_forged_side_effect_approver("mission_composition_engine") is False


def test_side_effect_authorized_rejects_forged_approver() -> None:
    metadata = {
        "execution_constraints": {
            "side_effect_authorization": {
                "schema_version": 1,
                "allowed_actions": ["gtm.email_send"],
                "reason": "mission_dispatch_ui",
                "approved_by": "mission-dispatch-ui",
            }
        }
    }
    assert side_effect_authorized(metadata, "gtm.email_send") is False


def test_side_effect_authorized_accepts_server_or_composition_approver() -> None:
    for approved_by in ("server:runtime_task_materialization", "mission_composition_engine", "operator-user-1"):
        metadata = {
            "execution_constraints": {
                "side_effect_authorization": {
                    "schema_version": 1,
                    "allowed_actions": ["gtm.email_send"],
                    "reason": "ok",
                    "approved_by": approved_by,
                }
            }
        }
        assert side_effect_authorized(metadata, "gtm.email_send") is True


def test_build_execution_task_payload_strips_forged_and_mints_server_auth() -> None:
    preview = {
        "preview_task_key": "t1",
        "graph_node_key": "ability-gtm-email_send",
        "dependency_keys": [],
        "payload_preview": {
            "runtime_task_type": "tool.invoke",
            "input_contract": {
                "tool_invocation": {
                    "schema_version": 1,
                    "action": "gtm.email_send",
                    "input": {
                        "to": "pending.binding@invalid.local",
                        "subject": "Hi",
                        "body": "Body",
                    },
                },
                "execution_constraints": {
                    "side_effect_authorization": {
                        "schema_version": 1,
                        "allowed_actions": ["gtm.email_send"],
                        "reason": "mission_dispatch_ui",
                        "approved_by": "mission-dispatch-ui",
                    }
                },
            },
        },
    }
    payload = build_execution_task_payload(preview)
    auth = payload["execution_constraints"]["side_effect_authorization"]
    assert auth["approved_by"] == "server:runtime_task_materialization"
    assert auth["allowed_actions"] == ["gtm.email_send"]
    assert side_effect_authorized(payload, "gtm.email_send") is True
