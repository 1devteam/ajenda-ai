"""Safe, payload-bound governance records for manifest-backed abilities.

The ability manifest remains a static policy declaration.  This module turns
the policy parts that matter at runtime into bounded task metadata and a
reviewer-issued grant.  It never executes an action or grants authority by
itself; queue admission and :class:`ToolRuntimeAuthority` remain the only
enforcement owners.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from backend.services.abilities.manifest import AbilityManifest
from backend.services.tools.schemas import ToolInvocation, tool_invocation_sha256

ABILITY_GOVERNANCE_SCHEMA_VERSION = 1


def manifest_fingerprint(manifest: AbilityManifest) -> str:
    """Return a stable fingerprint of the complete static ability contract."""

    encoded = json.dumps(
        manifest.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def manifest_governance_snapshot(manifest: AbilityManifest) -> dict[str, Any]:
    """Project policy-only manifest facts suitable for durable task metadata.

    This deliberately excludes task input, credentials, destinations, and
    external content.  The snapshot is evidence of the declared policy at
    task creation; the worker still validates the current manifest.
    """

    return {
        "schema_version": ABILITY_GOVERNANCE_SCHEMA_VERSION,
        "ability_id": manifest.ability_id,
        "action_name": manifest.action_name,
        "provider": manifest.provider,
        "capability": {"name": manifest.capability_name, "version": manifest.capability_version},
        "adapter": {"name": manifest.adapter_name, "version": manifest.adapter_version},
        "side_effect_class": manifest.side_effect_class.value,
        "max_side_effect_class": (
            manifest.max_side_effect_class.value if manifest.max_side_effect_class is not None else None
        ),
        "risk_level": manifest.risk_level.value,
        "approval_required": manifest.approval_required,
        "evidence_required": manifest.evidence_required,
        "readback_required": manifest.readback_required,
        "manifest_fingerprint": manifest_fingerprint(manifest),
    }


class AbilityAuthorizationV1(BaseModel):
    """A tenant-, task-, policy-, and invocation-bound human-review grant."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    grant_id: uuid.UUID
    tenant_id: str = Field(min_length=1, max_length=128)
    task_id: uuid.UUID
    ability_id: str = Field(min_length=1, max_length=160)
    manifest_fingerprint: str = Field(min_length=8, max_length=80)
    allowed_action: str = Field(min_length=1, max_length=160)
    invocation_sha256: str = Field(min_length=8, max_length=80)
    reason: str = Field(min_length=1, max_length=500)
    approved_by: str = Field(min_length=1, max_length=160)
    approved_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None
    revoked_by: str | None = Field(default=None, min_length=1, max_length=160)
    revocation_reason: str | None = Field(default=None, min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_lifetime(self) -> AbilityAuthorizationV1:
        if self.approved_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("ability approval timestamps must be timezone-aware")
        if self.expires_at <= self.approved_at:
            raise ValueError("ability approval must expire after approval")
        if (self.revoked_by is None) != (self.revoked_at is None):
            raise ValueError("ability approval revocation actor and timestamp must be provided together")
        return self


def ability_authorized(
    metadata: Mapping[str, Any],
    *,
    manifest: AbilityManifest,
    tenant_id: str,
    task_id: uuid.UUID,
    now: datetime | None = None,
) -> bool:
    """Return whether a task has a current approval for this exact ability run."""

    constraints = metadata.get("execution_constraints")
    if not isinstance(constraints, Mapping):
        return False
    raw_grant = constraints.get("ability_authorization")
    if not isinstance(raw_grant, Mapping):
        return False
    raw_invocation = metadata.get("tool_invocation")
    if not isinstance(raw_invocation, Mapping):
        return False
    try:
        grant = AbilityAuthorizationV1.model_validate(dict(raw_grant))
        invocation_hash = tool_invocation_sha256(ToolInvocation.model_validate(dict(raw_invocation)))
    except (ValidationError, TypeError, ValueError):
        return False
    current_time = now or datetime.now(UTC)
    return (
        grant.tenant_id == tenant_id
        and grant.task_id == task_id
        and grant.ability_id == manifest.ability_id
        and grant.manifest_fingerprint == manifest_fingerprint(manifest)
        and grant.allowed_action == manifest.action_name
        and grant.invocation_sha256 == invocation_hash
        and grant.revoked_at is None
        and current_time < grant.expires_at
    )
