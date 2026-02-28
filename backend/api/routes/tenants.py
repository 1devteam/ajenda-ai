"""
Tenants API Routes
Handles tenant/organization management with SQLAlchemy persistence

Built with Pride for Obex Blackvault
"""

from fastapi import APIRouter, HTTPException, status, Depends, Query
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
import uuid

from sqlalchemy.orm import Session
from backend.database import get_db
from backend.database.models import Tenant

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
    slug: str
    description: Optional[str] = None
    is_active: bool = True
    created_at: datetime
    agent_count: int = 0
    mission_count: int = 0


# ============================================================================
# Helper Functions
# ============================================================================


def _generate_slug(name: str) -> str:
    """Generate a URL-friendly slug from tenant name"""
    import re

    slug = name.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[-\s]+", "-", slug)
    return slug[:100]


# ============================================================================
# API Endpoints
# ============================================================================


@router.post("", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
async def create_tenant(tenant: TenantCreate, db: Session = Depends(get_db)):
    """
    Create a new tenant

    Creates a new tenant/organization in the system with database persistence.
    """
    tenant_id = f"tenant_{uuid.uuid4().hex[:12]}"
    slug = _generate_slug(tenant.name)

    # Check if slug already exists
    existing = db.query(Tenant).filter(Tenant.slug == slug).first()
    if existing:
        # Append random suffix to make it unique
        slug = f"{slug}-{uuid.uuid4().hex[:6]}"

    tenant_data = Tenant(
        id=tenant_id,
        name=tenant.name,
        slug=slug,
        settings={"description": tenant.description} if tenant.description else {},
        is_active=True,
        created_at=datetime.utcnow(),
    )

    db.add(tenant_data)
    db.commit()
    db.refresh(tenant_data)

    # Count related entities
    agent_count = len(tenant_data.agents) if tenant_data.agents else 0
    mission_count = len(tenant_data.missions) if tenant_data.missions else 0

    return TenantResponse(
        id=tenant_data.id,
        name=tenant_data.name,
        slug=tenant_data.slug,
        description=tenant_data.settings.get("description"),
        is_active=tenant_data.is_active,
        created_at=tenant_data.created_at,
        agent_count=agent_count,
        mission_count=mission_count,
    )


@router.get("/{tenant_id}", response_model=TenantResponse)
async def get_tenant(tenant_id: str, db: Session = Depends(get_db)):
    """
    Get tenant by ID

    Retrieves a specific tenant's information from the database.
    """
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()

    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant {tenant_id} not found",
        )

    # Count related entities
    agent_count = len(tenant.agents) if tenant.agents else 0
    mission_count = len(tenant.missions) if tenant.missions else 0

    return TenantResponse(
        id=tenant.id,
        name=tenant.name,
        slug=tenant.slug,
        description=tenant.settings.get("description"),
        is_active=tenant.is_active,
        created_at=tenant.created_at,
        agent_count=agent_count,
        mission_count=mission_count,
    )


@router.get("", response_model=List[TenantResponse])
async def list_tenants(
    db: Session = Depends(get_db),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(100, ge=1, le=1000, description="Max number of records to return"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
):
    """
    List all tenants

    Returns a list of tenants from the database with optional filtering.
    """
    query = db.query(Tenant)

    # Filter by active status if specified
    if is_active is not None:
        query = query.filter(Tenant.is_active == is_active)

    # Apply pagination
    tenants = query.offset(skip).limit(limit).all()

    return [
        TenantResponse(
            id=t.id,
            name=t.name,
            slug=t.slug,
            description=t.settings.get("description"),
            is_active=t.is_active,
            created_at=t.created_at,
            agent_count=len(t.agents) if t.agents else 0,
            mission_count=len(t.missions) if t.missions else 0,
        )
        for t in tenants
    ]


@router.put("/{tenant_id}", response_model=TenantResponse)
async def update_tenant(tenant_id: str, tenant: TenantUpdate, db: Session = Depends(get_db)):
    """
    Update tenant

    Updates a tenant's information in the database.
    """
    tenant_data = db.query(Tenant).filter(Tenant.id == tenant_id).first()

    if not tenant_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant {tenant_id} not found",
        )

    # Update fields if provided
    if tenant.name is not None:
        tenant_data.name = tenant.name
        tenant_data.slug = _generate_slug(tenant.name)
    if tenant.description is not None:
        settings = tenant_data.settings or {}
        settings["description"] = tenant.description
        tenant_data.settings = settings
    if tenant.is_active is not None:
        tenant_data.is_active = tenant.is_active

    db.commit()
    db.refresh(tenant_data)

    return TenantResponse(
        id=tenant_data.id,
        name=tenant_data.name,
        slug=tenant_data.slug,
        description=tenant_data.settings.get("description"),
        is_active=tenant_data.is_active,
        created_at=tenant_data.created_at,
        agent_count=len(tenant_data.agents) if tenant_data.agents else 0,
        mission_count=len(tenant_data.missions) if tenant_data.missions else 0,
    )


@router.delete("/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tenant(tenant_id: str, db: Session = Depends(get_db)):
    """
    Delete tenant

    Deletes a tenant from the database.
    Note: This will cascade delete all related users, agents, and missions.
    """
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()

    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant {tenant_id} not found",
        )

    db.delete(tenant)
    db.commit()
    return None
