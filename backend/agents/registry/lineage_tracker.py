"""
Model Lineage Tracker

Tracks the provenance and lifecycle of AI models.
Part of Month 2 Week 1: AIAsset Inventory & Lineage Tracking.

Built with Pride for Obex Blackvault.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any
from uuid import uuid4

from .asset_registry import AIAsset, AssetType, ModelLineage, get_registry


@dataclass
class LineageEvent:
    """
    Represents an event in the lineage of an AI model.
    
    Events track changes to the model over time (fine-tuning, updates, etc.).
    """
    event_id: str
    asset_id: str
    event_type: str  # "created", "fine_tuned", "updated", "deprecated"
    description: str
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert event to dictionary."""
        return {
            "event_id": self.event_id,
            "asset_id": self.asset_id,
            "event_type": self.event_type,
            "description": self.description,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
        }


class LineageTracker:
    """
    Tracks lineage events for AI models.
    
    Provides a timeline of changes and provenance information.
    """
    
    _instance: Optional["LineageTracker"] = None
    
    def __new__(cls):
        """Singleton pattern."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        """Initialize tracker."""
        if self._initialized:
            return
        
        self._events: Dict[str, LineageEvent] = {}
        self._events_by_asset: Dict[str, List[str]] = {}
        self._initialized = True
    
    def track_event(
        self,
        asset_id: str,
        event_type: str,
        description: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Track a lineage event.
        
        Args:
            asset_id: The asset ID
            event_type: Type of event
            description: Event description
            metadata: Additional metadata
            
        Returns:
            The event ID
        """
        event_id = str(uuid4())
        event = LineageEvent(
            event_id=event_id,
            asset_id=asset_id,
            event_type=event_type,
            description=description,
            metadata=metadata or {},
        )
        
        self._events[event_id] = event
        
        if asset_id not in self._events_by_asset:
            self._events_by_asset[asset_id] = []
        self._events_by_asset[asset_id].append(event_id)
        
        return event_id
    
    def get_event(self, event_id: str) -> Optional[LineageEvent]:
        """Get an event by ID."""
        return self._events.get(event_id)
    
    def get_events_for_asset(self, asset_id: str) -> List[LineageEvent]:
        """
        Get all events for an asset.
        
        Args:
            asset_id: The asset ID
            
        Returns:
            List of events, sorted by timestamp (newest first)
        """
        event_ids = self._events_by_asset.get(asset_id, [])
        events = [self._events[event_id] for event_id in event_ids]
        return sorted(events, key=lambda e: e.timestamp, reverse=True)
    
    def get_lineage_chain(self, asset_id: str) -> List[AIAsset]:
        """
        Get the full lineage chain for an asset.
        
        Traces back through dependencies to find the origin.
        
        Args:
            asset_id: The asset ID
            
        Returns:
            List of assets in the lineage chain (from origin to current)
        """
        registry = get_registry()
        asset = registry.get(asset_id)
        if not asset:
            return []
        
        chain = [asset]
        visited = {asset_id}
        
        # Trace back through dependencies
        current = asset
        while current.dependencies:
            # Get first dependency (assuming linear lineage)
            dep_id = current.dependencies[0]
            if dep_id in visited:
                break  # Circular dependency
            
            dep_asset = registry.get(dep_id)
            if not dep_asset:
                break
            
            chain.insert(0, dep_asset)
            visited.add(dep_id)
            current = dep_asset
        
        return chain
    
    def track_model_creation(
        self,
        asset_id: str,
        base_model: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Track model creation event.
        
        Args:
            asset_id: The asset ID
            base_model: Base model name
            metadata: Additional metadata
            
        Returns:
            The event ID
        """
        return self.track_event(
            asset_id=asset_id,
            event_type="created",
            description=f"Model created from base model: {base_model}",
            metadata=metadata or {},
        )
    
    def track_fine_tuning(
        self,
        asset_id: str,
        dataset: str,
        parameters: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Track fine-tuning event.
        
        Args:
            asset_id: The asset ID
            dataset: Dataset used for fine-tuning
            parameters: Fine-tuning parameters
            
        Returns:
            The event ID
        """
        return self.track_event(
            asset_id=asset_id,
            event_type="fine_tuned",
            description=f"Model fine-tuned on dataset: {dataset}",
            metadata={"dataset": dataset, "parameters": parameters or {}},
        )
    
    def track_vector_db_update(
        self,
        asset_id: str,
        source: str,
        documents_added: int,
    ) -> str:
        """
        Track vector database update event.
        
        Args:
            asset_id: The asset ID
            source: Source of documents
            documents_added: Number of documents added
            
        Returns:
            The event ID
        """
        return self.track_event(
            asset_id=asset_id,
            event_type="updated",
            description=f"Vector DB updated with {documents_added} documents from {source}",
            metadata={"source": source, "documents_added": documents_added},
        )
    
    def track_deprecation(
        self,
        asset_id: str,
        reason: str,
        replacement_id: Optional[str] = None,
    ) -> str:
        """
        Track deprecation event.
        
        Args:
            asset_id: The asset ID
            reason: Reason for deprecation
            replacement_id: ID of replacement asset (if any)
            
        Returns:
            The event ID
        """
        metadata = {"reason": reason}
        if replacement_id:
            metadata["replacement_id"] = replacement_id
        
        return self.track_event(
            asset_id=asset_id,
            event_type="deprecated",
            description=f"Model deprecated: {reason}",
            metadata=metadata,
        )
    
    def clear(self):
        """Clear all events (for testing)."""
        self._events.clear()
        self._events_by_asset.clear()


# Global tracker instance
_tracker = LineageTracker()


def get_tracker() -> LineageTracker:
    """Get the global lineage tracker instance."""
    return _tracker
