"""Durable, non-authoritative mission metadata for requested deliverables.

This module serializes the interpreted deliverable request and its structural
artifact projection so runtime can evaluate materialized outputs without
reinterpreting the original instruction. The envelope grants no execution
authority and does not claim that any artifact has been produced.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from backend.services.mission_composition.deliverable_contract import DeliverableRequest
from backend.services.mission_composition.deliverable_projection import (
    DeliverableProjection,
    project_deliverable_request,
)

DELIVERABLE_RUNTIME_STATE_METADATA_KEY = "deliverable_runtime_state"


class DeliverableRuntimeState(BaseModel):
    """Persistable semantic/projection state required for runtime evaluation."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    request: DeliverableRequest
    projection: DeliverableProjection
    completion: dict[str, object] | None = None
    grants_execution_authority: Literal[False] = False


def build_deliverable_runtime_state(
    request: DeliverableRequest | None,
    *,
    minimum_rows: int = 0,
    minimum_rows_by_artifact: dict[str, int] | None = None,
) -> dict[str, object] | None:
    """Build JSON-safe durable state from the canonical interpreted request."""

    if request is None:
        return None
    state = DeliverableRuntimeState(
        request=request,
        projection=project_deliverable_request(
            request,
            minimum_rows=minimum_rows,
            minimum_rows_by_artifact=minimum_rows_by_artifact,
        ),
    )
    return state.model_dump(mode="json")


def load_deliverable_runtime_state(raw: object) -> DeliverableRuntimeState | None:
    """Load durable state fail closed; callers decide how to surface invalid metadata."""

    if raw is None:
        return None
    return DeliverableRuntimeState.model_validate(raw)
