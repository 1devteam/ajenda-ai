"""
Integration API - REST endpoints for webhooks, API keys, and event streaming.

Provides 20 endpoints for managing external integrations.

Author: Dev Team Lead
Date: 2026-02-27
Built with Pride for Obex Blackvault
"""

from fastapi import (
    APIRouter,
    HTTPException,
    Header,
    Query,
    WebSocket,
    WebSocketDisconnect,
)
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime

from backend.integrations.governance.webhook_manager import (
    get_webhook_manager,
)
from backend.integrations.governance.api_gateway import (
    get_api_gateway,
    get_event_streaming,
    StreamType,
)


router = APIRouter(prefix="/api/v1/integrations", tags=["integrations"])


# ============================================================================
# Request/Response Models
# ============================================================================


class WebhookSubscriptionRequest(BaseModel):
    """Request to create webhook subscription."""

    url: str = Field(..., description="Webhook URL")
    events: List[str] = Field(..., description="Event types to subscribe to")
    secret: Optional[str] = Field(None, description="Secret for signature verification")


class WebhookSubscriptionResponse(BaseModel):
    """Webhook subscription response."""

    subscription_id: str
    url: str
    events: List[str]
    active: bool
    created_at: str


class WebhookDeliveryResponse(BaseModel):
    """Webhook delivery response."""

    delivery_id: str
    subscription_id: str
    event_type: str
    status: str
    attempts: int
    last_attempt: str
    response_code: Optional[int]
    next_retry: Optional[str]


class APIKeyRequest(BaseModel):
    """Request to create API key."""

    name: str = Field(..., description="Key name")
    organization: str = Field(..., description="Organization name")
    permissions: List[str] = Field(..., description="Permission scopes")
    rate_limit: int = Field(100, description="Requests per minute")
    expires_in_days: Optional[int] = Field(None, description="Expiration in days")


class APIKeyResponse(BaseModel):
    """API key response."""

    key_id: str
    key: Optional[str] = None  # Only returned on creation
    name: str
    organization: str
    permissions: List[str]
    rate_limit: int
    active: bool
    created_at: str
    expires_at: Optional[str]


class StreamSubscriptionRequest(BaseModel):
    """Request to subscribe to event stream."""

    stream_type: str = Field(..., description="Stream type")
    filters: Optional[Dict[str, Any]] = Field(None, description="Optional filters")


# ============================================================================
# Webhook Endpoints (7)
# ============================================================================


@router.post("/webhooks/subscribe", response_model=WebhookSubscriptionResponse)
async def subscribe_webhook(request: WebhookSubscriptionRequest):
    """
    Subscribe to webhook events.

    Creates a webhook subscription for specified event types.
    """
    manager = get_webhook_manager()

    subscription = manager.subscribe(
        url=request.url,
        events=request.events,
        secret=request.secret,
    )

    return WebhookSubscriptionResponse(**subscription.to_dict())


@router.delete("/webhooks/{subscription_id}")
async def unsubscribe_webhook(subscription_id: str):
    """
    Unsubscribe from webhook events.

    Removes a webhook subscription.
    """
    manager = get_webhook_manager()
    success = manager.unsubscribe(subscription_id)

    if not success:
        raise HTTPException(status_code=404, detail=f"Subscription {subscription_id} not found")

    return {"status": "unsubscribed", "subscription_id": subscription_id}


@router.get("/webhooks", response_model=List[WebhookSubscriptionResponse])
async def list_webhooks(active_only: bool = Query(True, description="Only active subscriptions")):
    """
    List webhook subscriptions.

    Returns all webhook subscriptions.
    """
    manager = get_webhook_manager()
    subscriptions = manager.list_subscriptions(active_only=active_only)

    return [WebhookSubscriptionResponse(**s.to_dict()) for s in subscriptions]


@router.get("/webhooks/{subscription_id}", response_model=WebhookSubscriptionResponse)
async def get_webhook(subscription_id: str):
    """
    Get webhook subscription by ID.

    Returns detailed information about a webhook subscription.
    """
    manager = get_webhook_manager()
    subscription = manager.get_subscription(subscription_id)

    if not subscription:
        raise HTTPException(status_code=404, detail=f"Subscription {subscription_id} not found")

    return WebhookSubscriptionResponse(**subscription.to_dict())


@router.get(
    "/webhooks/{subscription_id}/deliveries",
    response_model=List[WebhookDeliveryResponse],
)
async def get_webhook_deliveries(subscription_id: str):
    """
    Get webhook delivery history.

    Returns all delivery attempts for a subscription.
    """
    manager = get_webhook_manager()
    deliveries = manager.get_deliveries(subscription_id=subscription_id)

    return [WebhookDeliveryResponse(**d.to_dict()) for d in deliveries]


@router.post("/webhooks/{subscription_id}/test")
async def test_webhook(subscription_id: str):
    """
    Test a webhook subscription.

    Sends a test event to verify webhook is working.
    """
    manager = get_webhook_manager()
    success = await manager.test_webhook(subscription_id)

    if not success:
        raise HTTPException(
            status_code=404,
            detail=f"Subscription {subscription_id} not found or test failed",
        )

    return {"status": "test_sent", "subscription_id": subscription_id}


@router.post("/webhooks/retry-failed")
async def retry_failed_webhooks():
    """
    Retry all failed webhook deliveries.

    Retries all deliveries that failed but haven't exceeded max retries.
    """
    manager = get_webhook_manager()
    count = await manager.retry_failed()

    return {"status": "retrying", "count": count}


# ============================================================================
# API Gateway Endpoints (7)
# ============================================================================


@router.post("/api-keys", response_model=APIKeyResponse)
async def create_api_key(request: APIKeyRequest):
    """
    Create an API key.

    Generates a new API key for external access.
    """
    gateway = get_api_gateway()

    raw_key, api_key = gateway.create_api_key(
        name=request.name,
        organization=request.organization,
        permissions=request.permissions,
        rate_limit=request.rate_limit,
        expires_in_days=request.expires_in_days,
    )

    response = APIKeyResponse(**api_key.to_dict())
    response.key = raw_key  # Only returned on creation

    return response


@router.delete("/api-keys/{key_id}")
async def revoke_api_key(key_id: str):
    """
    Revoke an API key.

    Deactivates an API key.
    """
    gateway = get_api_gateway()
    success = gateway.revoke_api_key(key_id)

    if not success:
        raise HTTPException(status_code=404, detail=f"API key {key_id} not found")

    return {"status": "revoked", "key_id": key_id}


@router.get("/api-keys", response_model=List[APIKeyResponse])
async def list_api_keys(active_only: bool = Query(True, description="Only active keys")):
    """
    List API keys.

    Returns all API keys.
    """
    gateway = get_api_gateway()
    keys = gateway.list_api_keys(active_only=active_only)

    return [APIKeyResponse(**k.to_dict()) for k in keys]


@router.get("/api-keys/{key_id}", response_model=APIKeyResponse)
async def get_api_key(key_id: str):
    """
    Get API key by ID.

    Returns detailed information about an API key.
    """
    gateway = get_api_gateway()
    api_key = gateway.get_api_key(key_id)

    if not api_key:
        raise HTTPException(status_code=404, detail=f"API key {key_id} not found")

    return APIKeyResponse(**api_key.to_dict())


@router.get("/api-keys/{key_id}/usage")
async def get_api_key_usage(key_id: str):
    """
    Get API key usage statistics.

    Returns usage metrics for an API key.
    """
    gateway = get_api_gateway()
    api_key = gateway.get_api_key(key_id)

    if not api_key:
        raise HTTPException(status_code=404, detail=f"API key {key_id} not found")

    stats = gateway.get_usage_stats(key_id)

    return {
        "key_id": key_id,
        "statistics": stats,
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.post("/api-keys/{key_id}/validate")
async def validate_api_key(
    key_id: str,
    x_api_key: str = Header(..., description="API key to validate"),
):
    """
    Validate an API key.

    Checks if an API key is valid and active.
    """
    gateway = get_api_gateway()
    api_key = gateway.validate_api_key(x_api_key)

    if not api_key or api_key.key_id != key_id:
        raise HTTPException(status_code=401, detail="Invalid API key")

    return {
        "valid": True,
        "key_id": api_key.key_id,
        "organization": api_key.organization,
        "permissions": api_key.permissions,
    }


@router.get("/api-keys/{key_id}/rate-limit")
async def check_rate_limit(key_id: str):
    """
    Check rate limit status.

    Returns current rate limit status for an API key.
    """
    gateway = get_api_gateway()
    within_limit = gateway.check_rate_limit(key_id)

    api_key = gateway.get_api_key(key_id)
    if not api_key:
        raise HTTPException(status_code=404, detail=f"API key {key_id} not found")

    return {
        "key_id": key_id,
        "within_limit": within_limit,
        "rate_limit": api_key.rate_limit,
        "timestamp": datetime.utcnow().isoformat(),
    }


# ============================================================================
# Event Streaming Endpoints (6)
# ============================================================================


@router.websocket("/stream")
async def websocket_stream(websocket: WebSocket):
    """
    WebSocket endpoint for real-time event streaming.

    Clients connect and subscribe to event streams.
    """
    await websocket.accept()
    streaming = get_event_streaming()

    connection_id = f"conn-{datetime.utcnow().timestamp()}"
    subscriptions = []

    try:
        while True:
            # Receive subscription request
            data = await websocket.receive_json()

            if data.get("action") == "subscribe":
                stream_type = StreamType(data["stream_type"])
                filters = data.get("filters", {})

                subscription = streaming.subscribe(
                    connection_id=connection_id,
                    stream_type=stream_type,
                    filters=filters,
                )
                subscriptions.append(subscription)

                await websocket.send_json(
                    {
                        "type": "subscribed",
                        "subscription_id": subscription.subscription_id,
                        "stream_type": stream_type.value,
                    }
                )

                # Send recent events
                recent = streaming.get_recent_events(stream_type, limit=10)
                for event in recent:
                    await websocket.send_json(
                        {
                            "type": "event",
                            "subscription_id": subscription.subscription_id,
                            **event.to_dict(),
                        }
                    )

            elif data.get("action") == "unsubscribe":
                subscription_id = data["subscription_id"]
                streaming.unsubscribe(subscription_id)
                subscriptions = [s for s in subscriptions if s.subscription_id != subscription_id]

                await websocket.send_json(
                    {
                        "type": "unsubscribed",
                        "subscription_id": subscription_id,
                    }
                )

            elif data.get("action") == "ping":
                # Keep-alive
                for sub in subscriptions:
                    streaming.update_activity(sub.subscription_id)

                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        # Clean up subscriptions
        for sub in subscriptions:
            streaming.unsubscribe(sub.subscription_id)


@router.get("/stream/subscriptions")
async def get_stream_subscriptions():
    """
    Get active stream subscriptions.

    Returns all active event stream subscriptions.
    """
    streaming = get_event_streaming()
    subscriptions = streaming.get_active_subscriptions()

    return {
        "subscription_count": len(subscriptions),
        "subscriptions": [s.to_dict() for s in subscriptions],
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/stream/{stream_type}/recent")
async def get_recent_stream_events(
    stream_type: str,
    limit: int = Query(10, ge=1, le=100, description="Maximum number of events"),
):
    """
    Get recent events from a stream.

    Returns recent events without subscribing to the stream.
    """
    try:
        stream_type_enum = StreamType(stream_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid stream type: {stream_type}")

    streaming = get_event_streaming()
    events = streaming.get_recent_events(stream_type_enum, limit=limit)

    return {
        "stream_type": stream_type,
        "event_count": len(events),
        "events": [e.to_dict() for e in events],
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.post("/stream/{stream_type}/publish")
async def publish_stream_event(
    stream_type: str,
    data: Dict[str, Any],
):
    """
    Publish an event to a stream.

    Manually publish an event to a stream (for testing/integration).
    """
    try:
        stream_type_enum = StreamType(stream_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid stream type: {stream_type}")

    streaming = get_event_streaming()
    event = streaming.publish(stream_type_enum, data)

    return {
        "status": "published",
        **event.to_dict(),
    }


@router.get("/stream/statistics")
async def get_stream_statistics():
    """
    Get streaming statistics.

    Returns metrics about event streams and subscriptions.
    """
    streaming = get_event_streaming()
    stats = streaming.get_statistics()

    return {
        **stats,
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/stream/types")
async def get_stream_types():
    """
    Get available stream types.

    Returns list of available event stream types.
    """
    return {
        "stream_types": [st.value for st in StreamType],
        "timestamp": datetime.utcnow().isoformat(),
    }
