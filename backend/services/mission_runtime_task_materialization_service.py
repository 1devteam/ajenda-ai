from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.domain.enums import ExecutionTaskState
from backend.domain.execution_task import ExecutionTask
from backend.domain.mission import MISSION_RUNTIME_TASK_MATERIALIZATION_METADATA_KEY
from backend.repositories.capability_adapter_repository import CapabilityAdapterRepository
from backend.repositories.capability_repository import CapabilityRepository
from backend.repositories.execution_task_repository import ExecutionTaskRepository
from backend.repositories.mission_repository import MissionRepository
from backend.repositories.outcome_review_repository import OutcomeReviewRepository
from backend.services.mission_runtime_projection import (
    build_execution_task_payload,
    build_runtime_task_materialization_metadata,
    materialization_reference_current,
)


class MissionRuntimeTaskMaterializationService:
    """Owns runtime ExecutionTask materialization business logic for missions."""

    def __init__(
        self,
        db: Session,
        *,
        mission_repository_cls: Any = MissionRepository,
        execution_task_repository_cls: Any = ExecutionTaskRepository,
        capability_repository_cls: Any = CapabilityRepository,
        capability_adapter_repository_cls: Any = CapabilityAdapterRepository,
        outcome_review_repository_cls: Any = OutcomeReviewRepository,
    ) -> None:
        self._db = db
        self._mission_repository_cls = mission_repository_cls
        self._execution_task_repository_cls = execution_task_repository_cls
        self._capability_repository_cls = capability_repository_cls
        self._capability_adapter_repository_cls = capability_adapter_repository_cls
        self._outcome_review_repository_cls = outcome_review_repository_cls

    def materialize(self, *, mission_id: UUID, tenant_id: UUID) -> Any:
        from backend.services.mission_bridge.materialization import (
            build_blocked_runtime_task_materialization_read,
            build_mission_runtime_readiness,
            build_runtime_task_preview_items,
            readiness_item,
            runtime_task_materialization_to_read,
        )
        from backend.services.mission_bridge.read_models import RuntimeReadinessRead

        tenant_id_str = str(tenant_id)
        mission_repo = self._mission_repository_cls(self._db)
        mission = mission_repo.lock_for_tenant(mission_id=mission_id, tenant_id=tenant_id_str)
        if mission is None:
            raise HTTPException(status_code=404, detail="mission not found for tenant")

        readiness = build_mission_runtime_readiness(
            mission_id=mission_id,
            tenant_id=tenant_id,
            db=self._db,
            mission_repository_cls=self._mission_repository_cls,
            capability_repository_cls=self._capability_repository_cls,
            capability_adapter_repository_cls=self._capability_adapter_repository_cls,
            outcome_review_repository_cls=self._outcome_review_repository_cls,
        )
        if not readiness.ready:
            if any(blocker.code == "runtime_admission_not_admitted" for blocker in readiness.blockers):
                raise HTTPException(status_code=400, detail="runtime admission must be admitted before materialization")
            if any(blocker.code == "graph_reference_mismatch" for blocker in readiness.blockers):
                raise HTTPException(
                    status_code=400, detail="runtime admission graph reference does not match current task graph"
                )
            return build_blocked_runtime_task_materialization_read(readiness=readiness)

        tasks = build_runtime_task_preview_items(mission_id=mission_id, readiness=readiness)
        if len(tasks) != readiness.selected_node_count:
            incomplete_readiness_payload = readiness.model_dump()
            incomplete_readiness_payload["ready"] = False
            incomplete_readiness_payload["readiness_status"] = "incomplete"
            incomplete_readiness_payload["blockers"] = [
                *readiness.blockers,
                readiness_item(
                    code="runtime_task_preview_incomplete",
                    status="failed",
                    message="Runtime task preview did not produce one task for each selected node.",
                    details={"task_count": len(tasks), "selected_node_count": readiness.selected_node_count},
                ),
            ]
            return build_blocked_runtime_task_materialization_read(
                readiness=RuntimeReadinessRead.model_validate(incomplete_readiness_payload)
            )

        metadata = dict(mission.metadata_json or {})
        existing = metadata.get(MISSION_RUNTIME_TASK_MATERIALIZATION_METADATA_KEY)
        if isinstance(existing, dict) and materialization_reference_current(
            task_materialization=existing,
            graph_reference=readiness.graph_reference,
            materialization_reference=readiness.materialization_reference,
            admission_reference=readiness.admission_reference,
        ):
            return runtime_task_materialization_to_read(
                mission=mission, metadata=existing, blockers=readiness.blockers, warnings=readiness.warnings
            )

        previous_version = existing.get("materialization_version", 0) if isinstance(existing, dict) else 0
        task_repo = self._execution_task_repository_cls(self._db)
        created_task_ids: list[str] = []
        for task_preview in tasks:
            payload = build_execution_task_payload(task_preview)
            task = ExecutionTask(
                tenant_id=tenant_id_str,
                mission_id=mission_id,
                title=task_preview.graph_node_name or task_preview.graph_node_key,
                description=(
                    task_preview.operator_notes
                    or f"Planned runtime task for mission graph node {task_preview.graph_node_key}."
                ),
                status=ExecutionTaskState.PLANNED.value,
                metadata_json=payload,
                compliance_category=mission.compliance_category,
                jurisdiction=mission.jurisdiction,
            )
            created = task_repo.add(task)
            created_task_ids.append(str(created.id))

        task_materialization = build_runtime_task_materialization_metadata(
            mission_id=mission_id,
            materialization_version=previous_version + 1,
            created_execution_task_ids=created_task_ids,
            graph_reference=readiness.graph_reference,
            materialization_reference=readiness.materialization_reference,
            admission_reference=readiness.admission_reference,
            materialized_by="runtime-task-materialization-api",
            now=datetime.now(UTC).isoformat(),
        )
        metadata[MISSION_RUNTIME_TASK_MATERIALIZATION_METADATA_KEY] = task_materialization
        mission = mission_repo.update_metadata(mission=mission, metadata_json=metadata)
        return runtime_task_materialization_to_read(
            mission=mission,
            metadata=task_materialization,
            blockers=readiness.blockers,
            warnings=readiness.warnings,
        )
