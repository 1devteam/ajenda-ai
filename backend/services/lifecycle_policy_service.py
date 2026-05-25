from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from fastapi import HTTPException


@dataclass(frozen=True)
class LifecyclePolicyConfig:
    enforce_retention_class: bool = False
    enforce_escalation_transitions: bool = False
    enforce_provenance_confidence_floor: bool = False
    provenance_confidence_floor: float = 0.0


class LifecyclePolicyService:
    """Service-level lifecycle governance guards with non-breaking defaults."""

    _allowed_review_status_transitions: ClassVar[dict[str, set[str]]] = {
        "draft": {"draft", "in_review", "archived"},
        "in_review": {"in_review", "completed", "escalated", "archived", "superseded"},
        "completed": {"completed", "archived", "superseded", "escalated"},
        "escalated": {"escalated", "in_review", "completed", "archived", "superseded"},
        "superseded": {"superseded", "archived"},
        "archived": {"archived"},
    }

    def __init__(self, config: LifecyclePolicyConfig) -> None:
        self._config = config

    def validate_evidence_payload(self, *, provenance_metadata: dict[str, Any], confidence: float | None) -> None:
        if self._config.enforce_retention_class:
            retention_class = provenance_metadata.get("retention_class")
            if not isinstance(retention_class, str) or not retention_class.strip():
                raise HTTPException(status_code=422, detail="retention_class is required by lifecycle policy")
        self._validate_provenance_confidence_floor(confidence=confidence)

    def validate_outcome_create(self, *, review_status: str, confidence: float | None) -> None:
        if self._config.enforce_escalation_transitions and review_status == "escalated":
            raise HTTPException(status_code=422, detail="cannot create outcome review directly in escalated status")
        self._validate_provenance_confidence_floor(confidence=confidence)

    def validate_outcome_status_transition(
        self, *, previous_status: str, next_status: str, confidence: float | None
    ) -> None:
        if self._config.enforce_escalation_transitions:
            allowed = self._allowed_review_status_transitions.get(previous_status, {previous_status})
            if next_status not in allowed:
                raise HTTPException(
                    status_code=422,
                    detail=f"invalid lifecycle status transition: {previous_status} -> {next_status}",
                )
        self._validate_provenance_confidence_floor(confidence=confidence)

    def _validate_provenance_confidence_floor(self, *, confidence: float | None) -> None:
        if not self._config.enforce_provenance_confidence_floor:
            return
        if confidence is None:
            raise HTTPException(status_code=422, detail="confidence is required by lifecycle policy")
        if confidence < self._config.provenance_confidence_floor:
            raise HTTPException(
                status_code=422,
                detail=f"confidence is below lifecycle policy floor ({self._config.provenance_confidence_floor:.2f})",
            )
