"""
Tests for Asset Registry

Comprehensive test coverage for AIAssetRegistry.
Part of Month 2 Week 1: Asset Inventory & Lineage Tracking.

Built with Pride for Obex Blackvault.
"""

import pytest
from datetime import datetime
from backend.agents.registry.asset_registry import (
    AIAsset,
    AssetType,
    AssetStatus,
    ModelLineage,
    AIAssetRegistry,
)


@pytest.fixture(autouse=True, scope="function")
def clear_registry():
    """Clear registry before and after each test."""
    from backend.agents.registry.asset_registry import get_registry
    reg = get_registry()
    # Clear before test
    reg._assets.clear()
    yield
    # Clear after test
    reg._assets.clear()


@pytest.fixture
def registry():
    """Get the registry instance."""
    from backend.agents.registry.asset_registry import get_registry
    return get_registry()


@pytest.fixture
def sample_agent():
    """Create a sample agent asset."""
    return AIAsset(
        asset_id="agent-001",
        asset_type=AssetType.AGENT,
        name="Research Agent",
        description="Agent for research tasks",
        owner="team-research",
        status=AssetStatus.ACTIVE,
        metadata={"version": "1.0", "capabilities": ["search", "summarize"]},
        tags=["research", "production"],
        dependencies=["tool-001", "model-001"],
    )


@pytest.fixture
def sample_tool():
    """Create a sample tool asset."""
    return AIAsset(
        asset_id="tool-001",
        asset_type=AssetType.TOOL,
        name="Web Search",
        description="Search the web for information",
        owner="team-platform",
        status=AssetStatus.ACTIVE,
        metadata={"api_version": "v2"},
        tags=["search", "external"],
        dependencies=[],
    )


@pytest.fixture
def sample_model():
    """Create a sample model asset with lineage."""
    lineage = ModelLineage(
        base_model="gpt-4",
        fine_tuning_data=["dataset-001", "dataset-002"],
        vector_db_sources=["vectordb-001"],
        training_date=datetime(2026, 1, 15),
        model_version="1.0.0",
        parameters={"temperature": 0.7, "max_tokens": 2000},
    )
    return AIAsset(
        asset_id="model-001",
        asset_type=AssetType.MODEL,
        name="Research Model",
        description="Fine-tuned model for research tasks",
        owner="team-ml",
        status=AssetStatus.ACTIVE,
        lineage=lineage,
        metadata={"provider": "openai"},
        tags=["fine-tuned", "production"],
        dependencies=["vectordb-001"],
    )


# ============================================================================
# REGISTRATION TESTS
# ============================================================================


def test_register_asset(registry, sample_agent):
    """Test registering a new asset."""
    registry.register(sample_agent)
    
    # Verify asset is registered
    asset = registry.get(sample_agent.asset_id)
    assert asset is not None
    assert asset.asset_id == sample_agent.asset_id
    assert asset.name == sample_agent.name
    assert asset.asset_type == AssetType.AGENT


def test_register_duplicate_asset(registry, sample_agent):
    """Test that registering a duplicate asset raises an error."""
    registry.register(sample_agent)
    
    with pytest.raises(ValueError, match="already exists"):
        registry.register(sample_agent)


def test_register_multiple_assets(registry, sample_agent, sample_tool, sample_model):
    """Test registering multiple assets."""
    registry.register(sample_agent)
    registry.register(sample_tool)
    registry.register(sample_model)
    
    # Verify all assets are registered
    assert registry.get(sample_agent.asset_id) is not None
    assert registry.get(sample_tool.asset_id) is not None
    assert registry.get(sample_model.asset_id) is not None


# ============================================================================
# RETRIEVAL TESTS
# ============================================================================


def test_get_existing_asset(registry, sample_agent):
    """Test retrieving an existing asset."""
    registry.register(sample_agent)
    
    asset = registry.get(sample_agent.asset_id)
    assert asset is not None
    assert asset.asset_id == sample_agent.asset_id


def test_get_nonexistent_asset(registry):
    """Test retrieving a nonexistent asset returns None."""
    asset = registry.get("nonexistent-id")
    assert asset is None


def test_list_all_assets(registry, sample_agent, sample_tool, sample_model):
    """Test listing all assets."""
    registry.register(sample_agent)
    registry.register(sample_tool)
    registry.register(sample_model)
    
    assets = registry.list_all()
    assert len(assets) == 3
    
    asset_ids = {asset.asset_id for asset in assets}
    assert sample_agent.asset_id in asset_ids
    assert sample_tool.asset_id in asset_ids
    assert sample_model.asset_id in asset_ids


def test_list_by_type(registry, sample_agent, sample_tool, sample_model):
    """Test listing assets by type."""
    registry.register(sample_agent)
    registry.register(sample_tool)
    registry.register(sample_model)
    
    # List agents
    agents = registry.list_by_type(AssetType.AGENT)
    assert len(agents) == 1
    assert agents[0].asset_id == sample_agent.asset_id
    
    # List tools
    tools = registry.list_by_type(AssetType.TOOL)
    assert len(tools) == 1
    assert tools[0].asset_id == sample_tool.asset_id
    
    # List models
    models = registry.list_by_type(AssetType.MODEL)
    assert len(models) == 1
    assert models[0].asset_id == sample_model.asset_id


def test_list_by_owner(registry, sample_agent, sample_tool):
    """Test listing assets by owner."""
    registry.register(sample_agent)
    registry.register(sample_tool)
    
    # List assets owned by team-research
    research_assets = registry.list_by_owner("team-research")
    assert len(research_assets) == 1
    assert research_assets[0].asset_id == sample_agent.asset_id
    
    # List assets owned by team-platform
    platform_assets = registry.list_by_owner("team-platform")
    assert len(platform_assets) == 1
    assert platform_assets[0].asset_id == sample_tool.asset_id


def test_list_by_status(registry, sample_agent):
    """Test listing assets by status."""
    registry.register(sample_agent)
    
    # Create a deprecated asset
    deprecated_asset = AIAsset(
        asset_id="agent-002",
        asset_type=AssetType.AGENT,
        name="Old Agent",
        description="Deprecated agent",
        owner="team-research",
        status=AssetStatus.DEPRECATED,
    )
    registry.register(deprecated_asset)
    
    # List active assets
    active_assets = registry.list_by_status(AssetStatus.ACTIVE)
    assert len(active_assets) == 1
    assert active_assets[0].asset_id == sample_agent.asset_id
    
    # List deprecated assets
    deprecated_assets = registry.list_by_status(AssetStatus.DEPRECATED)
    assert len(deprecated_assets) == 1
    assert deprecated_assets[0].asset_id == deprecated_asset.asset_id


# ============================================================================
# UPDATE TESTS
# ============================================================================


def test_update_asset(registry, sample_agent):
    """Test updating an asset."""
    registry.register(sample_agent)
    
    # Update asset
    success = registry.update(
        sample_agent.asset_id,
        name="Updated Agent",
        description="Updated description",
        status=AssetStatus.DEPRECATED,
    )
    assert success is True
    
    # Verify updates
    asset = registry.get(sample_agent.asset_id)
    assert asset.name == "Updated Agent"
    assert asset.description == "Updated description"
    assert asset.status == AssetStatus.DEPRECATED


def test_update_nonexistent_asset(registry):
    """Test updating a nonexistent asset returns False."""
    success = registry.update("nonexistent-id", name="New Name")
    assert success is False


def test_update_metadata(registry, sample_agent):
    """Test updating asset metadata."""
    registry.register(sample_agent)
    
    # Update metadata
    new_metadata = {"version": "2.0", "capabilities": ["search", "summarize", "analyze"]}
    success = registry.update(sample_agent.asset_id, metadata=new_metadata)
    assert success is True
    
    # Verify metadata update
    asset = registry.get(sample_agent.asset_id)
    assert asset.metadata == new_metadata


def test_update_tags(registry, sample_agent):
    """Test updating asset tags."""
    registry.register(sample_agent)
    
    # Update tags
    new_tags = ["research", "production", "v2"]
    success = registry.update(sample_agent.asset_id, tags=new_tags)
    assert success is True
    
    # Verify tags update
    asset = registry.get(sample_agent.asset_id)
    assert asset.tags == new_tags


def test_update_dependencies(registry, sample_agent):
    """Test updating asset dependencies."""
    registry.register(sample_agent)
    
    # Update dependencies
    new_dependencies = ["tool-001", "tool-002", "model-001"]
    success = registry.update(sample_agent.asset_id, dependencies=new_dependencies)
    assert success is True
    
    # Verify dependencies update
    asset = registry.get(sample_agent.asset_id)
    assert asset.dependencies == new_dependencies


# ============================================================================
# DELETE TESTS
# ============================================================================


def test_delete_asset(registry, sample_agent):
    """Test deleting an asset."""
    registry.register(sample_agent)
    
    # Delete asset
    success = registry.delete(sample_agent.asset_id)
    assert success is True
    
    # Verify asset is deleted
    asset = registry.get(sample_agent.asset_id)
    assert asset is None


def test_delete_nonexistent_asset(registry):
    """Test deleting a nonexistent asset returns False."""
    success = registry.delete("nonexistent-id")
    assert success is False


# ============================================================================
# SEARCH TESTS
# ============================================================================


def test_search_by_type(registry, sample_agent, sample_tool):
    """Test searching assets by type."""
    registry.register(sample_agent)
    registry.register(sample_tool)
    
    # Search for agents
    agents = registry.search(asset_type=AssetType.AGENT)
    assert len(agents) == 1
    assert agents[0].asset_id == sample_agent.asset_id


def test_search_by_owner(registry, sample_agent, sample_tool):
    """Test searching assets by owner."""
    registry.register(sample_agent)
    registry.register(sample_tool)
    
    # Search for team-research assets
    research_assets = registry.search(owner="team-research")
    assert len(research_assets) == 1
    assert research_assets[0].asset_id == sample_agent.asset_id


def test_search_by_status(registry, sample_agent):
    """Test searching assets by status."""
    registry.register(sample_agent)
    
    # Create a deprecated asset
    deprecated_asset = AIAsset(
        asset_id="agent-002",
        asset_type=AssetType.AGENT,
        name="Old Agent",
        description="Deprecated agent",
        owner="team-research",
        status=AssetStatus.DEPRECATED,
    )
    registry.register(deprecated_asset)
    
    # Search for active assets
    active_assets = registry.search(status=AssetStatus.ACTIVE)
    assert len(active_assets) == 1
    assert active_assets[0].asset_id == sample_agent.asset_id


def test_search_by_tags(registry, sample_agent, sample_tool):
    """Test searching assets by tags."""
    registry.register(sample_agent)
    registry.register(sample_tool)
    
    # Search for assets with "research" tag
    research_assets = registry.search(tags=["research"])
    assert len(research_assets) == 1
    assert research_assets[0].asset_id == sample_agent.asset_id
    
    # Search for assets with "production" tag
    production_assets = registry.search(tags=["production"])
    assert len(production_assets) == 1
    assert production_assets[0].asset_id == sample_agent.asset_id
    
    # Search for assets with both tags (AND logic)
    both_tags_assets = registry.search(tags=["research", "production"])
    assert len(both_tags_assets) == 1
    assert both_tags_assets[0].asset_id == sample_agent.asset_id


def test_search_by_name_contains(registry, sample_agent, sample_tool):
    """Test searching assets by name substring."""
    registry.register(sample_agent)
    registry.register(sample_tool)
    
    # Search for assets with "Research" in name
    research_assets = registry.search(name_contains="Research")
    assert len(research_assets) == 1
    assert research_assets[0].asset_id == sample_agent.asset_id
    
    # Search for assets with "Web" in name
    web_assets = registry.search(name_contains="Web")
    assert len(web_assets) == 1
    assert web_assets[0].asset_id == sample_tool.asset_id
    
    # Search is case-insensitive
    lowercase_assets = registry.search(name_contains="research")
    assert len(lowercase_assets) == 1
    assert lowercase_assets[0].asset_id == sample_agent.asset_id


def test_search_combined_filters(registry, sample_agent, sample_tool, sample_model):
    """Test searching with multiple filters."""
    registry.register(sample_agent)
    registry.register(sample_tool)
    registry.register(sample_model)
    
    # Search for active agents owned by team-research
    results = registry.search(
        asset_type=AssetType.AGENT,
        owner="team-research",
        status=AssetStatus.ACTIVE,
    )
    assert len(results) == 1
    assert results[0].asset_id == sample_agent.asset_id
    
    # Search for production assets with "research" in name
    results = registry.search(
        tags=["production"],
        name_contains="research",
    )
    assert len(results) == 2  # agent and model


# ============================================================================
# DEPENDENCY TESTS
# ============================================================================


def test_get_dependencies(registry, sample_agent, sample_tool, sample_model):
    """Test getting asset dependencies."""
    registry.register(sample_agent)
    registry.register(sample_tool)
    registry.register(sample_model)
    
    # Get agent dependencies (non-recursive)
    dependencies = registry.get_dependencies(sample_agent.asset_id, recursive=False)
    assert len(dependencies) == 2
    
    dep_ids = {dep.asset_id for dep in dependencies}
    assert "tool-001" in dep_ids
    assert "model-001" in dep_ids


def test_get_dependencies_recursive(registry):
    """Test getting transitive dependencies."""
    # Create a dependency chain: agent -> tool -> model
    model = AIAsset(
        asset_id="model-001",
        asset_type=AssetType.MODEL,
        name="Base Model",
        description="Base model",
        owner="team-ml",
        dependencies=[],
    )
    
    tool = AIAsset(
        asset_id="tool-001",
        asset_type=AssetType.TOOL,
        name="Tool",
        description="Tool that uses model",
        owner="team-platform",
        dependencies=["model-001"],
    )
    
    agent = AIAsset(
        asset_id="agent-001",
        asset_type=AssetType.AGENT,
        name="Agent",
        description="Agent that uses tool",
        owner="team-research",
        dependencies=["tool-001"],
    )
    
    registry.register(model)
    registry.register(tool)
    registry.register(agent)
    
    # Get recursive dependencies
    dependencies = registry.get_dependencies(agent.asset_id, recursive=True)
    assert len(dependencies) == 2
    
    dep_ids = {dep.asset_id for dep in dependencies}
    assert "tool-001" in dep_ids
    assert "model-001" in dep_ids


def test_get_dependents(registry):
    """Test getting assets that depend on this asset."""
    # Create assets with dependencies
    tool = AIAsset(
        asset_id="tool-001",
        asset_type=AssetType.TOOL,
        name="Tool",
        description="Tool",
        owner="team-platform",
        dependencies=[],
    )
    
    agent1 = AIAsset(
        asset_id="agent-001",
        asset_type=AssetType.AGENT,
        name="Agent 1",
        description="Agent 1",
        owner="team-research",
        dependencies=["tool-001"],
    )
    
    agent2 = AIAsset(
        asset_id="agent-002",
        asset_type=AssetType.AGENT,
        name="Agent 2",
        description="Agent 2",
        owner="team-research",
        dependencies=["tool-001"],
    )
    
    registry.register(tool)
    registry.register(agent1)
    registry.register(agent2)
    
    # Get dependents of tool
    dependents = registry.get_dependents(tool.asset_id)
    assert len(dependents) == 2
    
    dependent_ids = {dep.asset_id for dep in dependents}
    assert "agent-001" in dependent_ids
    assert "agent-002" in dependent_ids


def test_get_dependencies_missing_asset(registry, sample_agent):
    """Test getting dependencies when some dependencies are missing."""
    # Register agent with dependencies that don't exist
    registry.register(sample_agent)
    
    # Get dependencies (should only return existing ones)
    dependencies = registry.get_dependencies(sample_agent.asset_id)
    assert len(dependencies) == 0  # None of the dependencies exist


# ============================================================================
# LINEAGE TESTS
# ============================================================================


def test_get_lineage(registry, sample_model):
    """Test getting model lineage."""
    registry.register(sample_model)
    
    lineage = registry.get_lineage(sample_model.asset_id)
    assert lineage is not None
    assert lineage.base_model == "gpt-4"
    assert len(lineage.fine_tuning_data) == 2
    assert len(lineage.vector_db_sources) == 1
    assert lineage.model_version == "1.0.0"


def test_get_lineage_no_lineage(registry, sample_agent):
    """Test getting lineage for asset without lineage."""
    registry.register(sample_agent)
    
    lineage = registry.get_lineage(sample_agent.asset_id)
    assert lineage is None


def test_get_lineage_nonexistent_asset(registry):
    """Test getting lineage for nonexistent asset."""
    lineage = registry.get_lineage("nonexistent-id")
    assert lineage is None


# ============================================================================
# SERIALIZATION TESTS
# ============================================================================


def test_asset_to_dict(sample_agent):
    """Test converting asset to dictionary."""
    data = sample_agent.to_dict()
    
    assert data["asset_id"] == sample_agent.asset_id
    assert data["asset_type"] == sample_agent.asset_type.value
    assert data["name"] == sample_agent.name
    assert data["description"] == sample_agent.description
    assert data["owner"] == sample_agent.owner
    assert data["status"] == sample_agent.status.value
    assert data["metadata"] == sample_agent.metadata
    assert data["tags"] == sample_agent.tags
    assert data["dependencies"] == sample_agent.dependencies
    assert "created_at" in data
    assert "updated_at" in data



