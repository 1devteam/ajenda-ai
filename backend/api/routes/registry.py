"""
Asset Registry API Endpoints

REST API for managing AI assets (agents, tools, models, vector DBs).
Part of Month 2 Week 1: AIAsset Inventory & Lineage Tracking.

Built with Pride for Obex Blackvault.
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime

from backend.agents.registry.asset_registry import (
    AIAsset,
    AssetType,
    AssetStatus,
    ModelLineage,
    get_registry,
)
from backend.agents.registry.lineage_tracker import (
    get_tracker,
)


router = APIRouter(prefix="/api/v1/registry", tags=["registry"])


# ============================================================================
# REQUEST/RESPONSE MODELS
# ============================================================================


class ModelLineageRequest(BaseModel):
    """Request model for model lineage."""

    base_model: str = Field(..., description="Base model name (e.g., 'gpt-4', 'claude-3')")
    fine_tuning_data: Optional[List[str]] = Field(None, description="Datasets used for fine-tuning")
    vector_db_sources: Optional[List[str]] = Field(None, description="Knowledge base sources")
    training_date: Optional[datetime] = Field(None, description="Training date")
    model_version: Optional[str] = Field(None, description="Model version")
    parameters: Optional[Dict[str, Any]] = Field(None, description="Model parameters")


class AssetCreateRequest(BaseModel):
    """Request model for creating an asset."""

    asset_id: str = Field(..., description="Unique asset identifier")
    asset_type: str = Field(..., description="Asset type (agent, tool, model, vector_db)")
    name: str = Field(..., description="Asset name")
    description: str = Field(..., description="Asset description")
    owner: str = Field(..., description="Owner (user or team)")
    status: str = Field(default="active", description="Asset status")
    lineage: Optional[ModelLineageRequest] = Field(None, description="Model lineage (for models)")
    metadata: Optional[Dict[str, Any]] = Field(
        default_factory=dict, description="Additional metadata"
    )
    tags: Optional[List[str]] = Field(default_factory=list, description="Tags")
    dependencies: Optional[List[str]] = Field(
        default_factory=list, description="Dependent asset IDs"
    )


class AssetUpdateRequest(BaseModel):
    """Request model for updating an asset."""

    name: Optional[str] = Field(None, description="Asset name")
    description: Optional[str] = Field(None, description="Asset description")
    owner: Optional[str] = Field(None, description="Owner")
    status: Optional[str] = Field(None, description="Asset status")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata")
    tags: Optional[List[str]] = Field(None, description="Tags")
    dependencies: Optional[List[str]] = Field(None, description="Dependent asset IDs")


class AssetResponse(BaseModel):
    """Response model for asset."""

    asset_id: str
    asset_type: str
    name: str
    description: str
    owner: str
    status: str
    lineage: Optional[Dict[str, Any]]
    metadata: Dict[str, Any]
    created_at: str
    updated_at: str
    tags: List[str]
    dependencies: List[str]


class LineageEventRequest(BaseModel):
    """Request model for lineage event."""

    asset_id: str = Field(..., description="Asset ID")
    event_type: str = Field(..., description="Event type")
    description: str = Field(..., description="Event description")
    metadata: Optional[Dict[str, Any]] = Field(
        default_factory=dict, description="Additional metadata"
    )


class LineageEventResponse(BaseModel):
    """Response model for lineage event."""

    event_id: str
    asset_id: str
    event_type: str
    description: str
    timestamp: str
    metadata: Dict[str, Any]


# ============================================================================
# ASSET CRUD ENDPOINTS
# ============================================================================


@router.post("/assets", response_model=AssetResponse, status_code=201)
async def create_asset(request: AssetCreateRequest):
    """
    Register a new AI asset.

    Creates a new asset in the registry with the specified properties.
    All agents, tools, and models must be registered before use.
    """
    registry = get_registry()

    try:
        # Convert lineage if provided
        lineage = None
        if request.lineage:
            lineage = ModelLineage(
                base_model=request.lineage.base_model,
                fine_tuning_data=request.lineage.fine_tuning_data,
                vector_db_sources=request.lineage.vector_db_sources,
                training_date=request.lineage.training_date,
                model_version=request.lineage.model_version,
                parameters=request.lineage.parameters,
            )

        # Create asset
        asset = AIAsset(
            asset_id=request.asset_id,
            asset_type=AssetType(request.asset_type),
            name=request.name,
            description=request.description,
            owner=request.owner,
            status=AssetStatus(request.status),
            lineage=lineage,
            metadata=request.metadata or {},
            tags=request.tags or [],
            dependencies=request.dependencies or [],
        )

        # Register asset
        registry.register(asset)

        # Track creation event
        tracker = get_tracker()
        tracker.track_model_creation(
            asset_id=asset.asset_id,
            base_model=lineage.base_model if lineage else "N/A",
            metadata={"asset_type": asset.asset_type.value},
        )

        return AssetResponse(**asset.to_dict())

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/assets/{asset_id}", response_model=AssetResponse)
async def get_asset(asset_id: str):
    """
    Get an asset by ID.

    Returns the asset details including lineage, metadata, and dependencies.
    """
    registry = get_registry()
    asset = registry.get(asset_id)

    if not asset:
        raise HTTPException(status_code=404, detail=f"Asset '{asset_id}' not found")

    return AssetResponse(**asset.to_dict())


@router.put("/assets/{asset_id}", response_model=AssetResponse)
async def update_asset(asset_id: str, request: AssetUpdateRequest):
    """
    Update an asset.

    Updates the specified fields of an asset. Only provided fields are updated.
    """
    registry = get_registry()

    # Build update dict
    updates = {}
    if request.name is not None:
        updates["name"] = request.name
    if request.description is not None:
        updates["description"] = request.description
    if request.owner is not None:
        updates["owner"] = request.owner
    if request.status is not None:
        updates["status"] = AssetStatus(request.status)
    if request.metadata is not None:
        updates["metadata"] = request.metadata
    if request.tags is not None:
        updates["tags"] = request.tags
    if request.dependencies is not None:
        updates["dependencies"] = request.dependencies

    success = registry.update(asset_id, **updates)

    if not success:
        raise HTTPException(status_code=404, detail=f"Asset '{asset_id}' not found")

    # Track update event
    tracker = get_tracker()
    tracker.track_event(
        asset_id=asset_id,
        event_type="updated",
        description=f"Asset updated: {', '.join(updates.keys())}",
        metadata=updates,
    )

    asset = registry.get(asset_id)
    return AssetResponse(**asset.to_dict())


@router.delete("/assets/{asset_id}", status_code=204)
async def delete_asset(asset_id: str):
    """
    Delete an asset.

    Removes the asset from the registry. This action cannot be undone.
    """
    registry = get_registry()
    success = registry.delete(asset_id)

    if not success:
        raise HTTPException(status_code=404, detail=f"Asset '{asset_id}' not found")

    return None


# ============================================================================
# ASSET QUERY ENDPOINTS
# ============================================================================


@router.get("/assets", response_model=List[AssetResponse])
async def list_assets(
    asset_type: Optional[str] = Query(None, description="Filter by asset type"),
    owner: Optional[str] = Query(None, description="Filter by owner"),
    status: Optional[str] = Query(None, description="Filter by status"),
    tags: Optional[List[str]] = Query(None, description="Filter by tags (must have all)"),
    name_contains: Optional[str] = Query(None, description="Filter by name (substring match)"),
):
    """
    List assets with optional filters.

    Returns a list of assets matching the specified filters.
    If no filters are provided, returns all assets.
    """
    registry = get_registry()

    # Convert string parameters to enums
    asset_type_enum = AssetType(asset_type) if asset_type else None
    status_enum = AssetStatus(status) if status else None

    # Search assets
    assets = registry.search(
        asset_type=asset_type_enum,
        owner=owner,
        status=status_enum,
        tags=tags,
        name_contains=name_contains,
    )

    return [AssetResponse(**asset.to_dict()) for asset in assets]


@router.get("/assets/{asset_id}/dependencies", response_model=List[AssetResponse])
async def get_dependencies(
    asset_id: str,
    recursive: bool = Query(False, description="Get transitive dependencies"),
):
    """
    Get dependencies for an asset.

    Returns the list of assets that this asset depends on.
    If recursive=true, returns all transitive dependencies.
    """
    registry = get_registry()
    asset = registry.get(asset_id)

    if not asset:
        raise HTTPException(status_code=404, detail=f"Asset '{asset_id}' not found")

    dependencies = registry.get_dependencies(asset_id, recursive=recursive)

    return [AssetResponse(**dep.to_dict()) for dep in dependencies]


@router.get("/assets/{asset_id}/dependents", response_model=List[AssetResponse])
async def get_dependents(asset_id: str):
    """
    Get assets that depend on this asset.

    Returns the list of assets that have this asset as a dependency.
    """
    registry = get_registry()
    asset = registry.get(asset_id)

    if not asset:
        raise HTTPException(status_code=404, detail=f"Asset '{asset_id}' not found")

    dependents = registry.get_dependents(asset_id)

    return [AssetResponse(**dep.to_dict()) for dep in dependents]


# ============================================================================
# LINEAGE ENDPOINTS
# ============================================================================


@router.get("/assets/{asset_id}/lineage", response_model=Dict[str, Any])
async def get_lineage(asset_id: str):
    """
    Get lineage for an asset.

    Returns the model lineage information including base model,
    fine-tuning data, and vector database sources.
    """
    registry = get_registry()
    lineage = registry.get_lineage(asset_id)

    if not lineage:
        raise HTTPException(status_code=404, detail=f"No lineage found for asset '{asset_id}'")

    return {
        "base_model": lineage.base_model,
        "fine_tuning_data": lineage.fine_tuning_data,
        "vector_db_sources": lineage.vector_db_sources,
        "training_date": (lineage.training_date.isoformat() if lineage.training_date else None),
        "model_version": lineage.model_version,
        "parameters": lineage.parameters,
    }


@router.get("/assets/{asset_id}/lineage/chain", response_model=List[AssetResponse])
async def get_lineage_chain(asset_id: str):
    """
    Get the full lineage chain for an asset.

    Traces back through dependencies to find the origin.
    Returns the chain from origin to current asset.
    """
    tracker = get_tracker()
    chain = tracker.get_lineage_chain(asset_id)

    if not chain:
        raise HTTPException(status_code=404, detail=f"Asset '{asset_id}' not found")

    return [AssetResponse(**asset.to_dict()) for asset in chain]


@router.get("/assets/{asset_id}/events", response_model=List[LineageEventResponse])
async def get_lineage_events(asset_id: str):
    """
    Get lineage events for an asset.

    Returns the timeline of events (created, fine-tuned, updated, deprecated)
    for the specified asset, sorted by timestamp (newest first).
    """
    tracker = get_tracker()
    events = tracker.get_events_for_asset(asset_id)

    return [LineageEventResponse(**event.to_dict()) for event in events]


@router.post("/events", response_model=LineageEventResponse, status_code=201)
async def create_lineage_event(request: LineageEventRequest):
    """
    Track a lineage event.

    Creates a new event in the lineage timeline for an asset.
    """
    tracker = get_tracker()

    event_id = tracker.track_event(
        asset_id=request.asset_id,
        event_type=request.event_type,
        description=request.description,
        metadata=request.metadata,
    )

    event = tracker.get_event(event_id)
    return LineageEventResponse(**event.to_dict())


# ============================================================================
# STATISTICS ENDPOINTS
# ============================================================================


@router.get("/stats", response_model=Dict[str, Any])
async def get_registry_stats():
    """
    Get registry statistics.

    Returns aggregate statistics about assets in the registry.
    """
    registry = get_registry()

    # Count by type
    type_counts = {}
    for asset_type in AssetType:
        assets = registry.list_by_type(asset_type)
        type_counts[asset_type.value] = len(assets)

    # Count by status
    status_counts = {}
    for status in AssetStatus:
        assets = registry.list_by_status(status)
        status_counts[status.value] = len(assets)

    # Total assets
    total_assets = len(registry.list_all())

    # Top owners
    all_assets = registry.list_all()
    owner_counts = {}
    for asset in all_assets:
        owner_counts[asset.owner] = owner_counts.get(asset.owner, 0) + 1
    top_owners = sorted(owner_counts.items(), key=lambda x: x[1], reverse=True)[:10]

    return {
        "total_assets": total_assets,
        "by_type": type_counts,
        "by_status": status_counts,
        "top_owners": [{"owner": owner, "count": count} for owner, count in top_owners],
    }
