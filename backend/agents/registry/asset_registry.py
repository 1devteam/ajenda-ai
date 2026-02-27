"""
Asset Registry for AI Governance

Tracks all AI assets (agents, tools, models) with lineage and metadata.
Part of Month 2 Week 1: AIAsset Inventory & Lineage Tracking.

Built with Pride for Obex Blackvault.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any
from uuid import uuid4


class AssetType(Enum):
    """Type of AI asset."""
    AGENT = "agent"
    TOOL = "tool"
    MODEL = "model"
    VECTOR_DB = "vector_db"


class AssetStatus(Enum):
    """Status of AI asset."""
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    ARCHIVED = "archived"
    UNDER_REVIEW = "under_review"


@dataclass
class ModelLineage:
    """
    Lineage information for AI models.
    
    Tracks the provenance of AI models including base model,
    fine-tuning data, and vector database sources.
    """
    base_model: str  # e.g., "gpt-4", "claude-3", "llama-3"
    fine_tuning_data: Optional[List[str]] = None  # Datasets used for fine-tuning
    vector_db_sources: Optional[List[str]] = None  # Knowledge base sources
    training_date: Optional[datetime] = None
    model_version: Optional[str] = None
    parameters: Optional[Dict[str, Any]] = None  # Model parameters (size, context length, etc.)
    
    def __post_init__(self):
        """Initialize empty lists if None."""
        if self.fine_tuning_data is None:
            self.fine_tuning_data = []
        if self.vector_db_sources is None:
            self.vector_db_sources = []
        if self.parameters is None:
            self.parameters = {}


@dataclass
class AIAsset:
    """
    Represents an AI asset in the registry.
    
    An asset can be an agent, tool, model, or vector database.
    Each asset has lineage, metadata, and lifecycle information.
    """
    asset_id: str
    asset_type: AssetType
    name: str
    description: str
    owner: str  # User or team responsible
    status: AssetStatus = AssetStatus.ACTIVE
    lineage: Optional[ModelLineage] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    tags: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)  # Other asset IDs this depends on
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert asset to dictionary for serialization."""
        return {
            "asset_id": self.asset_id,
            "asset_type": self.asset_type.value,
            "name": self.name,
            "description": self.description,
            "owner": self.owner,
            "status": self.status.value,
            "lineage": {
                "base_model": self.lineage.base_model,
                "fine_tuning_data": self.lineage.fine_tuning_data,
                "vector_db_sources": self.lineage.vector_db_sources,
                "training_date": self.lineage.training_date.isoformat() if self.lineage.training_date else None,
                "model_version": self.lineage.model_version,
                "parameters": self.lineage.parameters,
            } if self.lineage else None,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "tags": self.tags,
            "dependencies": self.dependencies,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AIAsset":
        """Create asset from dictionary."""
        lineage = None
        if data.get("lineage"):
            lineage_data = data["lineage"]
            lineage = ModelLineage(
                base_model=lineage_data["base_model"],
                fine_tuning_data=lineage_data.get("fine_tuning_data"),
                vector_db_sources=lineage_data.get("vector_db_sources"),
                training_date=datetime.fromisoformat(lineage_data["training_date"]) if lineage_data.get("training_date") else None,
                model_version=lineage_data.get("model_version"),
                parameters=lineage_data.get("parameters", {}),
            )
        
        return cls(
            asset_id=data["asset_id"],
            asset_type=AssetType(data["asset_type"]),
            name=data["name"],
            description=data["description"],
            owner=data["owner"],
            status=AssetStatus(data.get("status", "active")),
            lineage=lineage,
            metadata=data.get("metadata", {}),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            tags=data.get("tags", []),
            dependencies=data.get("dependencies", []),
        )


class AIAssetRegistry:
    """
    Central registry for all AI assets.
    
    Provides CRUD operations and querying capabilities for AI assets.
    Singleton pattern ensures single source of truth.
    """
    
    _instance: Optional["AIAssetRegistry"] = None
    
    def __new__(cls):
        """Singleton pattern."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        """Initialize registry."""
        if self._initialized:
            return
        
        self._assets: Dict[str, AIAsset] = {}
        self._assets_by_type: Dict[AssetType, List[str]] = {
            asset_type: [] for asset_type in AssetType
        }
        self._assets_by_owner: Dict[str, List[str]] = {}
        self._initialized = True
    
    def register(self, asset: AIAsset) -> str:
        """
        Register a new AI asset.
        
        Args:
            asset: The asset to register
            
        Returns:
            The asset ID
            
        Raises:
            ValueError: If asset with same ID already exists
        """
        if asset.asset_id in self._assets:
            raise ValueError(f"Asset with ID {asset.asset_id} already exists")
        
        # Store asset
        self._assets[asset.asset_id] = asset
        
        # Update indices
        self._assets_by_type[asset.asset_type].append(asset.asset_id)
        
        if asset.owner not in self._assets_by_owner:
            self._assets_by_owner[asset.owner] = []
        self._assets_by_owner[asset.owner].append(asset.asset_id)
        
        return asset.asset_id
    
    def get(self, asset_id: str) -> Optional[AIAsset]:
        """
        Get an asset by ID.
        
        Args:
            asset_id: The asset ID
            
        Returns:
            The asset, or None if not found
        """
        return self._assets.get(asset_id)
    
    def update(self, asset_id: str, **kwargs) -> bool:
        """
        Update an asset.
        
        Args:
            asset_id: The asset ID
            **kwargs: Fields to update
            
        Returns:
            True if updated, False if not found
        """
        asset = self._assets.get(asset_id)
        if not asset:
            return False
        
        # Update fields
        for key, value in kwargs.items():
            if hasattr(asset, key):
                setattr(asset, key, value)
        
        # Update timestamp
        asset.updated_at = datetime.now()
        
        return True
    
    def delete(self, asset_id: str) -> bool:
        """
        Delete an asset.
        
        Args:
            asset_id: The asset ID
            
        Returns:
            True if deleted, False if not found
        """
        asset = self._assets.get(asset_id)
        if not asset:
            return False
        
        # Remove from indices
        self._assets_by_type[asset.asset_type].remove(asset_id)
        self._assets_by_owner[asset.owner].remove(asset_id)
        
        # Remove asset
        del self._assets[asset_id]
        
        return True
    
    def list_all(self) -> List[AIAsset]:
        """
        List all assets.
        
        Returns:
            List of all assets
        """
        return list(self._assets.values())
    
    def list_by_type(self, asset_type: AssetType) -> List[AIAsset]:
        """
        List assets by type.
        
        Args:
            asset_type: The asset type
            
        Returns:
            List of assets of the specified type
        """
        asset_ids = self._assets_by_type.get(asset_type, [])
        return [self._assets[asset_id] for asset_id in asset_ids]
    
    def list_by_owner(self, owner: str) -> List[AIAsset]:
        """
        List assets by owner.
        
        Args:
            owner: The owner
            
        Returns:
            List of assets owned by the specified owner
        """
        asset_ids = self._assets_by_owner.get(owner, [])
        return [self._assets[asset_id] for asset_id in asset_ids]
    
    def list_by_status(self, status: AssetStatus) -> List[AIAsset]:
        """
        List assets by status.
        
        Args:
            status: The status
            
        Returns:
            List of assets with the specified status
        """
        return [asset for asset in self._assets.values() if asset.status == status]
    
    def list_by_tag(self, tag: str) -> List[AIAsset]:
        """
        List assets by tag.
        
        Args:
            tag: The tag
            
        Returns:
            List of assets with the specified tag
        """
        return [asset for asset in self._assets.values() if tag in asset.tags]
    
    def search(
        self,
        asset_type: Optional[AssetType] = None,
        owner: Optional[str] = None,
        status: Optional[AssetStatus] = None,
        tags: Optional[List[str]] = None,
        name_contains: Optional[str] = None,
    ) -> List[AIAsset]:
        """
        Search assets with multiple filters.
        
        Args:
            asset_type: Filter by asset type
            owner: Filter by owner
            status: Filter by status
            tags: Filter by tags (asset must have all specified tags)
            name_contains: Filter by name (case-insensitive substring match)
            
        Returns:
            List of assets matching all filters
        """
        results = list(self._assets.values())
        
        if asset_type:
            results = [a for a in results if a.asset_type == asset_type]
        
        if owner:
            results = [a for a in results if a.owner == owner]
        
        if status:
            results = [a for a in results if a.status == status]
        
        if tags:
            results = [a for a in results if all(tag in a.tags for tag in tags)]
        
        if name_contains:
            name_lower = name_contains.lower()
            results = [a for a in results if name_lower in a.name.lower()]
        
        return results
    
    def get_lineage(self, asset_id: str) -> Optional[ModelLineage]:
        """
        Get lineage for an asset.
        
        Args:
            asset_id: The asset ID
            
        Returns:
            The lineage, or None if asset not found or has no lineage
        """
        asset = self._assets.get(asset_id)
        return asset.lineage if asset else None
    
    def get_dependencies(self, asset_id: str, recursive: bool = False) -> List[AIAsset]:
        """
        Get dependencies for an asset.
        
        Args:
            asset_id: The asset ID
            recursive: If True, get all transitive dependencies
            
        Returns:
            List of dependent assets
        """
        asset = self._assets.get(asset_id)
        if not asset:
            return []
        
        dependencies = []
        for dep_id in asset.dependencies:
            dep_asset = self._assets.get(dep_id)
            if dep_asset:
                dependencies.append(dep_asset)
                
                if recursive:
                    # Get transitive dependencies
                    transitive = self.get_dependencies(dep_id, recursive=True)
                    dependencies.extend(transitive)
        
        # Remove duplicates
        seen = set()
        unique_deps = []
        for dep in dependencies:
            if dep.asset_id not in seen:
                seen.add(dep.asset_id)
                unique_deps.append(dep)
        
        return unique_deps
    
    def get_dependents(self, asset_id: str) -> List[AIAsset]:
        """
        Get assets that depend on this asset.
        
        Args:
            asset_id: The asset ID
            
        Returns:
            List of assets that depend on this asset
        """
        dependents = []
        for asset in self._assets.values():
            if asset_id in asset.dependencies:
                dependents.append(asset)
        return dependents
    
    def clear(self):
        """Clear all assets (for testing)."""
        self._assets.clear()
        for asset_type in AssetType:
            self._assets_by_type[asset_type].clear()
        self._assets_by_owner.clear()


# Global registry instance
_registry = AIAssetRegistry()


def get_registry() -> AIAssetRegistry:
    """Get the global asset registry instance."""
    return _registry
