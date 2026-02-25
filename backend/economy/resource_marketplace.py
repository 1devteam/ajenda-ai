"""
Resource Marketplace - Agent Economy System
Manages credits, transactions, and resource allocation for agents
"""
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from collections import defaultdict
from enum import Enum
import uuid
import asyncio
from backend.integrations.observability.prometheus_metrics import get_metrics

metrics = get_metrics()

class ResourceType(Enum):
    """Types of resources that can be charged in the economy"""
    LLM_CALL = "llm_call"
    COMPUTE = "compute"
    STORAGE = "storage"
    MEMORY = "memory"
    NETWORK = "network"
    TOOL_USE = "tool_use"

class ResourceMarketplace:
    """
    Manages the agent economy system
    
    Tracks:
    - Agent credit balances
    - Resource consumption (LLM calls, compute, storage)
    - Transactions (charges and rewards)
    - Tenant-wide economics
    """
    
    def __init__(self):
        """Initialize the marketplace with in-memory storage"""
        # In production, this would use Redis or PostgreSQL
        self._balances: Dict[str, Dict[str, Dict]] = defaultdict(dict)  # tenant_id -> agent_id -> balance_data
        self._transactions: Dict[str, List[Dict]] = defaultdict(list)  # tenant_id -> transactions
        self._lock = asyncio.Lock()
    
    async def get_balance(self, tenant_id: str, agent_id: str) -> Optional[Dict]:
        """
        Get credit balance for a specific agent
        
        Returns:
            {
                "type": "commander",
                "balance": 1000.0,
                "total_earned": 5000.0,
                "total_spent": 4000.0,
                "last_updated": datetime
            }
        """
        async with self._lock:
            if agent_id not in self._balances[tenant_id]:
                # Initialize new agent with starting balance
                self._balances[tenant_id][agent_id] = {
                    "type": "unknown",
                    "balance": 1000.0,  # Starting credits
                    "total_earned": 1000.0,
                    "total_spent": 0.0,
                    "last_updated": datetime.utcnow()
                }
            
            # Return a copy to prevent external mutation of internal state
            return dict(self._balances[tenant_id][agent_id])
    
    async def get_tenant_balances(self, tenant_id: str) -> Dict[str, Dict]:
        """
        Get all agent balances for a tenant
        
        Returns:
            {
                "agent_123": {
                    "type": "commander",
                    "balance": 1000.0,
                    ...
                },
                ...
            }
        """
        async with self._lock:
            return dict(self._balances[tenant_id])
    
    async def charge(
        self,
        tenant_id: str,
        agent_id: str,
        amount: float,
        resource_type: str,
        mission_id: Optional[str] = None,
        agent_type: str = "unknown"
    ) -> Dict:
        """
        Charge an agent for resource usage
        
        Args:
            tenant_id: Tenant identifier
            agent_id: Agent identifier
            amount: Amount to charge (positive number)
            resource_type: Type of resource (e.g., "llm_call", "compute", "storage")
            mission_id: Optional mission identifier
            agent_type: Type of agent (e.g., "commander", "guardian")
        
        Returns:
            Transaction record
        """
        async with self._lock:
            # Get or create agent balance
            if agent_id not in self._balances[tenant_id]:
                self._balances[tenant_id][agent_id] = {
                    "type": agent_type,
                    "balance": 1000.0,
                    "total_earned": 1000.0,
                    "total_spent": 0.0,
                    "last_updated": datetime.utcnow()
                }
            
            # Deduct from balance
            balance_data = self._balances[tenant_id][agent_id]
            balance_data["balance"] -= amount
            balance_data["total_spent"] += amount
            balance_data["last_updated"] = datetime.utcnow()

            # Record metrics
            metrics.record_credits_spent(agent_id, resource_type, amount)
            metrics.update_agent_balance(agent_id, balance_data["balance"])
            
            # Record transaction
            transaction = {
                "id": str(uuid.uuid4()),
                "agent_id": agent_id,
                "type": "charge",
                "amount": amount,
                "resource_type": resource_type,
                "mission_id": mission_id,
                "timestamp": datetime.utcnow()
            }
            
            self._transactions[tenant_id].append(transaction)
            
            return transaction
    
    async def reward(
        self,
        tenant_id: str,
        agent_id: str,
        amount: float,
        resource_type: str,
        mission_id: Optional[str] = None,
        agent_type: str = "unknown"
    ) -> Dict:
        """
        Reward an agent with credits
        
        Args:
            tenant_id: Tenant identifier
            agent_id: Agent identifier
            amount: Amount to reward (positive number)
            resource_type: Type of resource (e.g., "mission_success", "quality_bonus")
            mission_id: Optional mission identifier
            agent_type: Type of agent
        
        Returns:
            Transaction record
        """
        async with self._lock:
            # Get or create agent balance
            if agent_id not in self._balances[tenant_id]:
                self._balances[tenant_id][agent_id] = {
                    "type": agent_type,
                    "balance": 1000.0,
                    "total_earned": 1000.0,
                    "total_spent": 0.0,
                    "last_updated": datetime.utcnow()
                }
            
            # Add to balance
            balance_data = self._balances[tenant_id][agent_id]
            balance_data["balance"] += amount
            balance_data["total_earned"] += amount
            balance_data["last_updated"] = datetime.utcnow()

            # Record metrics
            metrics.record_credits_earned(agent_id, resource_type, amount)
            metrics.update_agent_balance(agent_id, balance_data["balance"])
            
            # Record transaction
            transaction = {
                "id": str(uuid.uuid4()),
                "agent_id": agent_id,
                "type": "reward",
                "amount": amount,
                "resource_type": resource_type,
                "mission_id": mission_id,
                "timestamp": datetime.utcnow()
            }
            
            self._transactions[tenant_id].append(transaction)
            
            return transaction
    
    async def get_transactions(
        self,
        tenant_id: str,
        limit: int = 100,
        offset: int = 0,
        agent_id: Optional[str] = None
    ) -> List[Dict]:
        """
        Get transaction history
        
        Args:
            tenant_id: Tenant identifier
            limit: Maximum number of transactions to return
            offset: Number of transactions to skip
            agent_id: Optional filter by agent
        
        Returns:
            List of transaction records
        """
        async with self._lock:
            transactions = self._transactions[tenant_id]
            
            # Filter by agent if specified
            if agent_id:
                transactions = [tx for tx in transactions if tx["agent_id"] == agent_id]
            
            # Sort by timestamp (newest first)
            transactions = sorted(transactions, key=lambda x: x["timestamp"], reverse=True)
            
            # Apply pagination
            return transactions[offset:offset + limit]
    
    async def get_tenant_stats(self, tenant_id: str) -> Dict:
        """
        Get tenant-wide economy statistics
        
        Returns:
            {
                "total_agents": 5,
                "total_balance": 10000.0,
                "total_spent_today": 500.0,
                "total_earned_today": 600.0,
                "average_cost_per_mission": 50.0,
                "most_expensive_agent": "agent_123",
                "most_profitable_agent": "agent_456"
            }
        """
        async with self._lock:
            balances = self._balances[tenant_id]
            transactions = self._transactions[tenant_id]
            
            # Calculate totals
            total_agents = len(balances)
            total_balance = sum(data["balance"] for data in balances.values())
            
            # Calculate today's activity
            today = datetime.utcnow().date()
            today_transactions = [
                tx for tx in transactions
                if tx["timestamp"].date() == today
            ]
            
            total_spent_today = sum(
                tx["amount"] for tx in today_transactions
                if tx["type"] == "charge"
            )
            
            total_earned_today = sum(
                tx["amount"] for tx in today_transactions
                if tx["type"] == "reward"
            )
            
            # Calculate average cost per mission
            mission_transactions = [tx for tx in transactions if tx.get("mission_id")]
            missions = set(tx["mission_id"] for tx in mission_transactions)
            average_cost_per_mission = (
                sum(tx["amount"] for tx in mission_transactions if tx["type"] == "charge") / len(missions)
                if missions else 0.0
            )
            
            # Find most expensive and profitable agents
            most_expensive_agent = max(
                balances.items(),
                key=lambda x: x[1]["total_spent"],
                default=(None, {"total_spent": 0})
            )[0]
            
            most_profitable_agent = max(
                balances.items(),
                key=lambda x: x[1]["total_earned"],
                default=(None, {"total_earned": 0})
            )[0]
            
            # Calculate additional stats
            total_transactions = len(transactions)
            avg_balance_per_agent = total_balance / total_agents if total_agents > 0 else 0.0
            
            return {
                "total_agents": total_agents,
                "total_balance": total_balance,
                "total_transactions": total_transactions,
                "avg_balance_per_agent": avg_balance_per_agent,
                "total_spent_today": total_spent_today,
                "total_earned_today": total_earned_today,
                "average_cost_per_mission": average_cost_per_mission,
                "most_expensive_agent": most_expensive_agent,
                "most_profitable_agent": most_profitable_agent
            }
    
    async def add_tenant_credits(self, tenant_id: str, amount: float):
        """
        Add credits to the tenant's economy
        
        In production, this would integrate with a payment processor
        """
        async with self._lock:
            # Distribute credits evenly across all agents
            balances = self._balances[tenant_id]
            
            if not balances:
                return
            
            per_agent = amount / len(balances)
            
            for agent_id, balance_data in balances.items():
                balance_data["balance"] += per_agent
                balance_data["total_earned"] += per_agent
                balance_data["last_updated"] = datetime.utcnow()
    
    async def get_tenant_total_balance(self, tenant_id: str) -> float:
        """Get total balance across all agents in the tenant"""
        async with self._lock:
            return sum(
                data["balance"]
                for data in self._balances[tenant_id].values()
            )
