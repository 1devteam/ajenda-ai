"""
Tenants API Routes
Handles tenant/organization management

Built with Pride for Obex Blackvault
"""
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
import uuid

router = APIRouter(prefix="/api/v1/tenants", tags=["tenants"])


# ============================================================================
# Request/Response Models
# ============================================================================

class TenantCreate(BaseModel):
    """Schema for creating a new tenant"""
    name: str = Field(..., min_length=1, max_length=100, description="Tenant name")
    description: Optional[str] = Field(None, max_length=500, description="Tenant description")


class TenantUpdate(BaseModel):
    """Schema for updating a tenant"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    is_active: Optional[bool] = None


class TenantResponse(BaseModel):
    """Tenant response model"""
    id: str
    name: str
    description: Optional[str] = None
    is_active: bool = True
    created_at: datetime
    updated_at: datetime
    agent_count: int = 0
    mission_count: int = 0


# ============================================================================
# In-Memory Storage (Replace with database in production)
# ============================================================================

_tenants_db: dict[str, dict] = {}


# ============================================================================
# API Endpoints
# ============================================================================

@router.post("", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
async def create_tenant(tenant: TenantCreate):
    """
    Create a new tenant
    
    Creates a new tenant/organization in the system.
    """
    tenant_id = f"tenant_{uuid.uuid4().hex[:12]}"
    now = datetime.utcnow()
    
    tenant_data = {
        "id": tenant_id,
        "name": tenant.name,
        "description": tenant.description,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
        "agent_count": 0,
        "mission_count": 0
    }
    
    _tenants_db[tenant_id] = tenant_data
    
    return TenantResponse(**tenant_data)


@router.get("/{tenant_id}", response_model=TenantResponse)
async def get_tenant(tenant_id: str):
    """
    Get tenant by ID
    
    Retrieves a specific tenant's information.
    """
    if tenant_id not in _tenants_db:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant {tenant_id} not found"
        )
    
    return TenantResponse(**_tenants_db[tenant_id])


@router.get("", response_model=List[TenantResponse])
async def list_tenants(
    skip: int = 0,
    limit: int = 100,
    is_active: Optional[bool] = None
):
    """
    List all tenants
    
    Returns a list of tenants with optional filtering.
    """
    tenants = list(_tenants_db.values())
    
    # Filter by active status if specified
    if is_active is not None:
        tenants = [t for t in tenants if t["is_active"] == is_active]
    
    # Apply pagination
    tenants = tenants[skip:skip + limit]
    
    return [TenantResponse(**t) for t in tenants]


@router.put("/{tenant_id}", response_model=TenantResponse)
async def update_tenant(tenant_id: str, tenant: TenantUpdate):
    """
    Update tenant
    
    Updates a tenant's information.
    """
    if tenant_id not in _tenants_db:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant {tenant_id} not found"
        )
    
    tenant_data = _tenants_db[tenant_id]
    
    # Update fields if provided
    if tenant.name is not None:
        tenant_data["name"] = tenant.name
    if tenant.description is not None:
        tenant_data["description"] = tenant.description
    if tenant.is_active is not None:
        tenant_data["is_active"] = tenant.is_active
    
    tenant_data["updated_at"] = datetime.utcnow()
    
    return TenantResponse(**tenant_data)


@router.delete("/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tenant(tenant_id: str):
    """
    Delete tenant
    
    Deletes a tenant from the system.
    """
    if tenant_id not in _tenants_db:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant {tenant_id} not found"
        )
    
    del _tenants_db[tenant_id]
    return None
