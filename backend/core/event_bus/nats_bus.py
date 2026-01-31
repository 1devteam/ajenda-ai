"""
NATS Event Bus - Stub Implementation
TODO: Implement full event bus in v5.0

This is a temporary stub to satisfy imports.
The real event bus will be implemented as part of v5.0.
"""
from enum import Enum
from typing import Callable, Any
import asyncio


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


class NATSEventBus:
    """
    Stub NATS Event Bus
    
    In v5.0, this will provide:
    - Pub/sub messaging between agents
    - Event-driven architecture
    - Distributed system coordination
    - Real-time event streaming
    """
    
    def __init__(self):
        self._subscribers = {}
    
    async def connect(self):
        """Stub connect method"""
        pass
    
    async def disconnect(self):
        """Stub disconnect method"""
        pass
    
    async def publish(self, subject: str, data: dict):
        """
        Stub publish method
        
        Args:
            subject: Event subject (e.g., "mission.created")
            data: Event payload
        """
        # In v5.0, this will publish to NATS
        pass
    
    async def subscribe(self, subject: str, callback: Callable):
        """
        Stub subscribe method
        
        Args:
            subject: Event subject to subscribe to
            callback: Function to call when event is received
        """
        # In v5.0, this will subscribe to NATS subjects
        if subject not in self._subscribers:
            self._subscribers[subject] = []
        self._subscribers[subject].append(callback)
    
    async def request(self, subject: str, data: dict, timeout: float = 5.0) -> Any:
        """
        Stub request-reply method
        
        Args:
            subject: Request subject
            data: Request payload
            timeout: Timeout in seconds
            
        Returns:
            Response data
        """
        # In v5.0, this will do request-reply pattern
        return {}


# Global event bus instance
event_bus = NATSEventBus()
