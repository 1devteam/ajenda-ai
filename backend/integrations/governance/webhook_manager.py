"""
Webhook Manager - Outbound event notifications.

Sends webhook notifications for governance events, manages subscriptions,
retries failed deliveries, tracks delivery status.

Author: Dev Team Lead
Date: 2026-02-27
Built with Pride for Obex Blackvault
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from enum import Enum
import uuid
import hmac
import hashlib
import json
import asyncio
import aiohttp


# ============================================================================
# Enums
# ============================================================================

class WebhookEvent(Enum):
    """Types of webhook events."""
    POLICY_EVALUATED = "policy.evaluated"
    APPROVAL_REQUESTED = "approval.requested"
    APPROVAL_COMPLETED = "approval.completed"
    RISK_ASSESSED = "risk.assessed"
    COMPLIANCE_VIOLATED = "compliance.violated"
    AUDIT_EVENT = "audit.event"
    ALERT_TRIGGERED = "alert.triggered"
    ASSET_REGISTERED = "asset.registered"
    ASSET_UPDATED = "asset.updated"


class DeliveryStatus(Enum):
    """Status of webhook delivery."""
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    RETRYING = "retrying"


# ============================================================================
# Data Models
# ============================================================================

@dataclass
class WebhookSubscription:
    """
    Represents a webhook subscription.
    """
    subscription_id: str
    url: str
    events: List[str]  # Event types to subscribe to
    secret: str  # For signature verification
    active: bool
    created_at: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "subscription_id": self.subscription_id,
            "url": self.url,
            "events": self.events,
            "secret": "***",  # Don't expose secret
            "active": self.active,
            "created_at": self.created_at.isoformat(),
            "metadata": self.metadata,
        }


@dataclass
class WebhookDelivery:
    """
    Represents a webhook delivery attempt.
    """
    delivery_id: str
    subscription_id: str
    event_type: str
    payload: Dict[str, Any]
    status: DeliveryStatus
    attempts: int
    last_attempt: datetime
    response_code: Optional[int] = None
    response_body: Optional[str] = None
    next_retry: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "delivery_id": self.delivery_id,
            "subscription_id": self.subscription_id,
            "event_type": self.event_type,
            "status": self.status.value,
            "attempts": self.attempts,
            "last_attempt": self.last_attempt.isoformat(),
            "response_code": self.response_code,
            "response_body": self.response_body,
            "next_retry": self.next_retry.isoformat() if self.next_retry else None,
        }


# ============================================================================
# Webhook Manager
# ============================================================================

class WebhookManager:
    """
    Manages webhook subscriptions and deliveries.
    
    Sends webhook notifications, retries failures, tracks delivery status.
    Singleton pattern ensures consistent webhook handling.
    """
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._subscriptions: Dict[str, WebhookSubscription] = {}
        self._deliveries: Dict[str, WebhookDelivery] = {}
        self._max_retries = 3
        self._retry_delays = [60, 300, 900]  # 1min, 5min, 15min
        self._initialized = True
    
    def subscribe(
        self,
        url: str,
        events: List[str],
        secret: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> WebhookSubscription:
        """
        Create a webhook subscription.
        
        Args:
            url: Webhook URL
            events: List of event types to subscribe to
            secret: Secret for signature verification (auto-generated if not provided)
            metadata: Additional metadata
            
        Returns:
            Created subscription
        """
        subscription_id = f"sub-{uuid.uuid4()}"
        
        if not secret:
            secret = str(uuid.uuid4())
        
        subscription = WebhookSubscription(
            subscription_id=subscription_id,
            url=url,
            events=events,
            secret=secret,
            active=True,
            created_at=datetime.utcnow(),
            metadata=metadata or {},
        )
        
        self._subscriptions[subscription_id] = subscription
        return subscription
    
    def unsubscribe(self, subscription_id: str) -> bool:
        """
        Remove a webhook subscription.
        
        Args:
            subscription_id: Subscription ID
            
        Returns:
            True if removed
        """
        if subscription_id in self._subscriptions:
            del self._subscriptions[subscription_id]
            return True
        return False
    
    def get_subscription(self, subscription_id: str) -> Optional[WebhookSubscription]:
        """Get subscription by ID."""
        return self._subscriptions.get(subscription_id)
    
    def list_subscriptions(self, active_only: bool = True) -> List[WebhookSubscription]:
        """
        List webhook subscriptions.
        
        Args:
            active_only: Only return active subscriptions
            
        Returns:
            List of subscriptions
        """
        subs = list(self._subscriptions.values())
        if active_only:
            subs = [s for s in subs if s.active]
        return subs
    
    async def send_webhook(self, event_type: str, payload: Dict[str, Any]) -> List[str]:
        """
        Send webhook to all subscribers of an event type.
        
        Args:
            event_type: Event type
            payload: Event payload
            
        Returns:
            List of delivery IDs
        """
        # Find matching subscriptions
        matching_subs = [
            sub for sub in self._subscriptions.values()
            if sub.active and event_type in sub.events
        ]
        
        if not matching_subs:
            return []
        
        # Create deliveries
        delivery_ids = []
        for sub in matching_subs:
            delivery_id = f"delivery-{uuid.uuid4()}"
            
            delivery = WebhookDelivery(
                delivery_id=delivery_id,
                subscription_id=sub.subscription_id,
                event_type=event_type,
                payload=payload,
                status=DeliveryStatus.PENDING,
                attempts=0,
                last_attempt=datetime.utcnow(),
            )
            
            self._deliveries[delivery_id] = delivery
            delivery_ids.append(delivery_id)
            
            # Send webhook (async)
            asyncio.create_task(self._deliver_webhook(delivery_id))
        
        return delivery_ids
    
    async def _deliver_webhook(self, delivery_id: str) -> None:
        """
        Deliver a webhook.
        
        Args:
            delivery_id: Delivery ID
        """
        delivery = self._deliveries.get(delivery_id)
        if not delivery:
            return
        
        subscription = self._subscriptions.get(delivery.subscription_id)
        if not subscription:
            delivery.status = DeliveryStatus.FAILED
            return
        
        # Increment attempts
        delivery.attempts += 1
        delivery.last_attempt = datetime.utcnow()
        
        # Prepare payload
        webhook_payload = {
            "event_type": delivery.event_type,
            "timestamp": datetime.utcnow().isoformat(),
            "data": delivery.payload,
        }
        
        # Generate signature
        signature = self._generate_signature(webhook_payload, subscription.secret)
        
        # Send HTTP POST
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    subscription.url,
                    json=webhook_payload,
                    headers={
                        "Content-Type": "application/json",
                        "X-Webhook-Signature": signature,
                        "X-Webhook-Event": delivery.event_type,
                    },
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as response:
                    delivery.response_code = response.status
                    delivery.response_body = await response.text()
                    
                    if 200 <= response.status < 300:
                        delivery.status = DeliveryStatus.SUCCESS
                    else:
                        await self._handle_delivery_failure(delivery)
        
        except Exception as e:
            delivery.response_body = str(e)
            await self._handle_delivery_failure(delivery)
    
    async def _handle_delivery_failure(self, delivery: WebhookDelivery) -> None:
        """
        Handle webhook delivery failure.
        
        Args:
            delivery: Failed delivery
        """
        if delivery.attempts >= self._max_retries:
            delivery.status = DeliveryStatus.FAILED
        else:
            delivery.status = DeliveryStatus.RETRYING
            
            # Schedule retry
            delay_seconds = self._retry_delays[delivery.attempts - 1]
            delivery.next_retry = datetime.utcnow() + timedelta(seconds=delay_seconds)
            
            # Retry after delay
            await asyncio.sleep(delay_seconds)
            await self._deliver_webhook(delivery.delivery_id)
    
    def _generate_signature(self, payload: Dict[str, Any], secret: str) -> str:
        """
        Generate HMAC signature for webhook payload.
        
        Args:
            payload: Webhook payload
            secret: Subscription secret
            
        Returns:
            HMAC signature
        """
        payload_bytes = json.dumps(payload, sort_keys=True).encode()
        signature = hmac.new(
            secret.encode(),
            payload_bytes,
            hashlib.sha256,
        ).hexdigest()
        return f"sha256={signature}"
    
    def get_delivery(self, delivery_id: str) -> Optional[WebhookDelivery]:
        """Get delivery by ID."""
        return self._deliveries.get(delivery_id)
    
    def get_deliveries(
        self,
        subscription_id: Optional[str] = None,
        status: Optional[DeliveryStatus] = None,
        limit: int = 100,
    ) -> List[WebhookDelivery]:
        """
        List webhook deliveries.
        
        Args:
            subscription_id: Filter by subscription
            status: Filter by status
            limit: Maximum number of deliveries
            
        Returns:
            List of deliveries
        """
        deliveries = list(self._deliveries.values())
        
        if subscription_id:
            deliveries = [d for d in deliveries if d.subscription_id == subscription_id]
        if status:
            deliveries = [d for d in deliveries if d.status == status]
        
        deliveries.sort(key=lambda d: d.last_attempt, reverse=True)
        return deliveries[:limit]
    
    async def retry_failed(self) -> int:
        """
        Retry all failed deliveries.
        
        Returns:
            Number of deliveries retried
        """
        failed = [
            d for d in self._deliveries.values()
            if d.status == DeliveryStatus.FAILED and d.attempts < self._max_retries
        ]
        
        for delivery in failed:
            delivery.status = DeliveryStatus.RETRYING
            asyncio.create_task(self._deliver_webhook(delivery.delivery_id))
        
        return len(failed)
    
    async def test_webhook(self, subscription_id: str) -> bool:
        """
        Test a webhook subscription.
        
        Args:
            subscription_id: Subscription ID
            
        Returns:
            True if test successful
        """
        subscription = self._subscriptions.get(subscription_id)
        if not subscription:
            return False
        
        # Send test event
        test_payload = {
            "test": True,
            "subscription_id": subscription_id,
            "timestamp": datetime.utcnow().isoformat(),
        }
        
        delivery_ids = await self.send_webhook("test.event", test_payload)
        
        if not delivery_ids:
            return False
        
        # Wait for delivery
        await asyncio.sleep(2)
        
        delivery = self._deliveries.get(delivery_ids[0])
        return delivery and delivery.status == DeliveryStatus.SUCCESS
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get webhook statistics.
        
        Returns:
            Statistics about webhooks
        """
        deliveries = list(self._deliveries.values())
        
        by_status = {}
        for status in DeliveryStatus:
            by_status[status.value] = len([
                d for d in deliveries if d.status == status
            ])
        
        return {
            "total_subscriptions": len(self._subscriptions),
            "active_subscriptions": len([s for s in self._subscriptions.values() if s.active]),
            "total_deliveries": len(deliveries),
            "by_status": by_status,
            "success_rate": (
                by_status["success"] / len(deliveries) * 100
                if deliveries else 0
            ),
        }
    
    def clear(self) -> None:
        """Clear all subscriptions and deliveries (for testing)."""
        self._subscriptions.clear()
        self._deliveries.clear()


# ============================================================================
# Singleton Access
# ============================================================================

def get_webhook_manager() -> WebhookManager:
    """Get the singleton webhook manager instance."""
    return WebhookManager()
