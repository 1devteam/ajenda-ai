from __future__ import annotations

import hashlib
import json
import logging
import uuid as _uuid
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from backend.api.routes._authorization import require_route_permission
from backend.api.routes.mission_contracts import (
    BridgeRuntimeAuthorityRead,
    GraphMaterializationRead,
    GraphMaterializationWrite,
    MissionQueueResponse,
    RuntimeAdmissionNodeSelection,
    RuntimeAdmissionRead,
    RuntimeAdmissionWrite,
    RuntimeQueueAdmissionResponse,
)
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.app.dependencies.services import get_queue_adapter
from backend.auth.permissions import Permission
from backend.domain.mission import (
    MISSION_GRAPH_MATERIALIZATION_METADATA_KEY,
    MISSION_INTAKE_METADATA_KEY,
    MISSION_RUNTIME_ADMISSION_METADATA_KEY,
    MISSION_RUNTIME_TASK_MATERIALIZATION_METADATA_KEY,
    MISSION_TASK_GRAPH_METADATA_KEY,
    MISSION_WORKER_CLAIM_ADMISSION_METADATA_KEY,
    MISSION_WORKER_RUN_ADMISSION_METADATA_KEY,
    MISSION_WORKER_START_ADMISSION_METADATA_KEY,
    Mission,
    build_graph_materialization_metadata,
    build_runtime_admission_metadata,
)
from backend.queue.base import QueueAdapter
from backend.repositories.capability_adapter_repository import CapabilityAdapterRepository
from backend.repositories.capability_repository import CapabilityRepository
from backend.repositories.execution_task_repository import ExecutionTaskRepository
from backend.repositories.mission_repository import MissionRepository
from backend.repositories.outcome_review_repository import OutcomeReviewRepository
from backend.services.execution_coordinator import ExecutionCoordinator
from backend.services.mission_bridge import read_models as _mission_bridge_read_models
from backend.services.mission_bridge.materialization import (
    build_mission_runtime_readiness as _build_mission_runtime_readiness,
)
from backend.services.mission_bridge.materialization import (
    build_runtime_task_preview_items as _build_runtime_task_preview_items,
)
from backend.services.mission_bridge.materialization import (
    runtime_preview_authority_flags as _runtime_preview_authority_flags,
)
from backend.services.mission_bridge.materialization import (
    runtime_task_materialization_to_read as _runtime_task_materialization_to_read,
)
from backend.services.mission_bridge.worker_claim import (
    build_runtime_dispatch_readiness as _build_runtime_dispatch_readiness,
)
from backend.services.mission_bridge.worker_claim import (
    build_worker_claim_preview as _build_worker_claim_preview,
)
from backend.services.mission_bridge.worker_claim import (
    build_worker_dispatch_eligibility as _build_worker_dispatch_eligibility,
)
from backend.services.mission_bridge.worker_claim import (
    missing_worker_claim_admission as _missing_worker_claim_admission,
)
from backend.services.mission_bridge.worker_claim import (
    worker_claim_admission_to_read as _worker_claim_admission_to_read,
)
from backend.services.mission_bridge.worker_run import (
    missing_worker_run_admission as _missing_worker_run_admission,
)
from backend.services.mission_bridge.worker_run import (
    worker_run_admission_to_read as _worker_run_admission_to_read,
)
from backend.services.mission_bridge.worker_start import (
    missing_worker_start_admission as _missing_worker_start_admission,
)
from backend.services.mission_bridge.worker_start import (
    worker_start_admission_to_read as _worker_start_admission_to_read,
)
from backend.services.mission_bridge_runtime_authority import provision_bridge_runtime_authority
from backend.services.mission_graph_integrity import evaluate_admission_integrity
from backend.services.mission_runtime_projection import supersede_runtime_task_materialization
from backend.services.mission_runtime_queue_admission_service import MissionRuntimeQueueAdmissionService
from backend.services.mission_runtime_task_materialization_service import MissionRuntimeTaskMaterializationService
from backend.services.quota_enforcement import QuotaEnforcementService

RuntimeReadinessStatus = _mission_bridge_read_models.RuntimeReadinessStatus
RuntimeReadinessCheckStatus = _mission_bridge_read_models.RuntimeReadinessCheckStatus
RuntimeReadinessItem = _mission_bridge_read_models.RuntimeReadinessItem
RuntimeReadinessRead = _mission_bridge_read_models.RuntimeReadinessRead
RuntimeTaskPreviewStatus = _mission_bridge_read_models.RuntimeTaskPreviewStatus
RuntimeTaskPreviewPayload = _mission_bridge_read_models.RuntimeTaskPreviewPayload
RuntimeTaskPreviewItem = _mission_bridge_read_models.RuntimeTaskPreviewItem
RuntimeTaskPreviewRead = _mission_bridge_read_models.RuntimeTaskPreviewRead
RuntimeTaskMaterializationStatus = _mission_bridge_read_models.RuntimeTaskMaterializationStatus
RuntimeDispatchReadinessStatus = _mission_bridge_read_models.RuntimeDispatchReadinessStatus
WorkerDispatchEligibilityStatus = _mission_bridge_read_models.WorkerDispatchEligibilityStatus
WorkerClaimPreviewStatus = _mission_bridge_read_models.WorkerClaimPreviewStatus
WorkerClaimAdmissionStatus = _mission_bridge_read_models.WorkerClaimAdmissionStatus
WorkerStartAdmissionStatus = _mission_bridge_read_models.WorkerStartAdmissionStatus
WorkerRunAdmissionStatus = _mission_bridge_read_models.WorkerRunAdmissionStatus
RuntimeTaskMaterializationRead = _mission_bridge_read_models.RuntimeTaskMaterializationRead
RuntimeDispatchAuthority = _mission_bridge_read_models.RuntimeDispatchAuthority
RuntimeDispatchReadinessRead = _mission_bridge_read_models.RuntimeDispatchReadinessRead
WorkerDispatchAuthority = _mission_bridge_read_models.WorkerDispatchAuthority
WorkerClaimAuthority = _mission_bridge_read_models.WorkerClaimAuthority
WorkerDispatchEligibilityRead = _mission_bridge_read_models.WorkerDispatchEligibilityRead
WorkerClaimPreviewEnvelope = _mission_bridge_read_models.WorkerClaimPreviewEnvelope
WorkerClaimPreviewRead = _mission_bridge_read_models.WorkerClaimPreviewRead
WorkerClaimReceipt = _mission_bridge_read_models.WorkerClaimReceipt
WorkerClaimAdmissionRead = _mission_bridge_read_models.WorkerClaimAdmissionRead
WorkerStartAuthority = _mission_bridge_read_models.WorkerStartAuthority
WorkerRunAuthority = _mission_bridge_read_models.WorkerRunAuthority
WorkerStartReceipt = _mission_bridge_read_models.WorkerStartReceipt
WorkerStartAdmissionRead = _mission_bridge_read_models.WorkerStartAdmissionRead
WorkerRunReceipt = _mission_bridge_read_models.WorkerRunReceipt
WorkerRunAdmissionRead = _mission_bridge_read_models.WorkerRunAdmissionRead

__all__ = [
    "CapabilityAdapterRepository",
    "CapabilityRepository",
    "ExecutionCoordinator",
    "MissionRuntimeQueueAdmissionService",
    "MissionRuntimeTaskMaterializationService",
    "evaluate_admission_integrity",
    "provision_bridge_runtime_authority",
]

router = APIRouter()
logger = logging.getLogger("ajenda.mission_runtime_routes")


_CLIENT_FORGED_ADMISSION_IDENTITIES = frozenset(
    {
        "mission-dispatch-ui",
        "mission_dispatch_ui",
        "dispatch-ui-v1",
        "mission-bridge-ui",
        "mission-dispatch",
    }
)


def _server_admitted_by(*, request: Request, body_admitted_by: str | None) -> str:
    """Prefer authenticated principal; never accept browser UI forged identities as authority."""
    principal = getattr(request.state, "principal", None)
    if principal is not None:
        for attr in ("subject_id", "subject", "sub"):
            value = getattr(principal, attr, None)
            if isinstance(value, str) and value.strip():
                return value.strip()
    candidate = (body_admitted_by or "").strip()
    if candidate and candidate.lower() not in _CLIENT_FORGED_ADMISSION_IDENTITIES:
        return candidate
    return "server:runtime_admission"


def _task_graph_fingerprint(
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


def _fingerprint_existing_task_graph(task_graph: dict[str, Any]) -> str | None:
    nodes = task_graph.get("nodes")
    edges = task_graph.get("edges")
    mission_id = task_graph.get("mission_id")
    if not isinstance(nodes, list) or not isinstance(edges, list) or not isinstance(mission_id, str):
        return None
    if not all(isinstance(node, dict) for node in nodes) or not all(isinstance(edge, dict) for edge in edges):
        return None
    return _task_graph_fingerprint(
        mission_id=mission_id,
        graph_status=task_graph.get("graph_status") if isinstance(task_graph.get("graph_status"), str) else None,
        nodes=nodes,
        edges=edges,
        operator_notes=task_graph.get("operator_notes") if isinstance(task_graph.get("operator_notes"), str) else None,
    )


def _supersede_runtime_admission_for_materialization(
    *,
    metadata: dict[str, Any],
    materialization_version: int,
    updated_at: str,
) -> None:
    admission = metadata.get(MISSION_RUNTIME_ADMISSION_METADATA_KEY)
    if not isinstance(admission, dict):
        return
    superseded = dict(admission)
    superseded["admission_status"] = "superseded"
    superseded["updated_at"] = updated_at
    superseded["superseded_at"] = updated_at
    superseded["superseded_reason"] = "graph_materialization_replaced"
    superseded["superseded_by_materialization_version"] = materialization_version
    metadata[MISSION_RUNTIME_ADMISSION_METADATA_KEY] = superseded


def _runtime_admission_to_read(mission: Mission) -> RuntimeAdmissionRead:
    return RuntimeAdmissionRead(
        mission_id=mission.id,
        tenant_id=mission.tenant_id,
        runtime_admission=mission.metadata_json.get(MISSION_RUNTIME_ADMISSION_METADATA_KEY, {}),
        updated_at=mission.updated_at.isoformat(),
    )


def _cancel_superseded_materialized_planned_tasks(
    *, metadata: dict[str, Any], task_repo: ExecutionTaskRepository, tenant_id: str, mission_id: UUID
) -> list[str]:
    """Cancel planned ExecutionTask rows referenced by active runtime task materialization metadata."""
    task_materialization = metadata.get(MISSION_RUNTIME_TASK_MATERIALIZATION_METADATA_KEY)
    if not isinstance(task_materialization, dict):
        return []
    raw_task_ids = task_materialization.get("created_execution_task_ids")
    if not isinstance(raw_task_ids, list):
        return []
    task_ids: list[UUID] = []
    for raw_task_id in raw_task_ids:
        try:
            task_ids.append(UUID(str(raw_task_id)))
        except ValueError:
            continue
    cancelled_tasks = task_repo.cancel_planned_by_ids_for_mission(
        tenant_id=tenant_id, mission_id=mission_id, task_ids=task_ids
    )
    return [str(task.id) for task in cancelled_tasks]


def _graph_materialization_to_read(mission: Mission) -> GraphMaterializationRead:
    return GraphMaterializationRead(
        mission_id=mission.id,
        tenant_id=mission.tenant_id,
        materialization=mission.metadata_json.get(MISSION_GRAPH_MATERIALIZATION_METADATA_KEY, {}),
        updated_at=mission.updated_at.isoformat(),
    )


@router.post("/{mission_id}/materialize-graph", response_model=GraphMaterializationRead)
def materialize_mission_graph(
    mission_id: UUID,
    body: dict[str, Any] | None,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> GraphMaterializationRead:
    """Persist planner-to-graph materialization metadata without runtime work."""
    require_route_permission(request=request, db=db, permission=Permission.MISSION_MANAGE, tenant_id=tenant_id)
    tenant_id_str = str(tenant_id)
    repo = MissionRepository(db)
    mission = repo.get_for_tenant(mission_id=mission_id, tenant_id=tenant_id_str)
    if mission is None:
        raise HTTPException(status_code=404, detail="mission not found for tenant")

    metadata = dict(mission.metadata_json or {})
    task_graph = metadata.get(MISSION_TASK_GRAPH_METADATA_KEY)
    if not isinstance(task_graph, dict):
        raise HTTPException(status_code=400, detail="mission task graph is required before materialization")

    graph_nodes = task_graph.get("nodes")
    if not isinstance(graph_nodes, list):
        raise HTTPException(status_code=400, detail="mission task graph nodes are required before materialization")
    node_keys = {node.get("key") for node in graph_nodes if isinstance(node, dict)}
    if len(node_keys) != len(graph_nodes) or any(not isinstance(key, str) or not key for key in node_keys):
        raise HTTPException(status_code=400, detail="mission task graph nodes must have valid keys")

    # The UI may request server-owned materialization with an empty body.  Build
    # provenance from the persisted graph rather than requiring the client to
    # manufacture authority metadata.
    if not body:
        graph_metadata = task_graph.get("metadata")
        if not isinstance(graph_metadata, dict) or graph_metadata.get("generated_by") != "mission_composition_engine":
            raise HTTPException(
                status_code=409,
                detail="empty materialization requests require a server-composed task graph",
            )
        proposal_id = graph_metadata.get("proposal_id")
        if not isinstance(proposal_id, str) or not proposal_id.strip():
            raise HTTPException(
                status_code=409,
                detail="server-composed task graph is missing proposal provenance",
            )
        now = datetime.now(UTC).isoformat()
        graph_fingerprint = str(task_graph.get("graph_fingerprint") or "")
        body = {
            "materialization_status": "validated",
            "materialization_source": "mission_composition_confirmed",
            "materialization_source_version": "1",
            "planner_provenance": {
                "planner_type": "mission_composition_engine",
                "planner_id": "mission_composition_engine",
                "planning_run_id": proposal_id,
                "plan_schema_version": 1,
            },
            "graph_validation_result": {
                "validation_status": "valid",
                "summary": "Server validated persisted composition graph structure.",
                "validated_at": now,
                "checks": [
                    {"name": "node_keys", "status": "passed", "details": f"nodes={len(graph_nodes)}"},
                    {"name": "server_owned", "status": "passed", "details": "metadata generated by API"},
                ],
            },
            "graph_generation_metadata": {
                "generator": "mission_composition_engine",
                "generation_mode": "deterministic",
                "generated_at": now,
                "compiler_version": "1",
                "source_plan_version": "1",
                "deterministic_inputs": {"graph_fingerprint": graph_fingerprint},
            },
            "deterministic_compilation_metadata": {
                "compiler_name": "mission_composition_engine",
                "compiler_version": "1",
                "compilation_boundary": "confirmed_composition_to_materialized_graph",
                "input_fingerprint": graph_fingerprint or None,
                "output_fingerprint": graph_fingerprint or None,
                "deterministic": True,
            },
        }
    try:
        body_model = GraphMaterializationWrite.model_validate(body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    capability_repo = CapabilityRepository(db)
    for selection in body_model.capability_selection_provenance:
        if selection.node_key not in node_keys:
            raise HTTPException(
                status_code=400, detail=f"capability selection references missing node: {selection.node_key}"
            )
        if selection.capability_id is not None:
            capability = capability_repo.get_visible_for_tenant(
                capability_id=selection.capability_id, tenant_id=tenant_id_str
            )
            if capability is None:
                raise HTTPException(
                    status_code=400, detail=f"capability not found for tenant: {selection.capability_id}"
                )

    previous = metadata.get(MISSION_GRAPH_MATERIALIZATION_METADATA_KEY)
    previous_version = previous.get("materialization_version", 0) if isinstance(previous, dict) else 0
    now = datetime.now(UTC).isoformat()

    # Trust boundary: client may not self-certify graph validation as "valid".
    # Accept structural node-key checks server-side; never store client-forged validity.
    materialization_status = body_model.materialization_status
    validation = body_model.graph_validation_result.model_dump(mode="json", exclude_none=True)
    client_sources = {"mission_dispatch_ui", "mission-dispatch-ui", "dispatch-ui-v1"}
    source = body_model.materialization_source.strip().lower()
    if source in client_sources or source.startswith("mission_dispatch") or source.startswith("mission-dispatch"):
        if materialization_status == "validated":
            materialization_status = "draft"
        if validation.get("validation_status") == "valid":
            validation = {
                "validation_status": "not_run",
                "summary": (
                    "Client claimed validation was discarded; "
                    "server structural node-key checks ran at materialize-graph."
                ),
                "checks": [
                    {
                        "name": "node_keys",
                        "status": "passed",
                        "details": "Server verified node keys are unique non-empty strings.",
                    }
                ],
            }

    materialization_metadata = build_graph_materialization_metadata(
        mission_id=str(mission_id),
        materialization_status=materialization_status,
        materialization_source=body_model.materialization_source,
        materialization_source_version=body_model.materialization_source_version,
        materialization_version=previous_version + 1,
        planner_provenance=body_model.planner_provenance.model_dump(mode="json", exclude_none=True),
        capability_selection_provenance=[
            selection.model_dump(mode="json", exclude_none=True)
            for selection in body_model.capability_selection_provenance
        ],
        graph_validation_result=validation,
        operator_review=body_model.operator_review.model_dump(mode="json", exclude_none=True),
        graph_generation_metadata=body_model.graph_generation_metadata.model_dump(mode="json", exclude_none=True),
        deterministic_compilation_metadata=body_model.deterministic_compilation_metadata.model_dump(
            mode="json", exclude_none=True
        ),
        generation_notes=body_model.generation_notes,
        materialized_at=previous.get("materialized_at", now) if isinstance(previous, dict) else now,
        updated_at=now,
        graph_reference={
            "metadata_key": MISSION_TASK_GRAPH_METADATA_KEY,
            "schema_version": task_graph.get("schema_version"),
            "graph_status": task_graph.get("graph_status"),
            "graph_version": task_graph.get("graph_version"),
            "graph_fingerprint": task_graph.get("graph_fingerprint") or _fingerprint_existing_task_graph(task_graph),
            "node_count": len(graph_nodes),
            "edge_count": len(task_graph.get("edges", [])) if isinstance(task_graph.get("edges", []), list) else 0,
        },
    )
    if isinstance(metadata.get(MISSION_RUNTIME_ADMISSION_METADATA_KEY), dict):
        _supersede_runtime_admission_for_materialization(
            metadata=metadata,
            materialization_version=previous_version + 1,
            updated_at=now,
        )
    cancelled_task_ids: list[str] = []
    if isinstance(metadata.get(MISSION_RUNTIME_TASK_MATERIALIZATION_METADATA_KEY), dict):
        cancelled_task_ids = _cancel_superseded_materialized_planned_tasks(
            metadata=metadata,
            task_repo=ExecutionTaskRepository(db),
            tenant_id=tenant_id_str,
            mission_id=mission_id,
        )
    supersede_runtime_task_materialization(
        metadata=metadata,
        reason="graph_materialization_replaced",
        updated_at=now,
        supersession={
            "superseded_by_materialization_version": previous_version + 1,
            "cancelled_execution_task_ids": cancelled_task_ids,
        },
    )
    metadata.update(materialization_metadata)
    mission = repo.update_metadata(mission=mission, metadata_json=metadata)
    return _graph_materialization_to_read(mission)


@router.get("/{mission_id}/materialization", response_model=GraphMaterializationRead)
def read_mission_graph_materialization(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> GraphMaterializationRead:
    """Read tenant-scoped planner-to-graph materialization metadata."""
    mission = MissionRepository(db).get_for_tenant(mission_id=mission_id, tenant_id=str(tenant_id))
    if mission is None:
        raise HTTPException(status_code=404, detail="mission not found for tenant")
    if MISSION_GRAPH_MATERIALIZATION_METADATA_KEY not in (mission.metadata_json or {}):
        raise HTTPException(status_code=404, detail="mission graph materialization not found")
    return _graph_materialization_to_read(mission)


@router.post("/{mission_id}/runtime-admission", response_model=RuntimeAdmissionRead)
def admit_mission_graph_to_runtime(
    mission_id: UUID,
    body: RuntimeAdmissionWrite,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> RuntimeAdmissionRead:
    """Persist graph-to-runtime admission metadata without queueing or dispatch.

    Server owns admission identity and can derive selected nodes from the compiled graph.
    """
    require_route_permission(request=request, db=db, permission=Permission.RUNTIME_OPERATE, tenant_id=tenant_id)
    tenant_id_str = str(tenant_id)
    repo = MissionRepository(db)
    mission = repo.get_for_tenant(mission_id=mission_id, tenant_id=tenant_id_str)
    if mission is None:
        raise HTTPException(status_code=404, detail="mission not found for tenant")

    metadata = dict(mission.metadata_json or {})
    task_graph = metadata.get(MISSION_TASK_GRAPH_METADATA_KEY)
    if not isinstance(task_graph, dict):
        raise HTTPException(status_code=400, detail="mission task graph is required before runtime admission")

    materialization = metadata.get(MISSION_GRAPH_MATERIALIZATION_METADATA_KEY)
    if not isinstance(materialization, dict):
        raise HTTPException(
            status_code=400, detail="mission graph materialization is required before runtime admission"
        )

    if materialization.get("materialization_status") == "superseded":
        raise HTTPException(status_code=400, detail="superseded graph materialization cannot be admitted")

    graph_nodes = task_graph.get("nodes")
    if not isinstance(graph_nodes, list) or not all(isinstance(node, dict) for node in graph_nodes):
        raise HTTPException(status_code=400, detail="mission task graph nodes are required before runtime admission")
    nodes_by_key = {node.get("key"): node for node in graph_nodes if isinstance(node.get("key"), str)}
    if len(nodes_by_key) != len(graph_nodes):
        raise HTTPException(status_code=400, detail="mission task graph nodes must have valid keys")

    graph_version = task_graph.get("graph_version")
    graph_fingerprint = task_graph.get("graph_fingerprint") or _fingerprint_existing_task_graph(task_graph)
    graph_reference = materialization.get("graph_reference")
    if not isinstance(graph_reference, dict):
        raise HTTPException(
            status_code=400, detail="materialization graph reference is required before runtime admission"
        )
    if (
        graph_reference.get("graph_version") != graph_version
        or graph_reference.get("graph_fingerprint") != graph_fingerprint
    ):
        raise HTTPException(status_code=400, detail="materialization graph reference does not match current task graph")

    outcome_reviews = OutcomeReviewRepository(db).list_for_mission(mission_id=mission_id, tenant_id=tenant_id_str)
    rejected_reviews = [
        review
        for review in outcome_reviews
        if review.review_status == "rejected" or review.review_decision == "rejected"
    ]
    if rejected_reviews:
        raise HTTPException(status_code=400, detail="rejected outcome review blocks runtime admission")

    intake_for_graft = metadata.get(MISSION_INTAKE_METADATA_KEY)
    intake_context = intake_for_graft.get("context") if isinstance(intake_for_graft, dict) else None
    composition_for_graft = intake_context.get("composition") if isinstance(intake_context, dict) else None
    compiled_instruction = (
        composition_for_graft.get("instruction")
        if isinstance(composition_for_graft, dict) and isinstance(composition_for_graft.get("instruction"), str)
        else None
    )
    # Mission objective is the server-normalized instruction.  The stored
    # composition instruction preserves the raw operator text for provenance
    # and may still contain harmless Markdown quote prefixes; feeding that raw
    # copy to GRAFT would reject a mission that already compiled successfully.
    graft_instruction = (mission.objective or compiled_instruction or "").strip()
    graft_report = evaluate_admission_integrity(
        session=db,
        tenant_id=tenant_id_str,
        instruction=graft_instruction,
        task_graph=task_graph,
    )
    if graft_report["status"] != "clear":
        raise HTTPException(
            status_code=400,
            detail={"message": "GRAFT runtime admission blocked", "graft": graft_report},
        )

    admitted_by = _server_admitted_by(request=request, body_admitted_by=body.admitted_by)
    node_selections = list(body.selected_nodes)
    if not node_selections:
        if not body.auto_provision_authority:
            raise HTTPException(
                status_code=400,
                detail="selected_nodes required when auto_provision_authority is false",
            )
        provisioned = provision_bridge_runtime_authority(
            db=db,
            mission_id=mission_id,
            tenant_id=tenant_id,
            admitted_by=admitted_by,
        )
        # Graph may have been rewritten with capability ids; re-read mission metadata snapshot.
        mission = repo.get_for_tenant(mission_id=mission_id, tenant_id=tenant_id_str) or mission
        metadata = dict(mission.metadata_json or {})
        task_graph = metadata.get(MISSION_TASK_GRAPH_METADATA_KEY) or task_graph
        graph_nodes = task_graph.get("nodes") if isinstance(task_graph, dict) else graph_nodes
        if not isinstance(graph_nodes, list):
            raise HTTPException(
                status_code=400, detail="mission task graph nodes are required before runtime admission"
            )
        nodes_by_key = {
            node.get("key"): node for node in graph_nodes if isinstance(node, dict) and isinstance(node.get("key"), str)
        }
        authority_by_key = {
            item["node_key"]: item
            for item in provisioned.get("node_authorities", [])
            if isinstance(item, dict) and isinstance(item.get("node_key"), str)
        }
        for node_key, authority in authority_by_key.items():
            if node_key not in nodes_by_key:
                continue
            try:
                provisioned_capability_id = UUID(str(authority["capability_id"]))
                provisioned_adapter_id = UUID(str(authority["adapter_id"]))
            except (KeyError, ValueError, TypeError) as exc:
                raise HTTPException(
                    status_code=400,
                    detail=f"bridge authority missing capability/adapter for node: {node_key}",
                ) from exc
            node_selections.append(
                RuntimeAdmissionNodeSelection(
                    node_key=node_key,
                    runtime_task_type="tool.invoke",
                    capability_id=provisioned_capability_id,
                    adapter_id=provisioned_adapter_id,
                    operator_notes="Server-derived admission from compiled graph.",
                )
            )
        if not node_selections:
            raise HTTPException(
                status_code=400,
                detail="no runtime-admissible tool.invoke nodes found on compiled task graph",
            )

    capability_repo = CapabilityRepository(db)
    adapter_repo = CapabilityAdapterRepository(db)
    selections_by_node = {
        selection.get("node_key"): selection
        for selection in materialization.get("capability_selection_provenance", [])
        if isinstance(selection, dict) and isinstance(selection.get("node_key"), str)
    }

    validation_checks: list[dict[str, str]] = []
    selected_nodes: list[dict[str, Any]] = []
    for selection in node_selections:
        node = nodes_by_key.get(selection.node_key)
        if node is None:
            raise HTTPException(
                status_code=400, detail=f"runtime admission references missing node: {selection.node_key}"
            )

        runtime_task_type = selection.runtime_task_type or node.get("intended_task_type")
        if not isinstance(runtime_task_type, str) or not runtime_task_type.strip():
            raise HTTPException(
                status_code=400, detail=f"runtime admission node lacks runtime task type: {selection.node_key}"
            )
        runtime_task_type = runtime_task_type.strip()

        node_capability_refs = (
            node.get("capability_references") if isinstance(node.get("capability_references"), list) else []
        )
        materialized_selection = selections_by_node.get(selection.node_key)
        capability_id = selection.capability_id
        materialized_capability_id: UUID | None = None
        if isinstance(materialized_selection, dict):
            raw_materialized_capability_id = materialized_selection.get("capability_id")
            if isinstance(raw_materialized_capability_id, str):
                try:
                    materialized_capability_id = UUID(raw_materialized_capability_id)
                except ValueError as exc:
                    raise HTTPException(
                        status_code=400,
                        detail=f"materialization capability_id is invalid for node: {selection.node_key}",
                    ) from exc

        if (
            capability_id is not None
            and materialized_capability_id is not None
            and capability_id != materialized_capability_id
        ):
            raise HTTPException(
                status_code=400,
                detail=f"runtime admission capability conflicts with materialization: {selection.node_key}",
            )

        if capability_id is None and materialized_capability_id is not None:
            capability_id = materialized_capability_id

        if capability_id is None:
            for capability_ref in node_capability_refs:
                if isinstance(capability_ref, dict) and isinstance(capability_ref.get("capability_id"), str):
                    try:
                        capability_id = UUID(capability_ref["capability_id"])
                    except ValueError as exc:
                        raise HTTPException(
                            status_code=400,
                            detail=f"task graph capability_id is invalid for node: {selection.node_key}",
                        ) from exc
                    break

        if capability_id is None and not node_capability_refs:
            raise HTTPException(
                status_code=400, detail=f"runtime admission node lacks capability reference: {selection.node_key}"
            )
        if capability_id is not None:
            capability = capability_repo.get_visible_for_tenant(capability_id=capability_id, tenant_id=tenant_id_str)
            if capability is None:
                raise HTTPException(status_code=400, detail=f"capability not found for tenant: {capability_id}")
        else:
            visible_capability_found = False
            for capability_ref in node_capability_refs:
                if not isinstance(capability_ref, dict):
                    continue
                capability_name = capability_ref.get("name")
                capability_version = capability_ref.get("version")
                if not isinstance(capability_name, str) or not capability_name.strip():
                    continue
                if not isinstance(capability_version, str) or not capability_version.strip():
                    continue

                capability = capability_repo.get_conflict_for_scope(
                    name=capability_name.strip(),
                    version=capability_version.strip(),
                    tenant_id=tenant_id_str,
                )
                if capability is None:
                    capability = capability_repo.get_conflict_for_scope(
                        name=capability_name.strip(),
                        version=capability_version.strip(),
                        tenant_id=None,
                    )
                if capability is not None:
                    visible_capability_found = True
                    break

            if not visible_capability_found:
                raise HTTPException(
                    status_code=400,
                    detail=f"runtime admission node lacks visible capability reference: {selection.node_key}",
                )

        adapter_id = selection.adapter_id
        if adapter_id is not None:
            adapter = adapter_repo.get_visible_for_tenant(adapter_id=adapter_id, tenant_id=tenant_id_str)
            if adapter is None:
                raise HTTPException(status_code=400, detail=f"capability adapter not found for tenant: {adapter_id}")

        validation_checks.append({"name": f"node:{selection.node_key}", "status": "passed"})
        selected_nodes.append(
            {
                "node_key": selection.node_key,
                "runtime_task_type": runtime_task_type,
                "capability_id": str(capability_id) if capability_id is not None else None,
                "adapter_id": str(adapter_id) if adapter_id is not None else None,
                "graph_node_reference": {
                    "key": node.get("key"),
                    "name": node.get("name"),
                    "intended_task_type": node.get("intended_task_type"),
                },
                "materialization_selection_reference": materialized_selection,
                "operator_notes": selection.operator_notes,
            }
        )

    previous = metadata.get(MISSION_RUNTIME_ADMISSION_METADATA_KEY)
    previous_version = previous.get("admission_version", 0) if isinstance(previous, dict) else 0
    now = datetime.now(UTC).isoformat()
    validation_notes = list(body.validation_notes)
    if not body.selected_nodes:
        validation_notes = [
            *validation_notes,
            "Server-derived selected_nodes from compiled task graph + bridge authority.",
        ]
    runtime_admission_metadata = build_runtime_admission_metadata(
        mission_id=str(mission_id),
        admission_status=body.admission_status,
        admission_version=previous_version + 1,
        admitted_by=admitted_by,
        admitted_at=(
            previous.get("admitted_at", now)
            if isinstance(previous, dict) and previous.get("admission_status") != "superseded"
            else now
        ),
        updated_at=now,
        graph_reference={
            "metadata_key": MISSION_TASK_GRAPH_METADATA_KEY,
            "schema_version": task_graph.get("schema_version") if isinstance(task_graph, dict) else None,
            "graph_status": task_graph.get("graph_status") if isinstance(task_graph, dict) else None,
            "graph_version": graph_version,
            "graph_fingerprint": graph_fingerprint,
            "node_count": len(graph_nodes) if isinstance(graph_nodes, list) else 0,
        },
        materialization_reference={
            "metadata_key": MISSION_GRAPH_MATERIALIZATION_METADATA_KEY,
            "schema_version": materialization.get("schema_version"),
            "materialization_status": materialization.get("materialization_status"),
            "materialization_version": materialization.get("materialization_version"),
            "graph_reference": graph_reference,
        },
        selected_nodes=selected_nodes,
        validation_result={
            "validation_status": "valid",
            "summary": (
                "Runtime admission metadata validated; queue admission and worker dispatch are recorded separately."
            ),
            "validated_at": now,
            "checks": validation_checks,
            "gaps": validation_notes,
        },
        execution_task_records=[],
        runtime_authority={
            "creates_execution_tasks": False,
            "enqueues_work": False,
            "dispatches_workers": False,
            "requires_explicit_queue_admission_for_execution": True,
        },
    )
    cancelled_task_ids: list[str] = []
    if isinstance(metadata.get(MISSION_RUNTIME_TASK_MATERIALIZATION_METADATA_KEY), dict):
        cancelled_task_ids = _cancel_superseded_materialized_planned_tasks(
            metadata=metadata,
            task_repo=ExecutionTaskRepository(db),
            tenant_id=tenant_id_str,
            mission_id=mission_id,
        )
    metadata.update(runtime_admission_metadata)
    supersede_runtime_task_materialization(
        metadata=metadata,
        reason="runtime_admission_replaced",
        updated_at=now,
        supersession={
            "superseded_by_admission_version": previous_version + 1,
            "cancelled_execution_task_ids": cancelled_task_ids,
        },
    )
    mission = repo.update_metadata(mission=mission, metadata_json=metadata)
    return _runtime_admission_to_read(mission)


@router.get("/{mission_id}/runtime-readiness", response_model=RuntimeReadinessRead)
def read_mission_runtime_readiness(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> RuntimeReadinessRead:
    """Validate read-only runtime admission readiness without runtime authority."""
    return _build_mission_runtime_readiness(
        mission_id=mission_id,
        tenant_id=tenant_id,
        db=db,
        mission_repository_cls=MissionRepository,
        capability_repository_cls=CapabilityRepository,
        capability_adapter_repository_cls=CapabilityAdapterRepository,
        outcome_review_repository_cls=OutcomeReviewRepository,
    )


@router.get("/{mission_id}/runtime-task-preview", response_model=RuntimeTaskPreviewRead)
def read_mission_runtime_task_preview(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> RuntimeTaskPreviewRead:
    """Preview future ExecutionTask materialization without creating or queueing work."""
    readiness = _build_mission_runtime_readiness(
        mission_id=mission_id,
        tenant_id=tenant_id,
        db=db,
        mission_repository_cls=MissionRepository,
        capability_repository_cls=CapabilityRepository,
        capability_adapter_repository_cls=CapabilityAdapterRepository,
        outcome_review_repository_cls=OutcomeReviewRepository,
    )
    tasks = _build_runtime_task_preview_items(mission_id=mission_id, readiness=readiness) if readiness.ready else []
    preview_status: RuntimeTaskPreviewStatus = readiness.readiness_status
    if readiness.ready and len(tasks) != readiness.selected_node_count:
        preview_status = "incomplete"
    readiness_summary = {
        "readiness_status": readiness.readiness_status,
        "selected_node_count": readiness.selected_node_count,
        "check_count": len(readiness.checks),
        "blocker_count": len(readiness.blockers),
        "warning_count": len(readiness.warnings),
    }
    return RuntimeTaskPreviewRead(
        mission_id=readiness.mission_id,
        tenant_id=readiness.tenant_id,
        ready=readiness.ready and preview_status == "ready",
        preview_status=preview_status,
        checked_at=readiness.checked_at,
        readiness_summary=readiness_summary,
        task_count=len(tasks),
        tasks=tasks,
        blockers=readiness.blockers,
        warnings=readiness.warnings,
        runtime_authority=_runtime_preview_authority_flags(),
    )


@router.get("/{mission_id}/runtime-task-materialization", response_model=RuntimeTaskMaterializationRead)
def read_mission_runtime_task_materialization(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> RuntimeTaskMaterializationRead:
    """Read tenant-scoped ExecutionTask materialization metadata."""
    mission = MissionRepository(db).get_for_tenant(mission_id=mission_id, tenant_id=str(tenant_id))
    if mission is None:
        raise HTTPException(status_code=404, detail="mission not found for tenant")
    materialization = (mission.metadata_json or {}).get(MISSION_RUNTIME_TASK_MATERIALIZATION_METADATA_KEY)
    if not isinstance(materialization, dict):
        raise HTTPException(status_code=404, detail="mission runtime task materialization not found")
    return _runtime_task_materialization_to_read(mission=mission, metadata=materialization)


@router.post("/{mission_id}/runtime-task-materialization", response_model=RuntimeTaskMaterializationRead)
def materialize_mission_runtime_tasks(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> RuntimeTaskMaterializationRead:
    """Create planned ExecutionTask rows from a ready admitted mission graph without queueing work."""
    require_route_permission(request=request, db=db, permission=Permission.RUNTIME_OPERATE, tenant_id=tenant_id)
    return cast(
        RuntimeTaskMaterializationRead,
        MissionRuntimeTaskMaterializationService(
            db,
            mission_repository_cls=MissionRepository,
            execution_task_repository_cls=ExecutionTaskRepository,
            capability_repository_cls=CapabilityRepository,
            capability_adapter_repository_cls=CapabilityAdapterRepository,
            outcome_review_repository_cls=OutcomeReviewRepository,
        ).materialize(mission_id=mission_id, tenant_id=tenant_id),
    )


@router.get("/{mission_id}/runtime-dispatch-readiness", response_model=RuntimeDispatchReadinessRead)
def read_mission_runtime_dispatch_readiness(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> RuntimeDispatchReadinessRead:
    """Read queued materialized task readiness without dispatching workers."""
    return _build_runtime_dispatch_readiness(
        mission_id=mission_id,
        tenant_id=tenant_id,
        db=db,
        mission_repository_cls=MissionRepository,
        execution_task_repository_cls=ExecutionTaskRepository,
    )


@router.get("/{mission_id}/worker-dispatch-eligibility", response_model=WorkerDispatchEligibilityRead)
def read_mission_worker_dispatch_eligibility(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> WorkerDispatchEligibilityRead:
    """Read worker dispatch eligibility without claiming leases or mutating runtime state."""
    return _build_worker_dispatch_eligibility(
        mission_id=mission_id,
        tenant_id=tenant_id,
        db=db,
        mission_repository_cls=MissionRepository,
        execution_task_repository_cls=ExecutionTaskRepository,
    )


@router.get("/{mission_id}/worker-claim-preview", response_model=WorkerClaimPreviewRead)
def read_mission_worker_claim_preview(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> WorkerClaimPreviewRead:
    """Preview future worker claim envelopes without claiming or dispatching work."""
    return _build_worker_claim_preview(
        mission_id=mission_id,
        tenant_id=tenant_id,
        db=db,
        mission_repository_cls=MissionRepository,
        execution_task_repository_cls=ExecutionTaskRepository,
    )


@router.post("/{mission_id}/worker-claim-admission", response_model=WorkerClaimAdmissionRead)
def worker_claim_admission(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> WorkerClaimAdmissionRead:
    """Deprecated: daemon workers exclusively own queue claim authority."""
    require_route_permission(request=request, db=db, permission=Permission.RUNTIME_OPERATE, tenant_id=tenant_id)
    raise HTTPException(
        status_code=410,
        detail="HTTP worker claim admission was removed; queued work is claimed by the daemon worker.",
    )


@router.get("/{mission_id}/worker-claim-admission", response_model=WorkerClaimAdmissionRead)
def read_mission_worker_claim_admission(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> WorkerClaimAdmissionRead:
    """Read latest worker claim admission metadata without mutating runtime state."""
    tenant_id_str = str(tenant_id)
    mission = MissionRepository(db).get_for_tenant(mission_id=mission_id, tenant_id=tenant_id_str)
    if mission is None:
        raise HTTPException(status_code=404, detail="mission not found for tenant")
    metadata = mission.metadata_json if isinstance(mission.metadata_json, dict) else {}
    admission = metadata.get(MISSION_WORKER_CLAIM_ADMISSION_METADATA_KEY)
    if not isinstance(admission, dict):
        return _missing_worker_claim_admission(mission_id=mission_id, tenant_id=tenant_id_str)
    return _worker_claim_admission_to_read(
        mission_id=mission_id, tenant_id=tenant_id_str, admission=admission, read_only=True
    )


@router.post("/{mission_id}/worker-start-admission", response_model=WorkerStartAdmissionRead)
def worker_start_admission(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> WorkerStartAdmissionRead:
    """Deprecated: daemon workers exclusively own execution start authority."""
    require_route_permission(request=request, db=db, permission=Permission.RUNTIME_OPERATE, tenant_id=tenant_id)
    raise HTTPException(
        status_code=410,
        detail="HTTP worker start admission was removed; claimed work is started by the daemon worker.",
    )


@router.get("/{mission_id}/worker-start-admission", response_model=WorkerStartAdmissionRead)
def read_mission_worker_start_admission(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> WorkerStartAdmissionRead:
    """Read latest worker execution start admission metadata without mutating runtime state."""
    tenant_id_str = str(tenant_id)
    mission = MissionRepository(db).get_for_tenant(mission_id=mission_id, tenant_id=tenant_id_str)
    if mission is None:
        raise HTTPException(status_code=404, detail="mission not found for tenant")
    metadata = mission.metadata_json if isinstance(mission.metadata_json, dict) else {}
    admission = metadata.get(MISSION_WORKER_START_ADMISSION_METADATA_KEY)
    if not isinstance(admission, dict):
        return _missing_worker_start_admission(mission_id=mission_id, tenant_id=tenant_id_str)
    return _worker_start_admission_to_read(
        mission_id=mission_id, tenant_id=tenant_id_str, admission=admission, read_only=True
    )


@router.post("/{mission_id}/worker-run-admission", response_model=WorkerRunAdmissionRead)
def worker_run_admission(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> WorkerRunAdmissionRead:
    """Deprecated: daemon workers exclusively own dispatcher execution authority."""
    require_route_permission(request=request, db=db, permission=Permission.RUNTIME_OPERATE, tenant_id=tenant_id)
    raise HTTPException(
        status_code=410,
        detail="HTTP worker run admission was removed; running work is dispatched by the daemon worker.",
    )


@router.get("/{mission_id}/worker-run-admission", response_model=WorkerRunAdmissionRead)
def read_mission_worker_run_admission(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> WorkerRunAdmissionRead:
    """Read latest worker run admission metadata without mutating runtime state."""
    tenant_id_str = str(tenant_id)
    mission = MissionRepository(db).get_for_tenant(mission_id=mission_id, tenant_id=tenant_id_str)
    if mission is None:
        raise HTTPException(status_code=404, detail="mission not found for tenant")
    metadata = mission.metadata_json if isinstance(mission.metadata_json, dict) else {}
    admission = metadata.get(MISSION_WORKER_RUN_ADMISSION_METADATA_KEY)
    if not isinstance(admission, dict):
        return _missing_worker_run_admission(mission_id=mission_id, tenant_id=tenant_id_str)
    return _worker_run_admission_to_read(
        mission_id=mission_id, tenant_id=tenant_id_str, admission=admission, read_only=True
    )


@router.post("/{mission_id}/runtime-queue-admission", response_model=RuntimeQueueAdmissionResponse)
def runtime_queue_admission(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
    queue: QueueAdapter = Depends(get_queue_adapter),
) -> dict[str, object]:
    """Queue eligible planned tasks from the current runtime task materialization."""
    require_route_permission(request=request, db=db, permission=Permission.EXECUTION_QUEUE, tenant_id=tenant_id)
    return _admit_mission_runtime_queue(
        mission_id=mission_id,
        tenant_id=tenant_id,
        db=db,
        queue=queue,
    )


def _admit_mission_runtime_queue(
    *, mission_id: UUID, tenant_id: _uuid.UUID, db: Session, queue: QueueAdapter
) -> dict[str, object]:
    """Invoke the single canonical mission runtime queue-admission authority."""

    return MissionRuntimeQueueAdmissionService(
        db,
        queue,
        mission_repository_cls=MissionRepository,
        execution_task_repository_cls=ExecutionTaskRepository,
        quota_enforcement_service_cls=QuotaEnforcementService,
        execution_coordinator_cls=ExecutionCoordinator,
    ).admit(mission_id=mission_id, tenant_id=tenant_id)


@router.get("/{mission_id}/runtime-admission", response_model=RuntimeAdmissionRead)
def read_mission_runtime_admission(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> RuntimeAdmissionRead:
    """Read tenant-scoped graph-to-runtime admission metadata."""
    mission = MissionRepository(db).get_for_tenant(mission_id=mission_id, tenant_id=str(tenant_id))
    if mission is None:
        raise HTTPException(status_code=404, detail="mission not found for tenant")
    if MISSION_RUNTIME_ADMISSION_METADATA_KEY not in (mission.metadata_json or {}):
        raise HTTPException(status_code=404, detail="mission runtime admission not found")
    return _runtime_admission_to_read(mission)


@router.post("/{mission_id}/bridge-runtime-authority", response_model=BridgeRuntimeAuthorityRead)
def provision_mission_bridge_runtime_authority(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> BridgeRuntimeAuthorityRead:
    """Provision tenant-scoped capability/adapter authority for mission bridge tool.invoke nodes."""
    require_route_permission(request=request, db=db, permission=Permission.MISSION_MANAGE, tenant_id=tenant_id)
    principal = getattr(request.state, "principal", None)
    admitted_by = str(getattr(principal, "subject_id", "mission-bridge-ui")).strip() or "mission-bridge-ui"
    result = provision_bridge_runtime_authority(
        db=db,
        mission_id=mission_id,
        tenant_id=tenant_id,
        admitted_by=admitted_by,
    )
    return BridgeRuntimeAuthorityRead.model_validate(result)


@router.post(
    "/{mission_id}/queue",
    response_model=MissionQueueResponse,
    deprecated=True,
    summary="[Legacy] Compatibility wrapper for runtime queue admission",
)
def queue_mission(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
    queue: QueueAdapter = Depends(get_queue_adapter),
) -> dict[str, object]:
    """Delegate to canonical runtime queue admission and project the legacy response."""
    logger.info(
        "legacy_mission_queue_route_used",
        extra={"mission_id": str(mission_id), "tenant_id": str(tenant_id), "legacy_route": "missions.queue"},
    )
    require_route_permission(request=request, db=db, permission=Permission.EXECUTION_QUEUE, tenant_id=tenant_id)
    admission = _admit_mission_runtime_queue(
        mission_id=mission_id,
        tenant_id=tenant_id,
        db=db,
        queue=queue,
    )
    return {
        "queued_task_ids": admission["queued_task_ids"],
        "pending_review_task_ids": admission["pending_review_task_ids"],
        "denied_tasks": admission["denied_tasks"],
    }
