"""
Agent Economy API Routes
Monitor credits, transactions, and resource usage
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime

from backend.middleware.auth.auth_middleware import get_current_user
from backend.economy.resource_marketplace import ResourceMarketplace
from backend.models.domain.user import User

router = APIRouter(prefix="/api/v1/economy", tags=["economy"])

marketplace = ResourceMarketplace()


class AgentBalance(BaseModel):
    """Agent credit balance"""
    agent_id: str
    agent_type: str
    balance: float
    total_earned: float
    total_spent: float
    last_updated: datetime


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
    """Tenant-wide economy statistics"""
    tenant_id: str
    total_agents: int
    total_balance: float
    total_spent_today: float
    total_earned_today: float
    average_cost_per_mission: float
    most_expensive_agent: Optional[str] = None
    most_profitable_agent: Optional[str] = None


@router.get("/balance", response_model=List[AgentBalance])
async def get_agent_balances(
    current_user: User = Depends(get_current_user)
):
    """
    Get credit balances for all agents in the tenant
    
    Shows how much each agent has earned and spent
    """
    balances = await marketplace.get_tenant_balances(current_user.tenant_id)
    
    return [
        AgentBalance(
            agent_id=agent_id,
            agent_type=data["type"],
            balance=data["balance"],
            total_earned=data["total_earned"],
            total_spent=data["total_spent"],
            last_updated=data["last_updated"]
        )
        for agent_id, data in balances.items()
    ]


@router.get("/balance/{agent_id}", response_model=AgentBalance)
async def get_agent_balance(
    agent_id: str,
    current_user: User = Depends(get_current_user)
):
    """Get credit balance for a specific agent"""
    balance = await marketplace.get_balance(current_user.tenant_id, agent_id)
    
    if balance is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    return AgentBalance(
        agent_id=agent_id,
        agent_type=balance["type"],
        balance=balance["balance"],
        total_earned=balance["total_earned"],
        total_spent=balance["total_spent"],
        last_updated=balance["last_updated"]
    )


@router.get("/transactions", response_model=List[Transaction])
async def get_transactions(
    limit: int = 100,
    offset: int = 0,
    agent_id: Optional[str] = None,
    current_user: User = Depends(get_current_user)
):
    """
    Get transaction history for the tenant
    
    Shows all charges and rewards across all agents
    """
    transactions = await marketplace.get_transactions(
        current_user.tenant_id,
        limit=limit,
        offset=offset,
        agent_id=agent_id
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


@router.get("/stats", response_model=EconomyStats)
async def get_economy_stats(
    current_user: User = Depends(get_current_user)
):
    """
    Get tenant-wide economy statistics
    
    Overview of total spending, earnings, and agent performance
    """
    stats = await marketplace.get_tenant_stats(current_user.tenant_id)
    
    return EconomyStats(
        tenant_id=current_user.tenant_id,
        total_agents=stats["total_agents"],
        total_balance=stats["total_balance"],
        total_spent_today=stats["total_spent_today"],
        total_earned_today=stats["total_earned_today"],
        average_cost_per_mission=stats["average_cost_per_mission"],
        most_expensive_agent=stats.get("most_expensive_agent"),
        most_profitable_agent=stats.get("most_profitable_agent")
    )


@router.post("/top-up")
async def top_up_credits(
    amount: float = Field(..., gt=0, description="Amount of credits to add"),
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
