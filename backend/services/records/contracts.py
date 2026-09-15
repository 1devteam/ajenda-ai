"""Kernel CRM identity and effect-receipt contracts.

These models are Ajenda Records authority. They do not belong to a vertical pack.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EffectCertainty(StrEnum):
    VERIFIED = "verified"
    REJECTED = "rejected"
    AMBIGUOUS = "ambiguous"


class IdentityDecisionStatus(StrEnum):
    MATCHED = "matched"
    NEW = "new"
    AMBIGUOUS = "ambiguous"
    REJECTED = "rejected"


class IdentityMatchDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    decision_status: IdentityDecisionStatus
    candidate_ids: tuple[str, ...] = Field(min_length=1, max_length=100)
    canonical_entity_id: str | None = Field(default=None, max_length=160)
    supporting_evidence_ids: tuple[str, ...] = Field(default=(), max_length=100)
    conflicting_evidence_ids: tuple[str, ...] = Field(default=(), max_length=100)
    rule_version: str = Field(min_length=1, max_length=80)
    decided_by: str = Field(min_length=1, max_length=160)

    @model_validator(mode="after")
    def validate_identity_claim(self) -> IdentityMatchDecision:
        if self.decision_status == IdentityDecisionStatus.MATCHED and not self.canonical_entity_id:
            raise ValueError("matched identity decision requires canonical_entity_id")
        if self.decision_status in {IdentityDecisionStatus.AMBIGUOUS, IdentityDecisionStatus.REJECTED}:
            if self.canonical_entity_id is not None:
                raise ValueError("ambiguous or rejected identity decision cannot select a canonical entity")
        return self


class EffectReceiptContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    provider: str = Field(min_length=1, max_length=120)
    provider_account_id: str = Field(min_length=1, max_length=160)
    action_name: str = Field(min_length=1, max_length=160)
    idempotency_key: str = Field(min_length=1, max_length=240)
    request_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    attempted_at: datetime
    certainty: EffectCertainty
    provider_object_ids: tuple[str, ...] = Field(default=(), max_length=100)
    read_back_at: datetime | None = None
    read_back_hash: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_certainty(self) -> EffectReceiptContract:
        if self.certainty == EffectCertainty.VERIFIED:
            if not self.provider_object_ids or self.read_back_at is None or self.read_back_hash is None:
                raise ValueError("verified effect requires provider identity and read-back proof")
        if self.certainty == EffectCertainty.AMBIGUOUS and self.read_back_hash is not None:
            raise ValueError("ambiguous effect cannot claim a conclusive read-back hash")
        return self
