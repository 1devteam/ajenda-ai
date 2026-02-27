"""
Tests for Lineage Tracker

Comprehensive test coverage for ModelLineageTracker.
Part of Month 2 Week 1: AIAsset Inventory & Lineage Tracking.

Built with Pride for Obex Blackvault.
"""

import pytest
from datetime import datetime, timedelta
from backend.agents.registry.lineage_tracker import (
    LineageEvent,
    LineageTracker,
)
from backend.agents.registry.asset_registry import (
    AIAsset,
    AssetType,
    AssetStatus,
    ModelLineage,
    get_registry,
)


@pytest.fixture(autouse=True)
def clear_state():
    """Clear registry and tracker before each test."""
    from backend.agents.registry.asset_registry import get_registry
    from backend.agents.registry.lineage_tracker import get_tracker
    reg = get_registry()
    t = get_tracker()
    reg._assets.clear()
    t.clear()
    yield
    reg._assets.clear()
    t.clear()


@pytest.fixture
def tracker():
    """Get the tracker instance."""
    from backend.agents.registry.lineage_tracker import get_tracker
    return get_tracker()


@pytest.fixture
def registry():
    """Get the registry instance."""
    from backend.agents.registry.asset_registry import get_registry
    return get_registry()


@pytest.fixture
def sample_model(registry):
    """Create and register a sample model."""
    lineage = ModelLineage(
        base_model="gpt-4",
        fine_tuning_data=["dataset-001"],
        vector_db_sources=["vectordb-001"],
        training_date=datetime(2026, 1, 15),
        model_version="1.0.0",
    )
    model = AIAsset(
        asset_id="model-001",
        asset_type=AssetType.MODEL,
        name="Research Model",
        description="Fine-tuned model",
        owner="team-ml",
        lineage=lineage,
    )
    registry.register(model)
    return model


# ============================================================================
# EVENT TRACKING TESTS
# ============================================================================


def test_track_model_creation(tracker):
    """Test tracking model creation event."""
    event_id = tracker.track_model_creation(
        asset_id="model-001",
        base_model="gpt-4",
        metadata={"version": "1.0"},
    )
    
    assert event_id is not None
    
    # Verify event
    event = tracker.get_event(event_id)
    assert event is not None
    assert event.asset_id == "model-001"
    assert event.event_type == "created"
    assert event.description == "Model created from base model: gpt-4"
    assert event.metadata["version"] == "1.0"


def test_track_fine_tuning(tracker):
    """Test tracking fine-tuning event."""
    event_id = tracker.track_fine_tuning(
        asset_id="model-001",
        dataset="dataset-001,dataset-002",
        parameters={"epochs": 10, "learning_rate": 0.001},
    )
    
    assert event_id is not None
    
    # Verify event
    event = tracker.get_event(event_id)
    assert event is not None
    assert event.asset_id == "model-001"
    assert event.event_type == "fine_tuned"
    assert "dataset-001" in event.description
    assert event.metadata["parameters"]["epochs"] == 10


def test_track_event(tracker):
    """Test tracking model update event."""
    event_id = tracker.track_event(
        asset_id="model-001",
        event_type="updated",
        description="Model parameters updated",
        metadata={"changes": {"temperature": 0.7, "max_tokens": 2000}, "updated_by": "user-001"},
    )
    
    assert event_id is not None
    
    # Verify event
    event = tracker.get_event(event_id)
    assert event is not None
    assert event.asset_id == "model-001"
    assert event.event_type == "updated"
    assert "updated" in event.description.lower()
    assert event.metadata["updated_by"] == "user-001"


def test_track_deprecation(tracker):
    """Test tracking model deprecation event."""
    event_id = tracker.track_deprecation(
        asset_id="model-001",
        reason="Replaced by model-002",
        replacement_id="model-002",
    )
    
    assert event_id is not None
    
    # Verify event
    event = tracker.get_event(event_id)
    assert event is not None
    assert event.asset_id == "model-001"
    assert event.event_type == "deprecated"
    assert "Replaced by model-002" in event.description or "deprecated" in event.description.lower()
    assert event.metadata.get("replacement_id") == "model-002" or event.metadata.get("reason") == "Replaced by model-002"


def test_track_custom_event(tracker):
    """Test tracking custom event."""
    event_id = tracker.track_event(
        asset_id="model-001",
        event_type="deployed",
        description="Model deployed to production",
        metadata={"environment": "production", "version": "1.0"},
    )
    
    assert event_id is not None
    
    # Verify event
    event = tracker.get_event(event_id)
    assert event is not None
    assert event.asset_id == "model-001"
    assert event.event_type == "deployed"
    assert event.description == "Model deployed to production"
    assert event.metadata["environment"] == "production"


# ============================================================================
# EVENT RETRIEVAL TESTS
# ============================================================================


def test_get_event(tracker):
    """Test retrieving an event by ID."""
    event_id = tracker.track_model_creation(
        asset_id="model-001",
        base_model="gpt-4",
    )
    
    event = tracker.get_event(event_id)
    assert event is not None
    assert event.event_id == event_id


def test_get_nonexistent_event(tracker):
    """Test retrieving a nonexistent event returns None."""
    event = tracker.get_event("nonexistent-id")
    assert event is None


def test_get_events_for_asset(tracker):
    """Test getting all events for an asset."""
    # Track multiple events
    tracker.track_model_creation(asset_id="model-001", base_model="gpt-4")
    tracker.track_fine_tuning(asset_id="model-001", dataset="dataset-001")
    tracker.track_event(asset_id="model-001", event_type="updated", description="Model updated", metadata={"changes": {"temperature": 0.7}})
    
    # Get events
    events = tracker.get_events_for_asset("model-001")
    assert len(events) == 3
    
    # Verify events are sorted by timestamp (newest first)
    assert events[0].event_type == "updated"
    assert events[1].event_type == "fine_tuned"
    assert events[2].event_type == "created"


def test_get_events_for_asset_no_events(tracker):
    """Test getting events for asset with no events."""
    events = tracker.get_events_for_asset("model-001")
    assert len(events) == 0


def test_get_events_for_multiple_assets(tracker):
    """Test that events are correctly separated by asset."""
    # Track events for different assets
    tracker.track_model_creation(asset_id="model-001", base_model="gpt-4")
    tracker.track_model_creation(asset_id="model-002", base_model="claude-3")
    tracker.track_fine_tuning(asset_id="model-001", dataset="dataset-001")
    
    # Get events for model-001
    events_001 = tracker.get_events_for_asset("model-001")
    assert len(events_001) == 2
    assert all(e.asset_id == "model-001" for e in events_001)
    
    # Get events for model-002
    events_002 = tracker.get_events_for_asset("model-002")
    assert len(events_002) == 1
    assert all(e.asset_id == "model-002" for e in events_002)


# ============================================================================
# LINEAGE CHAIN TESTS
# ============================================================================


def test_get_lineage_chain_single_model(tracker, registry, sample_model):
    """Test getting lineage chain for a single model."""
    chain = tracker.get_lineage_chain("model-001")
    
    assert len(chain) == 1
    assert chain[0].asset_id == "model-001"


def test_get_lineage_chain_with_dependencies(tracker, registry):
    """Test getting lineage chain with dependencies."""
    # Create a chain: model-003 -> model-002 -> model-001
    model1 = AIAsset(
        asset_id="model-001",
        asset_type=AssetType.MODEL,
        name="Base Model",
        description="Base model",
        owner="team-ml",
        dependencies=[],
    )
    
    model2 = AIAsset(
        asset_id="model-002",
        asset_type=AssetType.MODEL,
        name="Fine-tuned Model",
        description="Fine-tuned from model-001",
        owner="team-ml",
        dependencies=["model-001"],
    )
    
    model3 = AIAsset(
        asset_id="model-003",
        asset_type=AssetType.MODEL,
        name="Specialized Model",
        description="Specialized from model-002",
        owner="team-ml",
        dependencies=["model-002"],
    )
    
    registry.register(model1)
    registry.register(model2)
    registry.register(model3)
    
    # Get lineage chain for model-003
    chain = tracker.get_lineage_chain("model-003")
    
    assert len(chain) == 3
    assert chain[0].asset_id == "model-001"  # Origin
    assert chain[1].asset_id == "model-002"
    assert chain[2].asset_id == "model-003"  # Current


def test_get_lineage_chain_nonexistent_asset(tracker):
    """Test getting lineage chain for nonexistent asset."""
    chain = tracker.get_lineage_chain("nonexistent-id")
    assert len(chain) == 0


def test_get_lineage_chain_with_missing_dependencies(tracker, registry):
    """Test getting lineage chain when some dependencies are missing."""
    # Create model with dependency that doesn't exist
    model = AIAsset(
        asset_id="model-001",
        asset_type=AssetType.MODEL,
        name="Model",
        description="Model with missing dependency",
        owner="team-ml",
        dependencies=["nonexistent-model"],
    )
    registry.register(model)
    
    # Get lineage chain (should only include existing assets)
    chain = tracker.get_lineage_chain("model-001")
    assert len(chain) == 1
    assert chain[0].asset_id == "model-001"


def test_get_lineage_chain_complex_dependencies(tracker, registry):
    """Test lineage chain with multiple dependencies (takes first)."""
    # Create models with multiple dependencies
    model1 = AIAsset(
        asset_id="model-001",
        asset_type=AssetType.MODEL,
        name="Base Model 1",
        description="Base model 1",
        owner="team-ml",
        dependencies=[],
    )
    
    model2 = AIAsset(
        asset_id="model-002",
        asset_type=AssetType.MODEL,
        name="Base Model 2",
        description="Base model 2",
        owner="team-ml",
        dependencies=[],
    )
    
    model3 = AIAsset(
        asset_id="model-003",
        asset_type=AssetType.MODEL,
        name="Merged Model",
        description="Merged from model-001 and model-002",
        owner="team-ml",
        dependencies=["model-001", "model-002"],  # Multiple dependencies
    )
    
    registry.register(model1)
    registry.register(model2)
    registry.register(model3)
    
    # Get lineage chain (should follow first dependency)
    chain = tracker.get_lineage_chain("model-003")
    assert len(chain) == 2
    assert chain[0].asset_id == "model-001"  # First dependency
    assert chain[1].asset_id == "model-003"


# ============================================================================
# EVENT TIMELINE TESTS
# ============================================================================


def test_event_timeline_ordering(tracker):
    """Test that events are ordered by timestamp."""
    # Track events with small delays to ensure different timestamps
    import time
    
    tracker.track_model_creation(asset_id="model-001", base_model="gpt-4")
    time.sleep(0.01)
    tracker.track_fine_tuning(asset_id="model-001", dataset="dataset-001")
    time.sleep(0.01)
    tracker.track_event(asset_id="model-001", event_type="updated", description="Model updated", metadata={"changes": {"temperature": 0.7}})
    
    events = tracker.get_events_for_asset("model-001")
    
    # Verify events are in reverse chronological order
    assert events[0].timestamp > events[1].timestamp
    assert events[1].timestamp > events[2].timestamp


def test_event_metadata(tracker):
    """Test that event metadata is preserved."""
    metadata = {
        "user": "user-001",
        "environment": "production",
        "version": "1.0",
        "nested": {"key": "value"},
    }
    
    event_id = tracker.track_event(
        asset_id="model-001",
        event_type="deployed",
        description="Deployment",
        metadata=metadata,
    )
    
    event = tracker.get_event(event_id)
    assert event.metadata == metadata
    assert event.metadata["nested"]["key"] == "value"


# ============================================================================
# SERIALIZATION TESTS
# ============================================================================


def test_event_to_dict(tracker):
    """Test converting event to dictionary."""
    event_id = tracker.track_model_creation(
        asset_id="model-001",
        base_model="gpt-4",
        metadata={"version": "1.0"},
    )
    
    event = tracker.get_event(event_id)
    data = event.to_dict()
    
    assert data["event_id"] == event.event_id
    assert data["asset_id"] == event.asset_id
    assert data["event_type"] == event.event_type
    assert data["description"] == event.description
    assert "timestamp" in data
    assert data["metadata"]["version"] == "1.0"


# ============================================================================
# INTEGRATION TESTS
# ============================================================================


def test_full_model_lifecycle(tracker, registry):
    """Test tracking a complete model lifecycle."""
    # 1. Create base model
    base_model = AIAsset(
        asset_id="model-001",
        asset_type=AssetType.MODEL,
        name="Base Model",
        description="GPT-4 base model",
        owner="team-ml",
    )
    registry.register(base_model)
    tracker.track_model_creation(
        asset_id="model-001",
        base_model="gpt-4",
        metadata={"provider": "openai"},
    )
    
    # 2. Fine-tune model
    tracker.track_fine_tuning(
        asset_id="model-001",
        dataset="dataset-001,dataset-002",
        parameters={"epochs": 10, "learning_rate": 0.001},
    )
    
    # 3. Update model parameters
    tracker.track_event(
        asset_id="model-001",
        event_type="updated",
        description="Model parameters updated",
        metadata={"changes": {"temperature": 0.7, "max_tokens": 2000}, "updated_by": "user-001"},
    )
    
    # 4. Deploy model
    tracker.track_event(
        asset_id="model-001",
        event_type="deployed",
        description="Deployed to production",
        metadata={"environment": "production"},
    )
    
    # 5. Deprecate model
    tracker.track_deprecation(
        asset_id="model-001",
        reason="Replaced by model-002",
        replacement_id="model-002",
    )
    
    # Verify complete timeline
    events = tracker.get_events_for_asset("model-001")
    assert len(events) == 5
    
    event_types = [e.event_type for e in reversed(events)]
    assert event_types == ["created", "fine_tuned", "updated", "deployed", "deprecated"]


def test_multiple_models_lifecycle(tracker, registry):
    """Test tracking multiple models with their own lifecycles."""
    # Create and track model-001
    model1 = AIAsset(
        asset_id="model-001",
        asset_type=AssetType.MODEL,
        name="Model 1",
        description="Model 1",
        owner="team-ml",
    )
    registry.register(model1)
    tracker.track_model_creation(asset_id="model-001", base_model="gpt-4")
    tracker.track_fine_tuning(asset_id="model-001", dataset="dataset-001")
    
    # Create and track model-002
    model2 = AIAsset(
        asset_id="model-002",
        asset_type=AssetType.MODEL,
        name="Model 2",
        description="Model 2",
        owner="team-ml",
    )
    registry.register(model2)
    tracker.track_model_creation(asset_id="model-002", base_model="claude-3")
    tracker.track_event(asset_id="model-002", event_type="updated", description="Model updated", metadata={"changes": {"temperature": 0.5}})
    
    # Verify separate timelines
    events_001 = tracker.get_events_for_asset("model-001")
    assert len(events_001) == 2
    assert all(e.asset_id == "model-001" for e in events_001)
    
    events_002 = tracker.get_events_for_asset("model-002")
    assert len(events_002) == 2
    assert all(e.asset_id == "model-002" for e in events_002)
