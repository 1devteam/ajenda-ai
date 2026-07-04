from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from backend.api.routes._authorization import require_route_permission
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.auth.permissions import Permission
from backend.services.light_crm.records import LightCrmRecordService
from backend.services.light_crm.schemas import PIPELINE_STAGES
from backend.services.light_crm.workflow import workflow_suggestions
from backend.services.tools.record_types import SUPPORTED_RECORD_TYPES

router = APIRouter(prefix="/crm", tags=["crm"])

CrmRecordType = Literal["account", "contact", "opportunity", "activity", "task"]


class CrmRecordItem(BaseModel):
    id: str
    record_type: str
    data: dict[str, Any]


class CrmRecordListResponse(BaseModel):
    record_type: str
    items: list[CrmRecordItem]
    total: int


class CrmTimelineResponse(BaseModel):
    record_type: str
    record_id: str
    items: list[dict[str, Any]]
    total: int


class CrmPipelineStage(BaseModel):
    stage: str
    count: int
    opportunities: list[dict[str, Any]]


class CrmPipelineResponse(BaseModel):
    stages: list[CrmPipelineStage]


class CrmSuggestion(BaseModel):
    suggestion_id: str
    reason: str
    mission_action: str
    title: str
    description: str
    related_type: str
    related_id: str


class CrmSuggestionsResponse(BaseModel):
    items: list[CrmSuggestion]


class CrmRecordWriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: dict[str, Any] = Field(default_factory=dict)


@router.get("/records", response_model=CrmRecordListResponse)
def list_records(
    request: Request,
    record_type: CrmRecordType = Query(...),
    query: str = Query(default=""),
    stage: str | None = Query(default=None),
    account_id: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=50),
    tenant_id: uuid.UUID = Depends(get_request_tenant_id),
    session: Session = Depends(get_tenant_db_session),
) -> CrmRecordListResponse:
    require_route_permission(
        request=request,
        db=session,
        permission=Permission.EXECUTION_VIEW,
        tenant_id=tenant_id,
    )
    if record_type not in SUPPORTED_RECORD_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="unsupported record_type")

    filters: dict[str, Any] = {}
    if stage:
        filters["stage"] = stage.strip().lower()
    if account_id:
        filters["account_id"] = account_id.strip()

    crm = LightCrmRecordService(session=session)
    rows = crm.list_records(
        tenant_id=str(tenant_id),
        record_type=record_type,
        query=query,
        filters=filters or None,
        limit=limit,
    )
    items = [
        CrmRecordItem(
            id=str(row.get("id") or ""),
            record_type=record_type,
            data=row,
        )
        for row in rows
        if row.get("id")
    ]
    return CrmRecordListResponse(record_type=record_type, items=items, total=len(items))


@router.get("/records/{record_type}/{record_id}", response_model=CrmRecordItem)
def get_record(
    record_type: CrmRecordType,
    record_id: str,
    request: Request,
    tenant_id: uuid.UUID = Depends(get_request_tenant_id),
    session: Session = Depends(get_tenant_db_session),
) -> CrmRecordItem:
    require_route_permission(
        request=request,
        db=session,
        permission=Permission.EXECUTION_VIEW,
        tenant_id=tenant_id,
    )
    crm = LightCrmRecordService(session=session)
    row = crm.read_record(tenant_id=str(tenant_id), record_type=record_type, record_id=record_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="record not found")
    return CrmRecordItem(id=str(row.get("id") or record_id), record_type=record_type, data=row)


@router.get("/records/{record_type}/{record_id}/timeline", response_model=CrmTimelineResponse)
def get_record_timeline(
    record_type: CrmRecordType,
    record_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
    tenant_id: uuid.UUID = Depends(get_request_tenant_id),
    session: Session = Depends(get_tenant_db_session),
) -> CrmTimelineResponse:
    require_route_permission(
        request=request,
        db=session,
        permission=Permission.EXECUTION_VIEW,
        tenant_id=tenant_id,
    )
    crm = LightCrmRecordService(session=session)
    items = crm.list_timeline(
        tenant_id=str(tenant_id),
        record_type=record_type,
        record_id=record_id,
        limit=limit,
    )
    return CrmTimelineResponse(
        record_type=record_type,
        record_id=record_id,
        items=items,
        total=len(items),
    )


@router.put("/records/{record_type}/{record_id}", response_model=CrmRecordItem)
def upsert_record(
    record_type: CrmRecordType,
    record_id: str,
    body: CrmRecordWriteRequest,
    request: Request,
    tenant_id: uuid.UUID = Depends(get_request_tenant_id),
    session: Session = Depends(get_tenant_db_session),
) -> CrmRecordItem:
    require_route_permission(
        request=request,
        db=session,
        permission=Permission.MISSION_MANAGE,
        tenant_id=tenant_id,
    )
    from backend.services.light_crm.workflow import complete_internal_crm_upsert

    payload = {**body.data, "id": record_id}
    saved = complete_internal_crm_upsert(
        session=session,
        tenant_id=str(tenant_id),
        record_type=record_type,
        data=payload,
        commit=True,
    )
    return CrmRecordItem(id=str(saved.get("id") or record_id), record_type=record_type, data=saved)


@router.get("/pipeline", response_model=CrmPipelineResponse)
def get_pipeline(
    request: Request,
    tenant_id: uuid.UUID = Depends(get_request_tenant_id),
    session: Session = Depends(get_tenant_db_session),
) -> CrmPipelineResponse:
    require_route_permission(
        request=request,
        db=session,
        permission=Permission.EXECUTION_VIEW,
        tenant_id=tenant_id,
    )
    crm = LightCrmRecordService(session=session)
    stages = crm.pipeline_summary(tenant_id=str(tenant_id))
    return CrmPipelineResponse(
        stages=[
            CrmPipelineStage(stage=item["stage"], count=item["count"], opportunities=item["opportunities"])
            for item in stages
        ]
    )


@router.get("/pipeline/stages")
def list_pipeline_stages() -> dict[str, list[str]]:
    return {"stages": list(PIPELINE_STAGES)}


@router.get("/suggestions", response_model=CrmSuggestionsResponse)
def list_workflow_suggestions(
    request: Request,
    tenant_id: uuid.UUID = Depends(get_request_tenant_id),
    session: Session = Depends(get_tenant_db_session),
) -> CrmSuggestionsResponse:
    require_route_permission(
        request=request,
        db=session,
        permission=Permission.EXECUTION_VIEW,
        tenant_id=tenant_id,
    )
    items = workflow_suggestions(session=session, tenant_id=str(tenant_id))
    return CrmSuggestionsResponse(items=[CrmSuggestion.model_validate(item) for item in items])
