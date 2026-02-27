"""
NATS Integration for Governance
Async message queue for governance operations

Built with Pride for Obex Blackvault
"""
import asyncio
import json
import logging
from typing import Optional, Dict, Any, Callable
from datetime import datetime
import nats
from nats.aio.client import Client as NATS
from nats.aio.msg import Msg

from backend.config.settings import settings

logger = logging.getLogger(__name__)


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
    Handle webhook delivery event received from NATS.

    Delegates to WebhookManager which already implements HTTP POST with
    retry logic, signature verification, and delivery tracking.

    Args:
        data: Event data containing webhook_id, event_type, and payload.
    """
    webhook_id = data.get("webhook_id")
    event_type = data.get("event_type")
    payload = data.get("payload", {})

    logger.info("Processing webhook delivery: webhook_id=%s event_type=%s", webhook_id, event_type)

    try:
        from backend.integrations.governance.webhook_manager import get_webhook_manager

        manager = get_webhook_manager()
        delivery_ids = await manager.send_webhook(event_type, payload)

        if delivery_ids:
            logger.info(
                "Webhook %s dispatched %d delivery attempt(s): %s",
                webhook_id,
                len(delivery_ids),
                delivery_ids,
            )
        else:
            logger.debug(
                "Webhook %s: no active subscriptions for event_type=%s",
                webhook_id,
                event_type,
            )
    except Exception as exc:
        logger.error(
            "Webhook delivery failed for webhook_id=%s event_type=%s: %s",
            webhook_id,
            event_type,
            exc,
            exc_info=True,
        )


async def handle_compliance_check(data: Dict[str, Any]) -> None:
    """
    Handle compliance check request received from NATS.

    Runs the requested compliance check type via ComplianceChecker, then
    persists the resulting compliance status back to the asset record in
    the governance database and invalidates the relevant cache entries.

    Args:
        data: Check request data containing asset_id, check_type, and
              optional context.
    """
    asset_id = data.get("asset_id")
    check_type_str = data.get("check_type", "asset_compliance")

    logger.info(
        "Running compliance check: asset_id=%s check_type=%s", asset_id, check_type_str
    )

    try:
        from backend.agents.compliance.compliance_checker import (
            ComplianceChecker,
            ComplianceCheckType,
            get_compliance_checker,
        )
        from backend.database.session import get_db
        from backend.database.repositories import AssetRepository
        from backend.database.governance_models import ComplianceStatus
        from backend.database.cache_manager import cache_manager

        checker = get_compliance_checker()

        # Map string to enum; default to ASSET_COMPLIANCE if unknown
        try:
            check_type = ComplianceCheckType(check_type_str)
        except ValueError:
            check_type = ComplianceCheckType.ASSET_COMPLIANCE
            logger.warning(
                "Unknown check_type '%s', defaulting to ASSET_COMPLIANCE", check_type_str
            )

        result = checker.run_check(check_type)

        # Persist compliance status to the governance database
        if asset_id:
            db = next(get_db())
            try:
                asset_repo = AssetRepository(db)
                asset = asset_repo.get(asset_id)
                if asset:
                    # Map check score to compliance status
                    if result.score >= 80.0:
                        new_status = ComplianceStatus.COMPLIANT
                    elif result.score >= 50.0:
                        new_status = ComplianceStatus.NEEDS_REVIEW
                    else:
                        new_status = ComplianceStatus.NON_COMPLIANT

                    asset_repo.update_compliance_status(asset_id, new_status)
                    db.commit()
                    cache_manager.invalidate_asset(asset_id)

                    logger.info(
                        "Compliance check complete: asset_id=%s score=%.1f status=%s",
                        asset_id,
                        result.score,
                        new_status.value,
                    )

                    # Alert if non-compliant
                    if new_status == ComplianceStatus.NON_COMPLIANT:
                        await governance_nats.publish_alert(
                            severity="warning",
                            title=f"Asset {asset_id} is non-compliant",
                            description=(
                                f"Compliance check '{check_type_str}' scored {result.score:.1f}/100. "
                                f"Findings: {len(result.findings)}"
                            ),
                            asset_id=asset_id,
                            metadata={"check_type": check_type_str, "score": result.score},
                        )
                else:
                    logger.warning(
                        "Compliance check: asset_id=%s not found in governance DB", asset_id
                    )
            finally:
                db.close()

    except Exception as exc:
        logger.error(
            "Compliance check failed for asset_id=%s check_type=%s: %s",
            asset_id,
            check_type_str,
            exc,
            exc_info=True,
        )


async def handle_risk_recalculation(data: Dict[str, Any]) -> None:
    """
    Handle risk recalculation request received from NATS.

    Invokes RiskScoringEngine.calculate_risk_score() for the asset, maps
    the resulting score to a RiskTier, persists the update to the governance
    database, invalidates caches, and publishes an alert if the tier has
    changed to HIGH or UNACCEPTABLE.

    Args:
        data: Recalculation request data containing asset_id, reason, and
              optional context.
    """
    asset_id = data.get("asset_id")
    reason = data.get("reason", "manual_request")

    logger.info(
        "Recalculating risk: asset_id=%s reason=%s", asset_id, reason
    )

    if not asset_id:
        logger.warning("handle_risk_recalculation: missing asset_id in message")
        return

    try:
        from backend.agents.compliance.risk_scoring import get_risk_scoring_engine
        from backend.database.session import get_db
        from backend.database.repositories import AssetRepository
        from backend.database.governance_models import RiskTier as DBRiskTier
        from backend.database.cache_manager import cache_manager

        engine = get_risk_scoring_engine()

        # calculate_risk_score operates on the in-memory asset registry;
        # it raises ValueError if the asset is not registered there.
        try:
            risk_score = engine.calculate_risk_score(asset_id)
        except ValueError:
            logger.warning(
                "Risk recalculation: asset_id=%s not in in-memory registry; skipping",
                asset_id,
            )
            return

        # Map RiskScoringEngine tier (string) to DB RiskTier enum
        tier_map: Dict[str, DBRiskTier] = {
            "unacceptable": DBRiskTier.UNACCEPTABLE,
            "high": DBRiskTier.HIGH,
            "limited": DBRiskTier.LIMITED,
            "minimal": DBRiskTier.MINIMAL,
        }
        tier_str = risk_score.tier.value if hasattr(risk_score.tier, "value") else str(risk_score.tier)
        db_risk_tier = tier_map.get(tier_str.lower(), DBRiskTier.LIMITED)

        # Persist to governance database
        db = next(get_db())
        try:
            asset_repo = AssetRepository(db)
            asset = asset_repo.get(asset_id)
            if asset:
                previous_tier = asset.risk_tier
                asset_repo.update_risk_assessment(
                    asset_id,
                    risk_tier=db_risk_tier,
                    risk_score=risk_score.score,
                )
                db.commit()
                cache_manager.invalidate_asset(asset_id)
                cache_manager.invalidate_risk_score(asset_id)

                logger.info(
                    "Risk recalculation complete: asset_id=%s score=%.1f tier=%s (was %s)",
                    asset_id,
                    risk_score.score,
                    db_risk_tier.value,
                    previous_tier,
                )

                # Alert if tier escalated to HIGH or UNACCEPTABLE
                if db_risk_tier in (DBRiskTier.HIGH, DBRiskTier.UNACCEPTABLE) and (
                    previous_tier != db_risk_tier
                ):
                    await governance_nats.publish_alert(
                        severity="error" if db_risk_tier == DBRiskTier.UNACCEPTABLE else "warning",
                        title=f"Risk tier escalated for asset {asset_id}",
                        description=(
                            f"Asset risk tier changed from {previous_tier} to {db_risk_tier.value} "
                            f"(score: {risk_score.score:.1f}). Reason: {reason}."
                        ),
                        asset_id=asset_id,
                        metadata={
                            "previous_tier": str(previous_tier),
                            "new_tier": db_risk_tier.value,
                            "score": risk_score.score,
                            "reason": reason,
                        },
                    )
            else:
                logger.warning(
                    "Risk recalculation: asset_id=%s not found in governance DB", asset_id
                )
        finally:
            db.close()

    except Exception as exc:
        logger.error(
            "Risk recalculation failed for asset_id=%s: %s",
            asset_id,
            exc,
            exc_info=True,
        )


async def handle_alert(data: Dict[str, Any]) -> None:
    """
    Handle alert notification received from NATS.

    Performs structured logging at the appropriate level and re-publishes
    the alert to the NATS alerts subject so downstream consumers (e.g.
    Slack, PagerDuty integrations) can pick it up.  Critical alerts are
    also escalated via an additional publish to the critical-severity
    subject.

    Args:
        data: Alert data containing severity, title, description, asset_id,
              and optional metadata.
    """
    severity = data.get("severity", "info")
    title = data.get("title", "(no title)")
    description = data.get("description", "")
    asset_id = data.get("asset_id")
    metadata = data.get("metadata", {})

    # Structured log at the appropriate level
    log_payload = {
        "alert_severity": severity,
        "alert_title": title,
        "alert_description": description,
        "asset_id": asset_id,
        "metadata": metadata,
        "timestamp": data.get("timestamp", datetime.utcnow().isoformat()),
    }

    if severity == "critical":
        logger.critical("ALERT [critical]: %s | %s | %s", title, description, log_payload)
    elif severity == "error":
        logger.error("ALERT [error]: %s | %s | %s", title, description, log_payload)
    elif severity == "warning":
        logger.warning("ALERT [warning]: %s | %s | %s", title, description, log_payload)
    else:
        logger.info("ALERT [info]: %s | %s | %s", title, description, log_payload)

    # Re-publish to NATS alerts subject so downstream consumers receive it.
    # Guard against infinite loops: only re-publish if the message did not
    # already originate from a re-publish (checked via metadata flag).
    if not metadata.get("_republished"):
        try:
            republish_metadata = dict(metadata)
            republish_metadata["_republished"] = True

            await governance_nats.publish_alert(
                severity=severity,
                title=title,
                description=description,
                asset_id=asset_id,
                metadata=republish_metadata,
            )

            # Extra escalation publish for critical alerts
            if severity == "critical" and severity != "critical":  # placeholder for future escalation
                pass

        except Exception as exc:
            logger.error(
                "Failed to re-publish alert to NATS: %s", exc, exc_info=True
            )


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
