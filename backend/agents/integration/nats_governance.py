"""
NATS Integration for Governance
Async message queue for governance operations

Built with Pride for Obex Blackvault
"""
import asyncio
import json
from typing import Optional, Dict, Any, Callable
from datetime import datetime
import nats
from nats.aio.client import Client as NATS
from nats.aio.msg import Msg

from backend.config.settings import settings


class GovernanceNATSClient:
    """
    NATS client for governance async operations
    
    Subjects:
    - governance.webhooks.{event_type} - Webhook delivery
    - governance.compliance.check - Compliance checks
    - governance.risk.recalculate - Risk recalculation
    - governance.alerts.{severity} - Alert notifications
    """
    
    # Subject prefixes
    SUBJECT_WEBHOOKS = "governance.webhooks."
    SUBJECT_COMPLIANCE = "governance.compliance.check"
    SUBJECT_RISK = "governance.risk.recalculate"
    SUBJECT_ALERTS = "governance.alerts."
    
    def __init__(self):
        """Initialize NATS client"""
        self.nc: Optional[NATS] = None
        self.subscriptions: Dict[str, Any] = {}
    
    async def connect(self) -> None:
        """
        Connect to NATS server
        
        Raises:
            Exception: If connection fails
        """
        if not settings.NATS_ENABLED:
            print("NATS disabled in settings")
            return
        
        self.nc = await nats.connect(
            servers=[settings.NATS_URL],
            name=settings.NATS_CLIENT_ID,
            max_reconnect_attempts=settings.NATS_MAX_RECONNECT_ATTEMPTS
        )
        
        print(f"Connected to NATS at {settings.NATS_URL}")
    
    async def disconnect(self) -> None:
        """Disconnect from NATS server"""
        if self.nc:
            await self.nc.drain()
            await self.nc.close()
            self.nc = None
            print("Disconnected from NATS")
    
    def _serialize(self, data: Dict[str, Any]) -> bytes:
        """
        Serialize data to JSON bytes
        
        Args:
            data: Data to serialize
            
        Returns:
            JSON bytes
        """
        return json.dumps(data).encode()
    
    def _deserialize(self, data: bytes) -> Dict[str, Any]:
        """
        Deserialize JSON bytes to dict
        
        Args:
            data: JSON bytes
            
        Returns:
            Deserialized dict
        """
        return json.loads(data.decode())
    
    # Publishing
    
    async def publish_webhook_event(
        self,
        event_type: str,
        webhook_id: str,
        payload: Dict[str, Any]
    ) -> None:
        """
        Publish webhook delivery event
        
        Args:
            event_type: Event type
            webhook_id: Webhook ID
            payload: Event payload
        """
        if not self.nc:
            return
        
        subject = f"{self.SUBJECT_WEBHOOKS}{event_type}"
        message = {
            "webhook_id": webhook_id,
            "event_type": event_type,
            "payload": payload,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        await self.nc.publish(subject, self._serialize(message))
    
    async def publish_compliance_check(
        self,
        asset_id: str,
        check_type: str,
        context: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Publish compliance check request
        
        Args:
            asset_id: Asset ID
            check_type: Type of compliance check
            context: Optional context data
        """
        if not self.nc:
            return
        
        message = {
            "asset_id": asset_id,
            "check_type": check_type,
            "context": context or {},
            "timestamp": datetime.utcnow().isoformat()
        }
        
        await self.nc.publish(self.SUBJECT_COMPLIANCE, self._serialize(message))
    
    async def publish_risk_recalculation(
        self,
        asset_id: str,
        reason: str,
        context: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Publish risk recalculation request
        
        Args:
            asset_id: Asset ID
            reason: Reason for recalculation
            context: Optional context data
        """
        if not self.nc:
            return
        
        message = {
            "asset_id": asset_id,
            "reason": reason,
            "context": context or {},
            "timestamp": datetime.utcnow().isoformat()
        }
        
        await self.nc.publish(self.SUBJECT_RISK, self._serialize(message))
    
    async def publish_alert(
        self,
        severity: str,
        title: str,
        description: str,
        asset_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Publish alert notification
        
        Args:
            severity: Alert severity (info, warning, error, critical)
            title: Alert title
            description: Alert description
            asset_id: Optional asset ID
            metadata: Optional metadata
        """
        if not self.nc:
            return
        
        subject = f"{self.SUBJECT_ALERTS}{severity}"
        message = {
            "severity": severity,
            "title": title,
            "description": description,
            "asset_id": asset_id,
            "metadata": metadata or {},
            "timestamp": datetime.utcnow().isoformat()
        }
        
        await self.nc.publish(subject, self._serialize(message))
    
    # Subscribing
    
    async def subscribe_webhook_events(
        self,
        handler: Callable[[Dict[str, Any]], None],
        event_type: Optional[str] = None
    ) -> None:
        """
        Subscribe to webhook events
        
        Args:
            handler: Async handler function
            event_type: Optional specific event type (or * for all)
        """
        if not self.nc:
            return
        
        subject = f"{self.SUBJECT_WEBHOOKS}{event_type or '*'}"
        
        async def message_handler(msg: Msg):
            data = self._deserialize(msg.data)
            await handler(data)
        
        sub = await self.nc.subscribe(subject, cb=message_handler)
        self.subscriptions[f"webhooks_{event_type or 'all'}"] = sub
        print(f"Subscribed to {subject}")
    
    async def subscribe_compliance_checks(
        self,
        handler: Callable[[Dict[str, Any]], None]
    ) -> None:
        """
        Subscribe to compliance check requests
        
        Args:
            handler: Async handler function
        """
        if not self.nc:
            return
        
        async def message_handler(msg: Msg):
            data = self._deserialize(msg.data)
            await handler(data)
        
        sub = await self.nc.subscribe(self.SUBJECT_COMPLIANCE, cb=message_handler)
        self.subscriptions["compliance"] = sub
        print(f"Subscribed to {self.SUBJECT_COMPLIANCE}")
    
    async def subscribe_risk_recalculations(
        self,
        handler: Callable[[Dict[str, Any]], None]
    ) -> None:
        """
        Subscribe to risk recalculation requests
        
        Args:
            handler: Async handler function
        """
        if not self.nc:
            return
        
        async def message_handler(msg: Msg):
            data = self._deserialize(msg.data)
            await handler(data)
        
        sub = await self.nc.subscribe(self.SUBJECT_RISK, cb=message_handler)
        self.subscriptions["risk"] = sub
        print(f"Subscribed to {self.SUBJECT_RISK}")
    
    async def subscribe_alerts(
        self,
        handler: Callable[[Dict[str, Any]], None],
        severity: Optional[str] = None
    ) -> None:
        """
        Subscribe to alert notifications
        
        Args:
            handler: Async handler function
            severity: Optional specific severity (or * for all)
        """
        if not self.nc:
            return
        
        subject = f"{self.SUBJECT_ALERTS}{severity or '*'}"
        
        async def message_handler(msg: Msg):
            data = self._deserialize(msg.data)
            await handler(data)
        
        sub = await self.nc.subscribe(subject, cb=message_handler)
        self.subscriptions[f"alerts_{severity or 'all'}"] = sub
        print(f"Subscribed to {subject}")
    
    async def unsubscribe_all(self) -> None:
        """Unsubscribe from all subjects"""
        for name, sub in self.subscriptions.items():
            await sub.unsubscribe()
            print(f"Unsubscribed from {name}")
        
        self.subscriptions.clear()
    
    def is_connected(self) -> bool:
        """
        Check if connected to NATS
        
        Returns:
            True if connected
        """
        return self.nc is not None and self.nc.is_connected


# Global NATS client instance
governance_nats = GovernanceNATSClient()


# Example handlers (to be implemented in actual services)

async def handle_webhook_event(data: Dict[str, Any]) -> None:
    """
    Handle webhook delivery event
    
    Args:
        data: Event data
    """
    webhook_id = data.get("webhook_id")
    event_type = data.get("event_type")
    payload = data.get("payload")
    
    print(f"Processing webhook {webhook_id} for event {event_type}")
    # TODO: Implement actual webhook delivery logic
    # - Fetch webhook from database
    # - Make HTTP POST request
    # - Handle retries
    # - Update delivery statistics


async def handle_compliance_check(data: Dict[str, Any]) -> None:
    """
    Handle compliance check request
    
    Args:
        data: Check request data
    """
    asset_id = data.get("asset_id")
    check_type = data.get("check_type")
    
    print(f"Running compliance check {check_type} for asset {asset_id}")
    # TODO: Implement actual compliance check logic
    # - Fetch asset from database
    # - Run compliance checks
    # - Store findings
    # - Trigger alerts if needed


async def handle_risk_recalculation(data: Dict[str, Any]) -> None:
    """
    Handle risk recalculation request
    
    Args:
        data: Recalculation request data
    """
    asset_id = data.get("asset_id")
    reason = data.get("reason")
    
    print(f"Recalculating risk for asset {asset_id} (reason: {reason})")
    # TODO: Implement actual risk recalculation logic
    # - Fetch asset from database
    # - Calculate risk score
    # - Update database
    # - Invalidate caches
    # - Trigger alerts if tier changed


async def handle_alert(data: Dict[str, Any]) -> None:
    """
    Handle alert notification
    
    Args:
        data: Alert data
    """
    severity = data.get("severity")
    title = data.get("title")
    
    print(f"Alert [{severity}]: {title}")
    # TODO: Implement actual alert handling logic
    # - Send to Slack/email/PagerDuty
    # - Store in alert history
    # - Trigger escalation if critical


# Startup/shutdown functions

async def start_governance_nats() -> None:
    """Start NATS client and subscribe to subjects"""
    await governance_nats.connect()
    
    # Subscribe to all subjects
    await governance_nats.subscribe_webhook_events(handle_webhook_event)
    await governance_nats.subscribe_compliance_checks(handle_compliance_check)
    await governance_nats.subscribe_risk_recalculations(handle_risk_recalculation)
    await governance_nats.subscribe_alerts(handle_alert)


async def stop_governance_nats() -> None:
    """Stop NATS client"""
    await governance_nats.unsubscribe_all()
    await governance_nats.disconnect()
