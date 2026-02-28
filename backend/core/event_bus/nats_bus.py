"""
NATS Event Bus - Full Implementation for v5.0
Real event-driven messaging system using NATS
"""
from enum import Enum
from typing import Callable, Any, Optional, Dict
import asyncio
import json
import logging
from datetime import datetime

try:
    import nats
    from nats.aio.client import Client as NATS
    from nats.js import JetStreamContext
    NATS_AVAILABLE = True
except ImportError:
    NATS_AVAILABLE = False
    logging.warning("nats-py not installed. Install with: pip install nats-py")


logger = logging.getLogger(__name__)


class Subjects(Enum):
    """Event subjects for NATS messaging"""
    MISSION_CREATED = "mission.created"
    MISSION_STARTED = "mission.started"
    MISSION_COMPLETED = "mission.completed"
    MISSION_FAILED = "mission.failed"
    AGENT_STATUS_CHANGED = "agent.status.changed"
    AGENT_CREATED = "agent.created"
    RESOURCE_CHARGED = "resource.charged"
    RESOURCE_REWARDED = "resource.rewarded"
    LEARNING_OUTCOME = "learning.outcome"
    SYSTEM_ALERT = "system.alert"


class NATSEventBus:
    """
    Real NATS Event Bus for distributed messaging.

    When a NATS server is reachable the bus uses the nats-py client for full
    pub/sub and request-reply.  When NATS is unavailable (e.g. local dev or
    unit tests) the bus falls back to an in-process delivery mechanism so that
    all subscribers and request handlers still receive messages without any
    code changes at the call site.
    """
    
    def __init__(self, nats_url: str = "nats://localhost:4222"):
        self.nats_url = nats_url
        self.nc: Optional[NATS] = None
        self.js: Optional[JetStreamContext] = None
        self._subscribers: Dict[str, list] = {}
        self._connected = False
        # In-process request handlers: subject → async callable
        # Used for request-reply when NATS is unavailable.
        self._request_handlers: Dict[str, Callable] = {}

        if not NATS_AVAILABLE:
            logger.debug("NATS client not available — running in local-delivery mode")
    
    async def connect(self):
        """
        Connect to NATS server
        
        Like opening a connection to the post office
        """
        if not NATS_AVAILABLE:
            logger.debug("NATS not available — using in-process local-delivery mode")
            self._connected = True
            return
        
        try:
            self.nc = await nats.connect(self.nats_url)
            self.js = self.nc.jetstream()
            self._connected = True
            logger.info(f"Connected to NATS at {self.nats_url}")
            
            # Create streams for different event types
            await self._setup_streams()
            
        except Exception as e:
            logger.error(f"Failed to connect to NATS: {e}")
            logger.info("Falling back to in-memory stub mode")
            self._connected = True  # Continue in stub mode
    
    async def _setup_streams(self):
        """
        Set up JetStream streams for persistent messaging
        
        Streams are like organized filing cabinets that keep messages safe
        """
        if not self.js:
            return
        
        streams = [
            {
                "name": "MISSIONS",
                "subjects": ["mission.*"],
                "description": "Mission lifecycle events"
            },
            {
                "name": "AGENTS",
                "subjects": ["agent.*"],
                "description": "Agent lifecycle and status events"
            },
            {
                "name": "ECONOMY",
                "subjects": ["resource.*"],
                "description": "Economy and resource events"
            },
            {
                "name": "LEARNING",
                "subjects": ["learning.*"],
                "description": "Meta-learning events"
            },
            {
                "name": "SYSTEM",
                "subjects": ["system.*"],
                "description": "System-level events"
            }
        ]
        
        for stream_config in streams:
            try:
                await self.js.add_stream(
                    name=stream_config["name"],
                    subjects=stream_config["subjects"],
                    description=stream_config["description"]
                )
                logger.info(f"Created stream: {stream_config['name']}")
            except Exception as e:
                # Stream might already exist
                logger.debug(f"Stream {stream_config['name']} setup: {e}")
    
    async def disconnect(self):
        """
        Disconnect from NATS server
        
        Like closing the connection to the post office
        """
        if self.nc and self._connected:
            await self.nc.close()
            self._connected = False
            logger.info("Disconnected from NATS")
    
    async def publish(self, subject: str, data: dict):
        """
        Publish an event to NATS
        
        Like sending a letter - it goes to everyone who's listening for that subject
        
        Args:
            subject: Event subject (e.g., "mission.created")
            data: Event payload (will be JSON serialized)
        """
        # Add metadata
        event = {
            "subject": subject,
            "data": data,
            "timestamp": datetime.now().isoformat(),
            "event_id": f"{subject}-{datetime.now().timestamp()}"
        }
        
        # Serialize to JSON
        message = json.dumps(event).encode()
        
        # Record metric
        from backend.integrations.observability.prometheus_metrics import get_metrics
        get_metrics().record_nats_message(subject, "pub")
        
        if self.nc and self._connected and NATS_AVAILABLE:
            try:
                # Publish to NATS
                await self.nc.publish(subject, message)
                logger.debug(f"Published event: {subject}")
            except Exception as e:
                logger.error(f"Failed to publish event {subject}: {e}")
        else:
            # Local-delivery mode — deliver to in-process subscribers
            logger.debug("[LOCAL] Published event: %s", subject)
            await self._deliver_local(subject, event)
    
    async def _deliver_local(self, subject: str, event: dict):
        """
        Deliver event to local subscribers (stub mode)
        
        When NATS isn't available, we still deliver messages locally
        """
        if subject in self._subscribers:
            for callback in self._subscribers[subject]:
                try:
                    # Call the callback with the event data
                    if asyncio.iscoroutinefunction(callback):
                        await callback(event)
                    else:
                        callback(event)
                except Exception as e:
                    logger.error(f"Error in subscriber callback: {e}")
    
    async def subscribe(self, subject: str, callback: Callable):
        """
        Subscribe to events on a subject
        
        Like signing up to receive certain types of letters
        
        Args:
            subject: Event subject to subscribe to (can use wildcards like "mission.*")
            callback: Async function to call when event is received
        """
        # Store local subscriber
        if subject not in self._subscribers:
            self._subscribers[subject] = []
        self._subscribers[subject].append(callback)
        
        if self.nc and self._connected and NATS_AVAILABLE:
            try:
                # Subscribe to NATS
                async def message_handler(msg):
                    try:
                        # Decode and parse message
                        event = json.loads(msg.data.decode())
                        
                        # Record metric
                        from backend.integrations.observability.prometheus_metrics import get_metrics
                        get_metrics().record_nats_message(subject, "sub")
                        
                        # Call the callback
                        if asyncio.iscoroutinefunction(callback):
                            await callback(event)
                        else:
                            callback(event)
                    except Exception as e:
                        logger.error(f"Error handling message: {e}")
                
                await self.nc.subscribe(subject, cb=message_handler)
                logger.info(f"Subscribed to: {subject}")
            except Exception as e:
                logger.error(f"Failed to subscribe to {subject}: {e}")
        else:
            logger.debug("[LOCAL] Subscribed to: %s", subject)
    
    def register_request_handler(self, subject: str, handler: Callable) -> None:
        """
        Register an in-process handler for request-reply on *subject*.

        The handler must be an async callable with the signature::

            async def handler(data: dict) -> dict: ...

        It is used when NATS is unavailable (local-delivery mode) so that
        ``request()`` callers receive a real response instead of a stub.

        Args:
            subject: The subject to handle (exact match, no wildcards).
            handler: Async callable that accepts request data and returns
                     a response dict.
        """
        self._request_handlers[subject] = handler
        logger.debug("Registered in-process request handler for: %s", subject)

    async def request(self, subject: str, data: dict, timeout: float = 5.0) -> Any:
        """
        Request-reply pattern — send a request and wait for a response.

        When connected to a real NATS server the standard NATS request-reply
        mechanism is used.  In local-delivery mode the call is routed to a
        registered in-process handler (if one exists) so that callers always
        receive a meaningful response.

        Args:
            subject: Request subject.
            data:    Request payload.
            timeout: Timeout in seconds (only applies to real NATS).

        Returns:
            Response dict from the handler, or an error dict on failure.
        """
        request_envelope = {
            "subject": subject,
            "data": data,
            "timestamp": datetime.now().isoformat(),
        }

        if self.nc and self._connected and NATS_AVAILABLE:
            try:
                message = json.dumps(request_envelope).encode()
                response = await self.nc.request(subject, message, timeout=timeout)
                return json.loads(response.data.decode())
            except Exception as exc:
                logger.error("NATS request failed for subject '%s': %s", subject, exc)
                return {"error": str(exc)}

        # Local-delivery mode — route to registered in-process handler
        handler = self._request_handlers.get(subject)
        if handler is not None:
            try:
                logger.debug("[LOCAL] Request routed in-process: %s", subject)
                import asyncio
                if asyncio.iscoroutinefunction(handler):
                    return await handler(data)
                return handler(data)
            except Exception as exc:
                logger.error(
                    "In-process request handler for '%s' raised: %s", subject, exc
                )
                return {"error": str(exc)}

        # No handler registered — return an informative response instead of a
        # silent stub so callers can detect the unhandled case.
        logger.debug("[LOCAL] No request handler registered for: %s", subject)
        return {"status": "no_handler", "subject": subject}
    
    async def publish_mission_event(self, mission_id: str, status: str, data: dict = None):
        """
        Helper: Publish mission lifecycle event
        
        Makes it easy to announce mission updates
        """
        subject_map = {
            "created": Subjects.MISSION_CREATED.value,
            "started": Subjects.MISSION_STARTED.value,
            "completed": Subjects.MISSION_COMPLETED.value,
            "failed": Subjects.MISSION_FAILED.value
        }
        
        subject = subject_map.get(status, "mission.unknown")
        
        payload = {
            "mission_id": mission_id,
            "status": status,
            **(data or {})
        }
        
        await self.publish(subject, payload)
    
    async def publish_agent_event(self, agent_id: str, event_type: str, data: dict = None):
        """
        Helper: Publish agent event
        
        Makes it easy to announce agent updates
        """
        subject_map = {
            "created": Subjects.AGENT_CREATED.value,
            "status_changed": Subjects.AGENT_STATUS_CHANGED.value
        }
        
        subject = subject_map.get(event_type, "agent.unknown")
        
        payload = {
            "agent_id": agent_id,
            "event_type": event_type,
            **(data or {})
        }
        
        await self.publish(subject, payload)
    
    async def publish_economy_event(self, agent_id: str, event_type: str, 
                                   amount: float, resource_type: str, data: dict = None):
        """
        Helper: Publish economy event
        
        Announces when credits are earned or spent
        """
        subject_map = {
            "charged": Subjects.RESOURCE_CHARGED.value,
            "rewarded": Subjects.RESOURCE_REWARDED.value
        }
        
        subject = subject_map.get(event_type, "resource.unknown")
        
        payload = {
            "agent_id": agent_id,
            "event_type": event_type,
            "amount": amount,
            "resource_type": resource_type,
            **(data or {})
        }
        
        await self.publish(subject, payload)
    
    async def publish_learning_outcome(self, agent_id: str, mission_id: str, 
                                      outcome_data: dict):
        """
        Helper: Publish learning outcome
        
        Announces when an agent learns from a mission
        """
        payload = {
            "agent_id": agent_id,
            "mission_id": mission_id,
            **outcome_data
        }
        
        await self.publish(Subjects.LEARNING_OUTCOME.value, payload)
    
    def is_connected(self) -> bool:
        """Check if event bus is connected"""
        return self._connected


# Global event bus instance
event_bus = NATSEventBus()


async def get_event_bus() -> NATSEventBus:
    """
    Get the global event bus instance
    
    Use this in your code to access the event bus
    """
    if not event_bus.is_connected():
        await event_bus.connect()
    return event_bus
