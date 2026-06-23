"""Runtime task materialization and readiness bridge helpers."""

from __future__ import annotations

import hashlib
import json
import uuid as _uuid
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.domain.mission import (
    MISSION_GRAPH_MATERIALIZATION_METADATA_KEY,
    MISSION_RUNTIME_ADMISSION_METADATA_KEY,
    MISSION_TASK_GRAPH_METADATA_KEY,
    Mission,
)
from backend.repositories.capability_adapter_repository import CapabilityAdapterRepository
from backend.repositories.capability_repository import CapabilityRepository
from backend.repositories.mission_repository import MissionRepository
from backend.repositories.outcome_review_repository import OutcomeReviewRepository
from backend.services.mission_bridge.read_models import (
    RuntimeReadinessCheckStatus,
    RuntimeReadinessItem,
    RuntimeReadinessRead,
    RuntimeReadinessStatus,
    RuntimeTaskMaterializationRead,
    RuntimeTaskMaterializationStatus,
    RuntimeTaskPreviewItem,
)
from backend.services.mission_runtime_projection import (
    build_runtime_task_preview_items as project_runtime_task_preview_items,
)
from backend.services.mission_runtime_projection import (
    runtime_materialization_authority_flags,
)
from backend.services.mission_runtime_projection import (
    runtime_preview_authority_flags as projection_runtime_preview_authority_flags,
)


def task_graph_fingerprint(
    *,
    mission_id: str,
    graph_status: str | None,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    operator_notes: str | None,
) -> str:
    graph_identity = {
        "schema_version": 1,
        "mission_id": mission_id,
        "graph_status": graph_status,
        "nodes": nodes,
        "edges": edges,
        "operator_notes": operator_notes,
    }
    encoded = json.dumps(graph_identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return f"sha256:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"


def _task_graph_contract_content(task_graph: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": task_graph["schema_version"],
        "graph_status": task_graph["graph_status"],
        "nodes": task_graph["nodes"],
        "edges": task_graph["edges"],
        "metadata": task_graph["metadata"],
    }


def _task_graph_has_identity(task_graph: dict[str, Any]) -> bool:
    return (
        isinstance(task_graph.get("mission_id"), str)
        and isinstance(task_graph.get("graph_version"), int)
        and isinstance(task_graph.get("graph_fingerprint"), str)
    )


def _task_graph_contract_fingerprint(*, mission_id: str, normalized_graph: dict[str, Any]) -> str:
    graph_identity = {"mission_id": mission_id, **_task_graph_contract_content(normalized_graph)}
    encoded = json.dumps(graph_identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return f"sha256:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"


def _task_graph_with_identity(
    *, mission_id: UUID, normalized_graph: dict[str, Any], graph_version: int
) -> dict[str, Any]:
    mission_id_str = str(mission_id)
    graph_with_identity = {
        **_task_graph_contract_content(normalized_graph),
        "mission_id": mission_id_str,
        "graph_version": graph_version,
    }
    graph_with_identity["graph_fingerprint"] = _task_graph_contract_fingerprint(
        mission_id=mission_id_str, normalized_graph=graph_with_identity
    )
    return graph_with_identity


def fingerprint_existing_task_graph(task_graph: dict[str, Any]) -> str | None:
    nodes = task_graph.get("nodes")
    edges = task_graph.get("edges")
    mission_id = task_graph.get("mission_id")
    if not isinstance(nodes, list) or not isinstance(edges, list) or not isinstance(mission_id, str):
        return None
    if not all(isinstance(node, dict) for node in nodes) or not all(isinstance(edge, dict) for edge in edges):
        return None
    return task_graph_fingerprint(
        mission_id=mission_id,
        graph_status=task_graph.get("graph_status") if isinstance(task_graph.get("graph_status"), str) else None,
        nodes=nodes,
        edges=edges,
        operator_notes=task_graph.get("operator_notes") if isinstance(task_graph.get("operator_notes"), str) else None,
    )


def readiness_item(
    *, code: str, status: RuntimeReadinessCheckStatus, message: str, details: dict[str, Any] | None = None
) -> RuntimeReadinessItem:
    return RuntimeReadinessItem(code=code, status=status, message=message, details=details or {})


def runtime_readiness_reference(metadata: dict[str, Any] | None, key: str) -> dict[str, Any] | None:
    value = (metadata or {}).get(key)
    if isinstance(value, dict):
        return value
    return None


def graph_matches_reference(*, task_graph: dict[str, Any], graph_reference: dict[str, Any] | None) -> bool:
    graph_fingerprint = task_graph.get("graph_fingerprint") or fingerprint_existing_task_graph(task_graph)
    return isinstance(graph_reference, dict) and (
        graph_reference.get("metadata_key") == MISSION_TASK_GRAPH_METADATA_KEY
        and graph_reference.get("graph_version") == task_graph.get("graph_version")
        and graph_reference.get("graph_fingerprint") == graph_fingerprint
    )


def materialization_matches_reference(
    *, materialization: dict[str, Any], materialization_reference: dict[str, Any] | None
) -> bool:
    if not isinstance(materialization_reference, dict):
        return False
    return (
        materialization_reference.get("metadata_key") == MISSION_GRAPH_MATERIALIZATION_METADATA_KEY
        and materialization_reference.get("materialization_status") == materialization.get("materialization_status")
        and materialization_reference.get("materialization_version") == materialization.get("materialization_version")
        and materialization_reference.get("graph_reference") == materialization.get("graph_reference")
    )


def resolve_capability_for_readiness(
    *,
    selected_node: dict[str, Any],
    graph_node: dict[str, Any],
    capability_repo: CapabilityRepository,
    tenant_id: str,
    blockers: list[RuntimeReadinessItem],
    checks: list[RuntimeReadinessItem],
) -> tuple[_uuid.UUID | None, str | None, str | None]:
    capability_id: _uuid.UUID | None = None
    raw_capability_id = selected_node.get("capability_id")
    if isinstance(raw_capability_id, str) and raw_capability_id.strip():
        try:
            capability_id = _uuid.UUID(raw_capability_id)
        except ValueError:
            blockers.append(
                readiness_item(
                    code="capability_not_visible",
                    status="failed",
                    message="Selected node capability_id is not a valid UUID.",
                    details={"node_key": selected_node.get("node_key"), "capability_id": raw_capability_id},
                )
            )
            return None, None, None

    capability_name: str | None = None
    capability_version: str | None = None
    materialization_selection = selected_node.get("materialization_selection_reference")
    if isinstance(materialization_selection, dict):
        raw_name = materialization_selection.get("capability_name")
        raw_version = materialization_selection.get("capability_version")
        if isinstance(raw_name, str) and raw_name.strip():
            capability_name = raw_name.strip()
        if isinstance(raw_version, str) and raw_version.strip():
            capability_version = raw_version.strip()

    raw_capability_refs = graph_node.get("capability_references")
    capability_refs: list[Any] = raw_capability_refs if isinstance(raw_capability_refs, list) else []
    if capability_id is None:
        for capability_ref in capability_refs:
            if not isinstance(capability_ref, dict):
                continue
            raw_ref_id = capability_ref.get("capability_id")
            if isinstance(raw_ref_id, str) and raw_ref_id.strip():
                try:
                    capability_id = _uuid.UUID(raw_ref_id)
                except ValueError:
                    blockers.append(
                        readiness_item(
                            code="capability_not_visible",
                            status="failed",
                            message="Task graph capability_id is not a valid UUID.",
                            details={"node_key": selected_node.get("node_key"), "capability_id": raw_ref_id},
                        )
                    )
                    return None, None, None
                break
            if (
                capability_name is None
                and isinstance(capability_ref.get("name"), str)
                and capability_ref["name"].strip()
            ):
                capability_name = capability_ref["name"].strip()
            if (
                capability_version is None
                and isinstance(capability_ref.get("version"), str)
                and capability_ref["version"].strip()
            ):
                capability_version = capability_ref["version"].strip()

    if capability_id is not None:
        capability = capability_repo.get_visible_for_tenant(capability_id=capability_id, tenant_id=tenant_id)
        if capability is None:
            blockers.append(
                readiness_item(
                    code="capability_not_visible",
                    status="failed",
                    message="Selected node capability is no longer visible to the tenant.",
                    details={"node_key": selected_node.get("node_key"), "capability_id": str(capability_id)},
                )
            )
            return capability_id, capability_name, capability_version
        checks.append(
            readiness_item(
                code="capability_visible",
                status="passed",
                message="Selected node capability is tenant-visible.",
                details={"node_key": selected_node.get("node_key"), "capability_id": str(capability_id)},
            )
        )
        return (
            capability_id,
            getattr(capability, "name", capability_name),
            getattr(capability, "version", capability_version),
        )

    if capability_name and capability_version:
        capability = capability_repo.get_conflict_for_scope(
            name=capability_name,
            version=capability_version,
            tenant_id=tenant_id,
        )
        if capability is None:
            capability = capability_repo.get_conflict_for_scope(
                name=capability_name,
                version=capability_version,
                tenant_id=None,
            )
        if capability is not None:
            checks.append(
                readiness_item(
                    code="capability_visible",
                    status="passed",
                    message="Selected node capability name/version is tenant-visible.",
                    details={
                        "node_key": selected_node.get("node_key"),
                        "capability_name": capability_name,
                        "capability_version": capability_version,
                    },
                )
            )
            return getattr(capability, "id", None), capability_name, capability_version

    blockers.append(
        readiness_item(
            code="capability_not_visible",
            status="failed",
            message="Selected node capability reference is no longer tenant-visible.",
            details={
                "node_key": selected_node.get("node_key"),
                "capability_name": capability_name,
                "capability_version": capability_version,
            },
        )
    )
    return capability_id, capability_name, capability_version


def validate_adapter_for_readiness(
    *,
    selected_node: dict[str, Any],
    admitted_capability_id: _uuid.UUID | None,
    admitted_capability_name: str | None,
    admitted_capability_version: str | None,
    adapter_repo: CapabilityAdapterRepository,
    tenant_id: str,
    blockers: list[RuntimeReadinessItem],
    checks: list[RuntimeReadinessItem],
) -> None:
    raw_adapter_id = selected_node.get("adapter_id")
    if raw_adapter_id is None:
        return
    if not isinstance(raw_adapter_id, str) or not raw_adapter_id.strip():
        blockers.append(
            readiness_item(
                code="adapter_not_visible",
                status="failed",
                message="Selected node adapter_id is invalid.",
                details={"node_key": selected_node.get("node_key"), "adapter_id": raw_adapter_id},
            )
        )
        return
    try:
        adapter_id = _uuid.UUID(raw_adapter_id)
    except ValueError:
        blockers.append(
            readiness_item(
                code="adapter_not_visible",
                status="failed",
                message="Selected node adapter_id is not a valid UUID.",
                details={"node_key": selected_node.get("node_key"), "adapter_id": raw_adapter_id},
            )
        )
        return

    adapter = adapter_repo.get_visible_for_tenant(adapter_id=adapter_id, tenant_id=tenant_id)
    if adapter is None:
        blockers.append(
            readiness_item(
                code="adapter_not_visible",
                status="failed",
                message="Selected node adapter is no longer visible to the tenant.",
                details={"node_key": selected_node.get("node_key"), "adapter_id": str(adapter_id)},
            )
        )
        return

    adapter_capability_id = getattr(adapter, "capability_id", None)
    adapter_capability_name = getattr(adapter, "capability_name", None)
    adapter_capability_version = getattr(adapter, "capability_version", None)

    mismatch_details = {
        "node_key": selected_node.get("node_key"),
        "adapter_id": str(adapter_id),
        "adapter_capability_id": str(adapter_capability_id) if adapter_capability_id is not None else None,
        "adapter_capability_name": adapter_capability_name,
        "adapter_capability_version": adapter_capability_version,
        "admitted_capability_id": str(admitted_capability_id) if admitted_capability_id is not None else None,
        "admitted_capability_name": admitted_capability_name,
        "admitted_capability_version": admitted_capability_version,
    }

    id_binding_matches = (
        adapter_capability_id is not None
        and admitted_capability_id is not None
        and adapter_capability_id == admitted_capability_id
    )
    name_binding_matches = (
        adapter_capability_name is not None
        and admitted_capability_name is not None
        and adapter_capability_name == admitted_capability_name
        and (
            adapter_capability_version is None
            or admitted_capability_version is None
            or adapter_capability_version == admitted_capability_version
        )
    )

    if not id_binding_matches and not name_binding_matches:
        blockers.append(
            readiness_item(
                code="adapter_capability_mismatch",
                status="failed",
                message="Selected adapter binding does not match the admitted capability.",
                details=mismatch_details,
            )
        )
        return

    checks.append(
        readiness_item(
            code="adapter_visible",
            status="passed",
            message="Selected node adapter is tenant-visible and bound to the admitted capability.",
            details={"node_key": selected_node.get("node_key"), "adapter_id": str(adapter_id)},
        )
    )


def build_mission_runtime_readiness(
    *,
    mission_id: UUID,
    tenant_id: _uuid.UUID,
    db: Session,
    mission_repository_cls: Any = MissionRepository,
    capability_repository_cls: Any = CapabilityRepository,
    capability_adapter_repository_cls: Any = CapabilityAdapterRepository,
    outcome_review_repository_cls: Any = OutcomeReviewRepository,
) -> RuntimeReadinessRead:
    """Build the shared read-only runtime admission readiness result."""
    tenant_id_str = str(tenant_id)
    mission = mission_repository_cls(db).get_for_tenant(mission_id=mission_id, tenant_id=tenant_id_str)
    if mission is None:
        raise HTTPException(status_code=404, detail="mission not found for tenant")

    metadata = mission.metadata_json or {}
    task_graph = runtime_readiness_reference(metadata, MISSION_TASK_GRAPH_METADATA_KEY)
    materialization = runtime_readiness_reference(metadata, MISSION_GRAPH_MATERIALIZATION_METADATA_KEY)
    admission = runtime_readiness_reference(metadata, MISSION_RUNTIME_ADMISSION_METADATA_KEY)
    checked_at = datetime.now(UTC).isoformat()
    checks: list[RuntimeReadinessItem] = []
    blockers: list[RuntimeReadinessItem] = []
    warnings: list[RuntimeReadinessItem] = []
    incomplete_codes: set[str] = set()

    if task_graph is None:
        blockers.append(
            readiness_item(
                code="missing_task_graph",
                status="failed",
                message="Current task graph metadata is required before runtime readiness can pass.",
            )
        )
        incomplete_codes.add("missing_task_graph")
    else:
        checks.append(
            readiness_item(
                code="task_graph_present",
                status="passed",
                message="Current task graph metadata is present.",
                details={
                    "graph_version": task_graph.get("graph_version"),
                    "graph_fingerprint": task_graph.get("graph_fingerprint"),
                },
            )
        )

    if materialization is None:
        blockers.append(
            readiness_item(
                code="missing_materialization",
                status="failed",
                message="Current graph materialization metadata is required before runtime readiness can pass.",
            )
        )
        incomplete_codes.add("missing_materialization")
    elif materialization.get("materialization_status") == "superseded":
        blockers.append(
            readiness_item(
                code="materialization_superseded",
                status="failed",
                message="Current graph materialization is superseded.",
                details={"materialization_version": materialization.get("materialization_version")},
            )
        )
    else:
        checks.append(
            readiness_item(
                code="materialization_current",
                status="passed",
                message="Current graph materialization is present and not superseded.",
                details={
                    "materialization_status": materialization.get("materialization_status"),
                    "materialization_version": materialization.get("materialization_version"),
                },
            )
        )

    if admission is None:
        blockers.append(
            readiness_item(
                code="missing_runtime_admission",
                status="failed",
                message="Runtime admission metadata is required before runtime readiness can pass.",
            )
        )
        incomplete_codes.add("missing_runtime_admission")
    elif admission.get("admission_status") == "superseded":
        blockers.append(
            readiness_item(
                code="admission_superseded",
                status="failed",
                message="Runtime admission metadata is superseded.",
                details={"admission_version": admission.get("admission_version")},
            )
        )
    elif admission.get("admission_status") != "admitted":
        blockers.append(
            readiness_item(
                code="runtime_admission_not_admitted",
                status="failed",
                message="Runtime admission must have admission_status='admitted' before readiness can pass.",
                details={"admission_status": admission.get("admission_status")},
            )
        )
    else:
        checks.append(
            readiness_item(
                code="runtime_admission_admitted",
                status="passed",
                message="Runtime admission is admitted.",
                details={"admission_version": admission.get("admission_version")},
            )
        )

    selected_nodes = admission.get("selected_nodes") if isinstance(admission, dict) else []
    if not isinstance(selected_nodes, list):
        selected_nodes = []
    if isinstance(admission, dict) and not selected_nodes:
        blockers.append(
            readiness_item(
                code="validation_gap",
                status="failed",
                message="Runtime admission contains no selected nodes for readiness validation.",
            )
        )
        incomplete_codes.add("validation_gap")

    if task_graph is not None and admission is not None:
        if graph_matches_reference(task_graph=task_graph, graph_reference=admission.get("graph_reference")):
            checks.append(
                readiness_item(
                    code="graph_reference_current",
                    status="passed",
                    message="Admission graph reference matches the current task graph.",
                )
            )
        else:
            blockers.append(
                readiness_item(
                    code="graph_reference_mismatch",
                    status="failed",
                    message="Admission graph reference does not match the current task graph version/fingerprint.",
                    details={
                        "current_graph_version": task_graph.get("graph_version"),
                        "current_graph_fingerprint": task_graph.get("graph_fingerprint"),
                        "admission_graph_reference": admission.get("graph_reference"),
                    },
                )
            )

    if materialization is not None and admission is not None:
        if materialization_matches_reference(
            materialization=materialization, materialization_reference=admission.get("materialization_reference")
        ):
            checks.append(
                readiness_item(
                    code="materialization_reference_current",
                    status="passed",
                    message="Admission materialization reference matches the current materialization.",
                )
            )
        else:
            blockers.append(
                readiness_item(
                    code="materialization_reference_mismatch",
                    status="failed",
                    message="Admission materialization reference does not match the current materialization.",
                    details={
                        "current_materialization_version": materialization.get("materialization_version"),
                        "admission_materialization_reference": admission.get("materialization_reference"),
                    },
                )
            )

    outcome_reviews = outcome_review_repository_cls(db).list_for_mission(mission_id=mission_id, tenant_id=tenant_id_str)
    rejected_reviews = [
        review
        for review in outcome_reviews
        if getattr(review, "review_status", None) == "rejected"
        or getattr(review, "review_decision", None) == "rejected"
    ]
    if rejected_reviews:
        blockers.append(
            readiness_item(
                code="rejected_outcome_review",
                status="failed",
                message="At least one approved rejected outcome review blocks runtime materialization readiness.",
                details={"rejected_review_count": len(rejected_reviews)},
            )
        )
    else:
        checks.append(
            readiness_item(
                code="outcome_reviews_non_blocking",
                status="passed",
                message="No approved rejected outcome review blocks runtime materialization readiness.",
                details={"review_count": len(outcome_reviews)},
            )
        )

    capability_repo = capability_repository_cls(db)
    adapter_repo = capability_adapter_repository_cls(db)
    nodes_by_key: dict[str, dict[str, Any]] = {}
    if task_graph is not None and isinstance(task_graph.get("nodes"), list):
        nodes_by_key = {node["key"]: node for node in task_graph["nodes"] if isinstance(node, dict) and node.get("key")}

    for selected_node in selected_nodes:
        if not isinstance(selected_node, dict):
            blockers.append(
                readiness_item(
                    code="validation_gap",
                    status="failed",
                    message="Runtime admission selected node entry is malformed.",
                )
            )
            incomplete_codes.add("validation_gap")
            continue
        node_key = selected_node.get("node_key")
        node = nodes_by_key.get(node_key) if isinstance(node_key, str) else None
        if node is None:
            blockers.append(
                readiness_item(
                    code="missing_selected_node",
                    status="failed",
                    message="Runtime admission selected node is missing from the current task graph.",
                    details={"node_key": node_key},
                )
            )
            continue

        checks.append(
            readiness_item(
                code="selected_node_present",
                status="passed",
                message="Runtime admission selected node is present in the current task graph.",
                details={"node_key": node_key},
            )
        )
        runtime_task_type = selected_node.get("runtime_task_type") or node.get("intended_task_type")
        if not isinstance(runtime_task_type, str) or not runtime_task_type.strip():
            blockers.append(
                readiness_item(
                    code="missing_runtime_task_type",
                    status="failed",
                    message="Runtime admission selected node lacks a runtime task type.",
                    details={"node_key": node_key},
                )
            )
            continue
        checks.append(
            readiness_item(
                code="runtime_task_type_present",
                status="passed",
                message="Runtime admission selected node has a runtime task type.",
                details={"node_key": node_key, "runtime_task_type": runtime_task_type.strip()},
            )
        )

        capability_id, capability_name, capability_version = resolve_capability_for_readiness(
            selected_node=selected_node,
            graph_node=node,
            capability_repo=capability_repo,
            tenant_id=tenant_id_str,
            blockers=blockers,
            checks=checks,
        )
        validate_adapter_for_readiness(
            selected_node=selected_node,
            admitted_capability_id=capability_id,
            admitted_capability_name=capability_name,
            admitted_capability_version=capability_version,
            adapter_repo=adapter_repo,
            tenant_id=tenant_id_str,
            blockers=blockers,
            checks=checks,
        )

    validation_result = admission.get("validation_result") if isinstance(admission, dict) else None
    validation_gaps = validation_result.get("gaps") if isinstance(validation_result, dict) else None
    if validation_gaps:
        warning = readiness_item(
            code="validation_gap",
            status="warning",
            message="Runtime admission includes validation notes that should be reviewed before task materialization.",
            details={"gaps": validation_gaps},
        )
        warnings.append(warning)
        checks.append(warning)

    ready = not blockers
    readiness_status: RuntimeReadinessStatus = "ready" if ready else "blocked"
    if not ready and any(blocker.code in incomplete_codes for blocker in blockers):
        readiness_status = "incomplete"

    return RuntimeReadinessRead(
        mission_id=mission.id,
        tenant_id=mission.tenant_id,
        ready=ready,
        readiness_status=readiness_status,
        checked_at=checked_at,
        graph_reference=task_graph,
        materialization_reference=materialization,
        admission_reference=admission,
        selected_node_count=len(selected_nodes),
        checks=checks,
        blockers=blockers,
        warnings=warnings,
    )


def runtime_preview_authority_flags() -> dict[str, bool]:
    return projection_runtime_preview_authority_flags()


def build_runtime_task_preview_items(
    *, mission_id: UUID, readiness: RuntimeReadinessRead
) -> list[RuntimeTaskPreviewItem]:
    return [
        RuntimeTaskPreviewItem.model_validate(item)
        for item in project_runtime_task_preview_items(mission_id=mission_id, readiness=readiness)
    ]


def runtime_task_materialization_to_read(
    *,
    mission: Mission,
    metadata: dict[str, Any],
    blockers: list[RuntimeReadinessItem] | None = None,
    warnings: list[RuntimeReadinessItem] | None = None,
) -> RuntimeTaskMaterializationRead:
    raw_task_ids = metadata.get("created_execution_task_ids")
    created_task_ids = [UUID(str(task_id)) for task_id in raw_task_ids] if isinstance(raw_task_ids, list) else []
    raw_status = metadata.get("materialization_status")
    materialization_status: RuntimeTaskMaterializationStatus = (
        raw_status if raw_status in {"materialized", "blocked", "superseded"} else "blocked"
    )
    raw_authority = metadata.get("runtime_authority")
    runtime_authority: dict[str, bool] = (
        {str(key): bool(value) for key, value in raw_authority.items()}
        if isinstance(raw_authority, dict)
        else runtime_materialization_authority_flags()
    )
    return RuntimeTaskMaterializationRead(
        mission_id=mission.id,
        tenant_id=mission.tenant_id,
        materialization_status=materialization_status,
        materialization_version=(
            metadata.get("materialization_version")
            if isinstance(metadata.get("materialization_version"), int)
            else None
        ),
        created_execution_task_ids=created_task_ids,
        task_count=metadata.get("task_count", len(created_task_ids))
        if isinstance(metadata.get("task_count"), int)
        else len(created_task_ids),
        graph_reference=metadata.get("graph_reference") if isinstance(metadata.get("graph_reference"), dict) else None,
        materialization_reference=(
            metadata.get("materialization_reference")
            if isinstance(metadata.get("materialization_reference"), dict)
            else None
        ),
        admission_reference=metadata.get("admission_reference")
        if isinstance(metadata.get("admission_reference"), dict)
        else None,
        runtime_authority=runtime_authority,
        blockers=blockers or [],
        warnings=warnings or [],
        updated_at=str(metadata.get("updated_at") or mission.updated_at.isoformat()),
    )


def build_blocked_runtime_task_materialization_read(
    *, readiness: RuntimeReadinessRead, status: RuntimeTaskMaterializationStatus = "blocked"
) -> RuntimeTaskMaterializationRead:
    return RuntimeTaskMaterializationRead(
        mission_id=readiness.mission_id,
        tenant_id=readiness.tenant_id,
        materialization_status=status,
        materialization_version=None,
        created_execution_task_ids=[],
        task_count=0,
        graph_reference=readiness.graph_reference,
        materialization_reference=readiness.materialization_reference,
        admission_reference=readiness.admission_reference,
        runtime_authority=runtime_materialization_authority_flags(),
        blockers=readiness.blockers,
        warnings=readiness.warnings,
        updated_at=readiness.checked_at,
    )
