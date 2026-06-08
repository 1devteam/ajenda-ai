"""Ability rollout manifest contracts.

This module defines the static rollout contract that future abilities/tools must
satisfy before they are promoted into runtime use. It does not execute tools,
register handlers, or bypass the existing tool.invoke runtime authority.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.services.tools.schemas import SideEffectClass


class AbilityRiskLevel(StrEnum):
    """Risk classification for an ability rollout."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


_WRITE_OR_SEND_EFFECTS = {
    SideEffectClass.INTERNAL_WRITE,
    SideEffectClass.EXTERNAL_WRITE,
    SideEffectClass.EXTERNAL_SEND,
    SideEffectClass.EXTERNAL_PUBLISH,
}


_SIDE_EFFECT_RANK = {
    SideEffectClass.NONE: 0,
    SideEffectClass.INTERNAL_READ: 1,
    SideEffectClass.EXTERNAL_READ: 2,
    SideEffectClass.INTERNAL_WRITE: 3,
    SideEffectClass.EXTERNAL_WRITE: 4,
    SideEffectClass.EXTERNAL_SEND: 5,
    SideEffectClass.EXTERNAL_PUBLISH: 6,
}


def _side_effect_rank(side_effect_class: SideEffectClass) -> int:
    return _SIDE_EFFECT_RANK[side_effect_class]


class AbilityManifest(BaseModel):
    """Static contract describing one rollout-ready ability."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    ability_id: str = Field(min_length=1, max_length=160)
    display_name: str = Field(min_length=1, max_length=240)
    action_name: str = Field(min_length=1, max_length=160)
    provider: str = Field(min_length=1, max_length=160)
    capability_name: str = Field(min_length=1, max_length=160)
    capability_version: str = Field(min_length=1, max_length=80)
    adapter_name: str = Field(min_length=1, max_length=160)
    adapter_version: str = Field(min_length=1, max_length=80)
    input_schema_ref: str = Field(min_length=1, max_length=240)
    output_schema_ref: str = Field(min_length=1, max_length=240)
    side_effect_class: SideEffectClass = SideEffectClass.NONE
    max_side_effect_class: SideEffectClass | None = None
    risk_level: AbilityRiskLevel = AbilityRiskLevel.LOW
    required_permissions: list[str] = Field(default_factory=list)
    required_tools: list[str] = Field(default_factory=list)
    approval_required: bool = False
    idempotency_required: bool = False
    evidence_required: bool = True
    readback_required: bool = False
    readback_deferred_reason: str | None = Field(default=None, max_length=500)
    enabled_by_default: bool = False

    @field_validator(
        "ability_id",
        "display_name",
        "action_name",
        "provider",
        "capability_name",
        "capability_version",
        "adapter_name",
        "adapter_version",
        "input_schema_ref",
        "output_schema_ref",
    )
    @classmethod
    def strip_required_strings(cls, value: str) -> str:
        """Normalize required string fields and reject whitespace-only values."""

        stripped = value.strip()
        if not stripped:
            raise ValueError("field must be non-empty")
        return stripped

    @field_validator("required_permissions", "required_tools")
    @classmethod
    def normalize_string_list(cls, values: list[str]) -> list[str]:
        """Normalize list fields and reject blank entries."""

        normalized: list[str] = []
        for value in values:
            stripped = value.strip()
            if not stripped:
                raise ValueError("list entries must be non-empty")
            normalized.append(stripped)
        return normalized

    @model_validator(mode="after")
    def validate_rollout_policy(self) -> AbilityManifest:
        """Enforce rollout rules that make abilities safe to promote."""

        effective_side_effect_class = self.max_side_effect_class or self.side_effect_class
        if _side_effect_rank(effective_side_effect_class) < _side_effect_rank(self.side_effect_class):
            raise ValueError("max_side_effect_class cannot be lower than side_effect_class")
        if effective_side_effect_class.has_side_effect and not self.approval_required:
            raise ValueError("side-effecting abilities require approval_required=true")
        if (
            effective_side_effect_class
            in {
                SideEffectClass.EXTERNAL_WRITE,
                SideEffectClass.EXTERNAL_SEND,
                SideEffectClass.EXTERNAL_PUBLISH,
            }
            and not self.idempotency_required
        ):
            raise ValueError("external write/send/publish abilities require idempotency_required=true")
        if not self.evidence_required:
            raise ValueError("runtime ability manifests require evidence_required=true")
        if effective_side_effect_class in _WRITE_OR_SEND_EFFECTS and not self.readback_required:
            if not self.readback_deferred_reason:
                raise ValueError("write/send/publish abilities require readback_required=true or a deferred reason")
        if self.enabled_by_default and self.risk_level in {AbilityRiskLevel.HIGH, AbilityRiskLevel.CRITICAL}:
            raise ValueError("high or critical risk abilities cannot be enabled by default")
        return self
