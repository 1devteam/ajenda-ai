from typing import Any, Literal
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.services.tools.schemas import CredentialReference

class AbilityActionRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    provider: str
    side_effect_class: str
    enabled: bool
    label: str
    requires_authority: bool
    provider_mode: Literal["local", "external", "mixed"]

class AbilityActionListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actions: list[AbilityActionRead]

class AbilityTaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str = Field(min_length=1, max_length=160)
    input: dict[str, Any] = Field(default_factory=dict)
    title: str | None = Field(default=None, max_length=240)
    description: str | None = Field(default=None, max_length=1000)
    mission_objective: str | None = Field(default=None, max_length=1000)
    mission_id: uuid.UUID | None = None
    idempotency_key: str | None = Field(default=None, max_length=200)
    approved_by: str = Field(default="ability-runtime-ui", min_length=1, max_length=160)
    approval_reason: str = Field(default="User launched ability from product runtime UI.", min_length=1, max_length=500)
    credential_reference: CredentialReference | None = None
    capability_id: uuid.UUID | None = None
    adapter_id: uuid.UUID | None = None
    autonomy_acknowledgment: dict[str, Any] | None = None

    @field_validator("action")
    @classmethod
    def normalize_action(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("action must be non-empty")
        return normalized

class AbilityTaskQueuedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: uuid.UUID
    mission_id: uuid.UUID
    status: str
    action: str
    queue_status: str
    queue_reason: str | None = None

class AbilityTaskStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: uuid.UUID
    mission_id: uuid.UUID | None
    title: str
    description: str | None
    status: str
    action: str | None
    metadata_json: dict[str, Any]
    lineage: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    audit: list[dict[str, Any]]

