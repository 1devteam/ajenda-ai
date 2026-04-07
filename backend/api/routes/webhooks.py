"""Webhook endpoint management routes.

Route inventory:
  POST   /v1/webhooks/                              — Register a new endpoint
  GET    /v1/webhooks/                              — List all endpoints
  GET    /v1/webhooks/{endpoint_id}                 — Get a single endpoint
  DELETE /v1/webhooks/{endpoint_id}                 — Delete an endpoint
  GET    /v1/webhooks/{endpoint_id}/deliveries      — List delivery history

All routes require a valid X-Tenant-Id header and are gated behind the
'webhooks' feature flag (starter plan and above).

The signing secret is returned only on POST and never again. Tenants must
store it securely at registration time.
"""
from __future__ import annotations

import uuid as _uuid
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from backend.app.dependencies.db import get_db_session
from backend.services.quota_enforcement import FeatureNotAvailableError
from backend.services.webhook_dispatch import (
    WebhookDispatchService,
    WebhookNotFoundError,
    WebhookRegistrationError,
)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class RegisterWebhookRequest(BaseModel):
    """Request body for registering a new webhook endpoint."""

    url: str = Field(
        ...,
        description="HTTPS URL to deliver events to",
        examples=["https://example.com/webhooks/ajenda"],
    )
    event_types: list[str] = Field(
        ...,
        min_length=1,
        description=(
            "List of event types to subscribe to. "
            "Valid values: task.queued, task.running, task.completed, "
            "task.failed, task.dead_lettered, task.recovering, "
            "mission.completed, compliance.review_required"
        ),
        examples=[["task.completed", "task.failed"]],
    )

    @field_validator("event_types")
    @classmethod
    def validate_event_types(cls, v: list[str]) -> list[str]:
        valid = {
            "task.queued",
            "task.running",
            "task.completed",
            "task.failed",
            "task.dead_lettered",
            "task.recovering",
            "mission.completed",
            "compliance.review_required",
        }
        invalid = set(v) - valid
        if invalid:
            raise ValueError(
                f"Unknown event type(s): {sorted(invalid)}. "
                f"Valid types: {sorted(valid)}"
            )
        return list(set(v))  # deduplicate


class WebhookEndpointResponse(BaseModel):
    """Response schema for a webhook endpoint (no secret)."""

    id: str
    tenant_id: str
    url: str
    event_types: list[str]
    is_active: bool
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


class RegisterWebhookResponse(BaseModel):
    """Response schema for endpoint registration — includes the one-time secret."""

    id: str
    tenant_id: str
    url: str
    event_types: list[str]
    is_active: bool
    created_at: str
    updated_at: str
    # Shown exactly once — not stored in plaintext
    secret: str = Field(
        ...,
        description=(
            "HMAC-SHA256 signing secret. Store this securely — it will not be "
            "shown again. Use it to verify the X-Ajenda-Signature-256 header "
            "on incoming webhook deliveries."
        ),
    )


class WebhookDeliveryResponse(BaseModel):
    """Response schema for a delivery attempt record."""

    id: str
    endpoint_id: str
    event_type: str
    event_id: str
    status: str
    attempt_number: int
    http_status_code: int | None
    error_message: str | None
    attempted_at: str
    delivered_at: str | None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@router.post("/", response_model=RegisterWebhookResponse, status_code=201)
def register_webhook(
    body: RegisterWebhookRequest,
    tenant_id: str = Header(alias="X-Tenant-Id"),
    db: Session = Depends(get_db_session),
) -> RegisterWebhookResponse:
    """Register a new webhook endpoint.

    Returns the endpoint details including the one-time signing secret.
    The secret is shown exactly once — store it securely immediately.

    Requires the 'webhooks' feature (starter plan and above).
    """
    tenant_uuid = _uuid.UUID(tenant_id)
    service = WebhookDispatchService(db)

    try:
        endpoint, plaintext_secret = service.register_endpoint(
            tenant_id=tenant_uuid,
            url=body.url,
            event_types=body.event_types,
        )
    except FeatureNotAvailableError as exc:
        raise HTTPException(
            status_code=402,
            detail={
                "code": "FEATURE_NOT_AVAILABLE",
                "feature": exc.feature,
                "plan": exc.plan,
                "message": (
                    f"Webhooks are not available on the {exc.plan!r} plan. "
                    "Upgrade to Starter or above to use webhooks."
                ),
            },
        ) from exc
    except WebhookRegistrationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    db.commit()

    return RegisterWebhookResponse(
        id=str(endpoint.id),
        tenant_id=str(endpoint.tenant_id),
        url=endpoint.url,
        event_types=endpoint.event_types,
        is_active=endpoint.is_active,
        created_at=endpoint.created_at.isoformat(),
        updated_at=endpoint.updated_at.isoformat(),
        secret=plaintext_secret,
    )


@router.get("/", response_model=list[WebhookEndpointResponse])
def list_webhooks(
    tenant_id: str = Header(alias="X-Tenant-Id"),
    db: Session = Depends(get_db_session),
) -> list[WebhookEndpointResponse]:
    """List all registered webhook endpoints for the tenant."""
    tenant_uuid = _uuid.UUID(tenant_id)
    service = WebhookDispatchService(db)
    endpoints = service.list_endpoints(tenant_uuid)

    return [
        WebhookEndpointResponse(
            id=str(ep.id),
            tenant_id=str(ep.tenant_id),
            url=ep.url,
            event_types=ep.event_types,
            is_active=ep.is_active,
            created_at=ep.created_at.isoformat(),
            updated_at=ep.updated_at.isoformat(),
        )
        for ep in endpoints
    ]


@router.get("/{endpoint_id}", response_model=WebhookEndpointResponse)
def get_webhook(
    endpoint_id: UUID,
    tenant_id: str = Header(alias="X-Tenant-Id"),
    db: Session = Depends(get_db_session),
) -> WebhookEndpointResponse:
    """Get a single webhook endpoint by ID."""
    tenant_uuid = _uuid.UUID(tenant_id)
    service = WebhookDispatchService(db)

    try:
        endpoint = service.get_endpoint(endpoint_id, tenant_id=tenant_uuid)
    except WebhookNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return WebhookEndpointResponse(
        id=str(endpoint.id),
        tenant_id=str(endpoint.tenant_id),
        url=endpoint.url,
        event_types=endpoint.event_types,
        is_active=endpoint.is_active,
        created_at=endpoint.created_at.isoformat(),
        updated_at=endpoint.updated_at.isoformat(),
    )


@router.delete("/{endpoint_id}", status_code=204)
def delete_webhook(
    endpoint_id: UUID,
    tenant_id: str = Header(alias="X-Tenant-Id"),
    db: Session = Depends(get_db_session),
) -> None:
    """Delete a webhook endpoint.

    Delivery history is retained for audit purposes.
    """
    tenant_uuid = _uuid.UUID(tenant_id)
    service = WebhookDispatchService(db)

    try:
        service.delete_endpoint(endpoint_id, tenant_id=tenant_uuid)
    except WebhookNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    db.commit()


@router.get(
    "/{endpoint_id}/deliveries",
    response_model=list[WebhookDeliveryResponse],
)
def list_webhook_deliveries(
    endpoint_id: UUID,
    tenant_id: str = Header(alias="X-Tenant-Id"),
    db: Session = Depends(get_db_session),
) -> list[WebhookDeliveryResponse]:
    """List recent delivery attempts for a webhook endpoint.

    Returns the 50 most recent attempts, newest first.
    """
    from backend.repositories.webhook_repository import WebhookRepository

    tenant_uuid = _uuid.UUID(tenant_id)

    # Verify endpoint ownership before returning delivery data
    service = WebhookDispatchService(db)
    try:
        service.get_endpoint(endpoint_id, tenant_id=tenant_uuid)
    except WebhookNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    repo = WebhookRepository(db)
    deliveries = repo.list_deliveries_for_endpoint(
        endpoint_id, tenant_id=tenant_uuid, limit=50
    )

    return [
        WebhookDeliveryResponse(
            id=str(d.id),
            endpoint_id=str(d.endpoint_id),
            event_type=d.event_type,
            event_id=str(d.event_id),
            status=d.status,
            attempt_number=d.attempt_number,
            http_status_code=d.http_status_code,
            error_message=d.error_message,
            attempted_at=d.attempted_at.isoformat(),
            delivered_at=d.delivered_at.isoformat() if d.delivered_at else None,
        )
        for d in deliveries
    ]
