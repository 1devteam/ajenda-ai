"""Trust-boundary tests for side-effect authorization and task payload minting."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from backend.services.mission_runtime_projection import build_execution_task_payload
from backend.services.tools.schemas import (
    is_client_forged_side_effect_approver,
    side_effect_authorized,
    tool_invocation_sha256,
)


def test_client_forged_dispatch_ui_approver_rejected() -> None:
    assert is_client_forged_side_effect_approver("mission-dispatch-ui") is True
    assert is_client_forged_side_effect_approver("mission_dispatch_ui") is True
    assert is_client_forged_side_effect_approver("server:runtime_task_materialization") is True
    assert is_client_forged_side_effect_approver("mission_composition_engine") is True


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


def test_side_effect_authorized_only_accepts_independent_approver() -> None:
    for approved_by, expected in (
        ("server:runtime_task_materialization", False),
        ("mission_composition_engine", False),
        ("operator-user-1", True),
    ):
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
        assert side_effect_authorized(metadata, "gtm.email_send") is expected


def test_build_execution_task_payload_strips_forged_without_minting_auth() -> None:
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
    assert "execution_constraints" not in payload
    assert side_effect_authorized(payload, "gtm.email_send") is False


def _v2_metadata(*, tenant_id: str, task_id: uuid.UUID, now: datetime) -> dict[str, object]:
    invocation = {
        "schema_version": 1,
        "action": "gtm.email_send",
        "input": {"to": "lead@example.com", "subject": "Reviewed", "body": "Hello"},
    }
    return {
        "tool_invocation": invocation,
        "execution_constraints": {
            "side_effect_authorization": {
                "schema_version": 2,
                "grant_id": str(uuid.uuid4()),
                "tenant_id": tenant_id,
                "task_id": str(task_id),
                "allowed_action": "gtm.email_send",
                "invocation_sha256": tool_invocation_sha256(invocation),
                "reason": "human_review_approved",
                "approved_by": "admin:user-1",
                "approved_at": now.isoformat(),
                "expires_at": (now + timedelta(hours=1)).isoformat(),
                "revoked_at": None,
            }
        },
    }


def test_v2_approval_is_tenant_task_payload_and_expiry_bound() -> None:
    now = datetime.now(UTC)
    tenant_id = str(uuid.uuid4())
    task_id = uuid.uuid4()
    metadata = _v2_metadata(tenant_id=tenant_id, task_id=task_id, now=now)

    assert side_effect_authorized(
        metadata,
        "gtm.email_send",
        tenant_id=tenant_id,
        task_id=task_id,
        now=now,
    )
    assert not side_effect_authorized(
        metadata,
        "gtm.email_send",
        tenant_id=str(uuid.uuid4()),
        task_id=task_id,
        now=now,
    )
    assert not side_effect_authorized(
        metadata,
        "gtm.email_send",
        tenant_id=tenant_id,
        task_id=uuid.uuid4(),
        now=now,
    )
    assert not side_effect_authorized(
        metadata,
        "gtm.email_send",
        tenant_id=tenant_id,
        task_id=task_id,
        now=now + timedelta(hours=2),
    )


def test_v2_approval_rejects_changed_or_revoked_payload() -> None:
    now = datetime.now(UTC)
    tenant_id = str(uuid.uuid4())
    task_id = uuid.uuid4()
    metadata = _v2_metadata(tenant_id=tenant_id, task_id=task_id, now=now)
    metadata["tool_invocation"]["input"]["subject"] = "Changed after review"  # type: ignore[index]
    assert not side_effect_authorized(
        metadata,
        "gtm.email_send",
        tenant_id=tenant_id,
        task_id=task_id,
        now=now,
    )

    metadata = _v2_metadata(tenant_id=tenant_id, task_id=task_id, now=now)
    metadata["execution_constraints"]["side_effect_authorization"]["revoked_at"] = now.isoformat()  # type: ignore[index]
    assert not side_effect_authorized(
        metadata,
        "gtm.email_send",
        tenant_id=tenant_id,
        task_id=task_id,
        now=now,
    )
