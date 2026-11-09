from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from backend.services.abilities.catalog import ABILITY_MANIFESTS_BY_ACTION
from backend.services.abilities.runtime_governance import (
    AbilityAuthorizationV1,
    ability_authorized,
    manifest_fingerprint,
    manifest_governance_snapshot,
)
from backend.services.tools.schemas import ToolInvocation, tool_invocation_sha256


def _browser_metadata(*, task_id: uuid.UUID) -> dict[str, object]:
    return {
        "tool_invocation": {
            "schema_version": 1,
            "action": "web.browser_session",
            "input": {"url": "https://example.test"},
        },
        "capability_reference": {"capability_id": str(uuid.uuid4())},
        "adapter_reference": {"adapter_id": str(uuid.uuid4())},
    }


def test_manifest_governance_snapshot_is_policy_only() -> None:
    manifest = ABILITY_MANIFESTS_BY_ACTION["web.browser_session"]

    snapshot = manifest_governance_snapshot(manifest)

    assert snapshot["ability_id"] == "web-browser-session"
    assert snapshot["approval_required"] is False
    assert snapshot["side_effect_class"] == "external_read"
    assert snapshot["manifest_fingerprint"] == manifest_fingerprint(manifest)
    assert "url" not in snapshot
    assert "input" not in snapshot
    assert "credential" not in snapshot


def test_ability_authorization_is_bound_to_task_policy_and_invocation() -> None:
    tenant_id = "tenant-a"
    task_id = uuid.uuid4()
    manifest = ABILITY_MANIFESTS_BY_ACTION["web.browser_session"]
    metadata = _browser_metadata(task_id=task_id)
    invocation = ToolInvocation.model_validate(metadata["tool_invocation"])
    approved_at = datetime.now(UTC)
    metadata["execution_constraints"] = {
        "ability_authorization": AbilityAuthorizationV1(
            grant_id=uuid.uuid4(),
            tenant_id=tenant_id,
            task_id=task_id,
            ability_id=manifest.ability_id,
            manifest_fingerprint=manifest_fingerprint(manifest),
            allowed_action=manifest.action_name,
            invocation_sha256=tool_invocation_sha256(invocation),
            reason="human_review_approved",
            approved_by="human:reviewer",
            approved_at=approved_at,
            expires_at=approved_at + timedelta(hours=1),
        ).model_dump(mode="json")
    }

    assert ability_authorized(metadata, manifest=manifest, tenant_id=tenant_id, task_id=task_id)

    metadata["tool_invocation"]["input"]["url"] = "https://other.example.test"  # type: ignore[index]
    assert not ability_authorized(metadata, manifest=manifest, tenant_id=tenant_id, task_id=task_id)
