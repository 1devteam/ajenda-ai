"""
API Gateway & Event Streaming - External integrations.

API Gateway: Accept inbound API calls, authenticate, rate limit
Event Streaming: Stream governance events in real-time via WebSocket/SSE

Author: Dev Team Lead
Date: 2026-02-27
Built with Pride for Obex Blackvault
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from enum import Enum
import uuid
import hashlib
import secrets


# ============================================================================
# Enums
# ============================================================================


class StreamType(Enum):
    """Types of event streams."""

    AUDIT = "audit"
    POLICY = "policy"
    APPROVAL = "approval"
    ALERT = "alert"
    METRICS = "metrics"


# ============================================================================
# Data Models - API Gateway
# ============================================================================


@dataclass
class APIKey:
    """
    Represents an API key for external access.
    """

    key_id: str
    key_hash: str  # Hashed key for security
    name: str
    organization: str
    permissions: List[str]  # Scopes: read:assets, write:policies, etc.
    rate_limit: int  # Requests per minute
    active: bool
    created_at: datetime
    expires_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "key_id": self.key_id,
            "name": self.name,
            "organization": self.organization,
            "permissions": self.permissions,
            "rate_limit": self.rate_limit,
            "active": self.active,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }


@dataclass
class APIRequest:
    """
    Represents an API request.
    """

    request_id: str
    key_id: str
    endpoint: str
    method: str
    timestamp: datetime
    response_code: int
    response_time_ms: int

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "request_id": self.request_id,
            "key_id": self.key_id,
            "endpoint": self.endpoint,
            "method": self.method,
            "timestamp": self.timestamp.isoformat(),
            "response_code": self.response_code,
            "response_time_ms": self.response_time_ms,
        }


# ============================================================================
# Data Models - Event Streaming
# ============================================================================


@dataclass
class StreamSubscription:
    """
    Represents a stream subscription.
    """

    subscription_id: str
    connection_id: str
    stream_type: StreamType
    filters: Dict[str, Any]
    created_at: datetime
    last_activity: datetime

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "subscription_id": self.subscription_id,
            "connection_id": self.connection_id,
            "stream_type": self.stream_type.value,
            "filters": self.filters,
            "created_at": self.created_at.isoformat(),
            "last_activity": self.last_activity.isoformat(),
        }


@dataclass
class StreamEvent:
    """
    Represents a stream event.
    """

    event_id: str
    stream_type: StreamType
    timestamp: datetime
    data: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "event_id": self.event_id,
            "stream_type": self.stream_type.value,
            "timestamp": self.timestamp.isoformat(),
            "data": self.data,
        }


# ============================================================================
# API Gateway
# ============================================================================


class APIGateway:
    """
    Manages external API access.

    Authenticates requests, enforces rate limits, tracks usage.
    Singleton pattern ensures consistent gateway behavior.
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

        self._api_keys: Dict[str, APIKey] = {}
        self._requests: Dict[str, APIRequest] = {}
        self._rate_limit_buckets: Dict[str, List[datetime]] = {}
        self._initialized = True

    def create_api_key(
        self,
        name: str,
        organization: str,
        permissions: List[str],
        rate_limit: int = 100,
        expires_in_days: Optional[int] = None,
    ) -> tuple[str, APIKey]:
        """
        Create an API key.

        Args:
            name: Key name
            organization: Organization name
            permissions: List of permission scopes
            rate_limit: Requests per minute
            expires_in_days: Expiration in days (None = no expiration)

        Returns:
            Tuple of (raw_key, api_key_object)
        """
        key_id = f"key-{uuid.uuid4()}"
        raw_key = secrets.token_urlsafe(32)
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

        expires_at = None
        if expires_in_days:
            expires_at = datetime.utcnow() + timedelta(days=expires_in_days)

        api_key = APIKey(
            key_id=key_id,
            key_hash=key_hash,
            name=name,
            organization=organization,
            permissions=permissions,
            rate_limit=rate_limit,
            active=True,
            created_at=datetime.utcnow(),
            expires_at=expires_at,
        )

        self._api_keys[key_id] = api_key
        return raw_key, api_key

    def revoke_api_key(self, key_id: str) -> bool:
        """
        Revoke an API key.

        Args:
            key_id: Key ID

        Returns:
            True if revoked
        """
        if key_id in self._api_keys:
            self._api_keys[key_id].active = False
            return True
        return False

    def validate_api_key(self, raw_key: str) -> Optional[APIKey]:
        """
        Validate an API key.

        Args:
            raw_key: Raw API key

        Returns:
            API key if valid, None otherwise
        """
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

        for api_key in self._api_keys.values():
            if api_key.key_hash == key_hash and api_key.active:
                # Check expiration
                if api_key.expires_at and datetime.utcnow() > api_key.expires_at:
                    api_key.active = False
                    return None
                return api_key

        return None

    def check_rate_limit(self, key_id: str) -> bool:
        """
        Check if API key is within rate limit.

        Args:
            key_id: Key ID

        Returns:
            True if within limit
        """
        api_key = self._api_keys.get(key_id)
        if not api_key:
            return False

        # Get request timestamps in last minute
        now = datetime.utcnow()
        one_minute_ago = now - timedelta(minutes=1)

        if key_id not in self._rate_limit_buckets:
            self._rate_limit_buckets[key_id] = []

        # Remove old timestamps
        self._rate_limit_buckets[key_id] = [
            ts for ts in self._rate_limit_buckets[key_id] if ts > one_minute_ago
        ]

        # Check limit
        if len(self._rate_limit_buckets[key_id]) >= api_key.rate_limit:
            return False

        # Add current request
        self._rate_limit_buckets[key_id].append(now)
        return True

    def log_request(
        self,
        key_id: str,
        endpoint: str,
        method: str,
        response_code: int,
        response_time_ms: int,
    ) -> APIRequest:
        """
        Log an API request.

        Args:
            key_id: Key ID
            endpoint: Endpoint path
            method: HTTP method
            response_code: Response status code
            response_time_ms: Response time in milliseconds

        Returns:
            Logged request
        """
        request_id = f"req-{uuid.uuid4()}"

        request = APIRequest(
            request_id=request_id,
            key_id=key_id,
            endpoint=endpoint,
            method=method,
            timestamp=datetime.utcnow(),
            response_code=response_code,
            response_time_ms=response_time_ms,
        )

        self._requests[request_id] = request
        return request

    def get_api_key(self, key_id: str) -> Optional[APIKey]:
        """Get API key by ID."""
        return self._api_keys.get(key_id)

    def list_api_keys(self, active_only: bool = True) -> List[APIKey]:
        """
        List API keys.

        Args:
            active_only: Only return active keys

        Returns:
            List of API keys
        """
        keys = list(self._api_keys.values())
        if active_only:
            keys = [k for k in keys if k.active]
        return keys

    def get_usage_stats(self, key_id: str) -> Dict[str, Any]:
        """
        Get usage statistics for an API key.

        Args:
            key_id: Key ID

        Returns:
            Usage statistics
        """
        requests = [r for r in self._requests.values() if r.key_id == key_id]

        if not requests:
            return {
                "total_requests": 0,
                "avg_response_time_ms": 0,
                "by_status_code": {},
                "by_endpoint": {},
            }

        # Calculate stats
        by_status = {}
        by_endpoint = {}
        total_time = 0

        for req in requests:
            # By status code
            code = str(req.response_code)
            by_status[code] = by_status.get(code, 0) + 1

            # By endpoint
            by_endpoint[req.endpoint] = by_endpoint.get(req.endpoint, 0) + 1

            # Response time
            total_time += req.response_time_ms

        return {
            "total_requests": len(requests),
            "avg_response_time_ms": total_time / len(requests),
            "by_status_code": by_status,
            "by_endpoint": by_endpoint,
        }

    def clear(self) -> None:
        """Clear all keys and requests (for testing)."""
        self._api_keys.clear()
        self._requests.clear()
        self._rate_limit_buckets.clear()


# ============================================================================
# Event Streaming
# ============================================================================


class EventStreaming:
    """
    Manages real-time event streaming.

    Streams governance events via WebSocket/SSE, manages subscriptions.
    Singleton pattern ensures consistent streaming.
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

        self._subscriptions: Dict[str, StreamSubscription] = {}
        self._event_buffers: Dict[StreamType, List[StreamEvent]] = {
            stream_type: [] for stream_type in StreamType
        }
        self._buffer_size = 100  # Keep last 100 events per stream
        self._initialized = True

    def subscribe(
        self,
        connection_id: str,
        stream_type: StreamType,
        filters: Optional[Dict[str, Any]] = None,
    ) -> StreamSubscription:
        """
        Subscribe to an event stream.

        Args:
            connection_id: Unique connection ID
            stream_type: Type of stream
            filters: Optional filters

        Returns:
            Stream subscription
        """
        subscription_id = f"sub-{uuid.uuid4()}"

        subscription = StreamSubscription(
            subscription_id=subscription_id,
            connection_id=connection_id,
            stream_type=stream_type,
            filters=filters or {},
            created_at=datetime.utcnow(),
            last_activity=datetime.utcnow(),
        )

        self._subscriptions[subscription_id] = subscription
        return subscription

    def unsubscribe(self, subscription_id: str) -> bool:
        """
        Unsubscribe from a stream.

        Args:
            subscription_id: Subscription ID

        Returns:
            True if unsubscribed
        """
        if subscription_id in self._subscriptions:
            del self._subscriptions[subscription_id]
            return True
        return False

    def publish(self, stream_type: StreamType, data: Dict[str, Any]) -> StreamEvent:
        """
        Publish an event to a stream.

        Args:
            stream_type: Stream type
            data: Event data

        Returns:
            Published event
        """
        event_id = f"event-{uuid.uuid4()}"

        event = StreamEvent(
            event_id=event_id,
            stream_type=stream_type,
            timestamp=datetime.utcnow(),
            data=data,
        )

        # Add to buffer
        self._event_buffers[stream_type].append(event)

        # Trim buffer
        if len(self._event_buffers[stream_type]) > self._buffer_size:
            self._event_buffers[stream_type] = self._event_buffers[stream_type][
                -self._buffer_size :
            ]

        return event

    def get_recent_events(
        self,
        stream_type: StreamType,
        limit: int = 10,
    ) -> List[StreamEvent]:
        """
        Get recent events from a stream.

        Args:
            stream_type: Stream type
            limit: Maximum number of events

        Returns:
            List of recent events
        """
        events = self._event_buffers.get(stream_type, [])
        return events[-limit:]

    def get_active_subscriptions(self) -> List[StreamSubscription]:
        """
        Get active subscriptions.

        Returns:
            List of active subscriptions
        """
        # Remove stale subscriptions (no activity in 5 minutes)
        stale_threshold = datetime.utcnow() - timedelta(minutes=5)

        active = []
        for sub in list(self._subscriptions.values()):
            if sub.last_activity > stale_threshold:
                active.append(sub)
            else:
                del self._subscriptions[sub.subscription_id]

        return active

    def update_activity(self, subscription_id: str) -> bool:
        """
        Update subscription activity timestamp.

        Args:
            subscription_id: Subscription ID

        Returns:
            True if updated
        """
        sub = self._subscriptions.get(subscription_id)
        if sub:
            sub.last_activity = datetime.utcnow()
            return True
        return False

    def get_statistics(self) -> Dict[str, Any]:
        """
        Get streaming statistics.

        Returns:
            Statistics about streams
        """
        by_stream = {}
        for stream_type in StreamType:
            by_stream[stream_type.value] = {
                "event_count": len(self._event_buffers[stream_type]),
                "subscription_count": len(
                    [s for s in self._subscriptions.values() if s.stream_type == stream_type]
                ),
            }

        return {
            "total_subscriptions": len(self._subscriptions),
            "by_stream": by_stream,
        }

    def clear(self) -> None:
        """Clear all subscriptions and events (for testing)."""
        self._subscriptions.clear()
        for stream_type in StreamType:
            self._event_buffers[stream_type].clear()


# ============================================================================
# Singleton Access
# ============================================================================


def get_api_gateway() -> APIGateway:
    """Get the singleton API gateway instance."""
    return APIGateway()


def get_event_streaming() -> EventStreaming:
    """Get the singleton event streaming instance."""
    return EventStreaming()
