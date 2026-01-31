"""
Economy API Routes
Handles agent credit management, transactions, and marketplace operations
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

from backend.economy.resource_marketplace import ResourceMarketplace
from backend.models.domain.user import User
from backend.middleware.auth.auth_middleware import get_current_user

router = APIRouter(prefix="/api/v1/economy", tags=["economy"])
marketplace = ResourceMarketplace()


class AgentBalance(BaseModel):
    """Agent balance information"""
    agent_id: str
    balance: float
    tenant_id: str


class Transaction(BaseModel):
    """Economy transaction record"""
    transaction_id: str
    agent_id: str
    type: str  # "charge" or "reward"
    amount: float
    resource_type: str
    mission_id: Optional[str] = None
    timestamp: datetime


class EconomyStats(BaseModel):
    """Tenant economy statistics"""
    total_balance: float
    total_transactions: int
    total_agents: int
    avg_balance_per_agent: float


@router.get("/balance", response_model=List[AgentBalance])
async def get_agent_balances(
    current_user: User = Depends(get_current_user)
):
    """Get all agent balances for the current tenant"""
    balances = await marketplace.get_all_balances(current_user.tenant_id)
    return [
        AgentBalance(
            agent_id=agent_id,
            balance=balance["balance"],
            tenant_id=current_user.tenant_id
        )
        for agent_id, balance in balances.items()
    ]


@router.get("/transactions", response_model=List[Transaction])
async def get_transactions(
    agent_id: Optional[str] = None,
    limit: int = 100,
    current_user: User = Depends(get_current_user)
):
    """Get transaction history for the tenant or specific agent"""
    transactions = await marketplace.get_transactions(
        current_user.tenant_id,
        agent_id=agent_id,
        limit=limit
    )
    return [
        Transaction(
            transaction_id=tx["id"],
            agent_id=tx["agent_id"],
            type=tx["type"],
            amount=tx["amount"],
            resource_type=tx["resource_type"],
            mission_id=tx.get("mission_id"),
            timestamp=tx["timestamp"]
        )
        for tx in transactions
    ]


@router.post("/top-up")
async def top_up_credits(
    amount: float = Query(..., gt=0, description="Amount of credits to add"),
    current_user: User = Depends(get_current_user)
):
    """
    Add credits to the tenant's economy
    In production, this would integrate with a payment processor
    """
    await marketplace.add_tenant_credits(current_user.tenant_id, amount)
    return {
        "message": f"Added {amount} credits to tenant {current_user.tenant_id}",
        "new_balance": await marketplace.get_tenant_total_balance(current_user.tenant_id)
    }


@router.get("/stats", response_model=EconomyStats)
async def get_economy_stats(
    current_user: User = Depends(get_current_user)
):
    """Get economy statistics for the tenant"""
    stats = await marketplace.get_tenant_stats(current_user.tenant_id)
    return EconomyStats(**stats)
