"""
Resource Marketplace - Agent Economy System
Manages credits, transactions, and resource allocation for agents

Persistence: Redis-backed with in-memory fallback.
- Balances are stored in Redis hashes: economy:{tenant_id}:balance:{agent_id}
- Transactions are stored in Redis lists: economy:{tenant_id}:txns
- If Redis is unavailable, falls back to in-memory storage transparently.

Built with Pride for Obex Blackvault
"""

import asyncio
import json
import logging
import uuid
from collections import defaultdict
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

from backend.integrations.observability.prometheus_metrics import get_metrics

try:
    import redis.asyncio as aioredis

    _REDIS_AVAILABLE = True
except ImportError:
    _REDIS_AVAILABLE = False

logger = logging.getLogger(__name__)
metrics = get_metrics()

# Starting credit balance for every new agent
_STARTING_BALANCE = 1000.0


class ResourceType(Enum):
    """Types of resources that can be charged in the economy"""

    LLM_CALL = "llm_call"
    COMPUTE = "compute"
    STORAGE = "storage"
    MEMORY = "memory"
    NETWORK = "network"
    TOOL_USE = "tool_use"


def _now_iso() -> str:
    return datetime.utcnow().isoformat()


def _today_str() -> str:
    return datetime.utcnow().date().isoformat()


class ResourceMarketplace:
    """
    Manages the agent economy system.

    Persistence strategy:
    - Primary: Redis (async, atomic HINCRBYFLOAT for balance mutations)
    - Fallback: In-memory defaultdict (used when Redis is unavailable)

    All public methods maintain the same interface regardless of backend.
    """

    def __init__(self, redis_url: Optional[str] = None):
        """
        Initialise the marketplace.

        Args:
            redis_url: Redis connection URL. If None, reads from settings or
                       falls back to in-memory storage.
        """
        self._redis_url = redis_url
        self._redis: Optional[object] = None  # aioredis.Redis instance
        self._redis_ready = False

        # In-memory fallback structures (used when Redis is unavailable)
        self._balances: Dict[str, Dict[str, Dict]] = defaultdict(dict)
        self._transactions: Dict[str, List[Dict]] = defaultdict(list)
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """
        Attempt to connect to Redis. Non-fatal — falls back to in-memory
        if connection fails.
        """
        if not _REDIS_AVAILABLE:
            logger.info("Economy: Redis package not installed — using in-memory storage")
            return

        url = self._redis_url
        if not url:
            try:
                from backend.core.config import get_settings

                url = get_settings().redis_url
            except Exception:
                url = "redis://localhost:6379/0"

        try:
            self._redis = aioredis.from_url(
                url,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=3,
                socket_timeout=3,
            )
            await self._redis.ping()
            self._redis_ready = True
            logger.info(f"Economy: Redis connected at {url}")
        except Exception as exc:
            logger.warning(f"Economy: Redis unavailable ({exc}) — using in-memory fallback")
            self._redis = None
            self._redis_ready = False

    async def close(self) -> None:
        """Close the Redis connection gracefully."""
        if self._redis and self._redis_ready:
            try:
                await self._redis.aclose()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Internal Redis helpers
    # ------------------------------------------------------------------

    def _balance_key(self, tenant_id: str, agent_id: str) -> str:
        return f"economy:{tenant_id}:balance:{agent_id}"

    def _txn_key(self, tenant_id: str) -> str:
        return f"economy:{tenant_id}:txns"

    async def _redis_get_balance(self, tenant_id: str, agent_id: str) -> Dict:
        """Read balance from Redis, initialising if absent."""
        key = self._balance_key(tenant_id, agent_id)
        raw = await self._redis.hgetall(key)
        if not raw:
            # Initialise new agent balance
            init = {
                "type": "unknown",
                "balance": str(_STARTING_BALANCE),
                "total_earned": str(_STARTING_BALANCE),
                "total_spent": "0.0",
                "last_updated": _now_iso(),
            }
            await self._redis.hset(key, mapping=init)
            return {
                "type": "unknown",
                "balance": _STARTING_BALANCE,
                "total_earned": _STARTING_BALANCE,
                "total_spent": 0.0,
                "last_updated": datetime.utcnow(),
            }
        return {
            "type": raw.get("type", "unknown"),
            "balance": float(raw.get("balance", _STARTING_BALANCE)),
            "total_earned": float(raw.get("total_earned", _STARTING_BALANCE)),
            "total_spent": float(raw.get("total_spent", 0.0)),
            "last_updated": raw.get("last_updated", _now_iso()),
        }

    async def _redis_mutate_balance(
        self,
        tenant_id: str,
        agent_id: str,
        delta: float,
        agent_type: str = "unknown",
    ) -> float:
        """
        Atomically adjust balance by delta (positive = credit, negative = debit).
        Returns the new balance.
        """
        key = self._balance_key(tenant_id, agent_id)
        # Ensure the key exists before incrementing
        exists = await self._redis.exists(key)
        if not exists:
            init = {
                "type": agent_type,
                "balance": str(_STARTING_BALANCE),
                "total_earned": str(_STARTING_BALANCE),
                "total_spent": "0.0",
                "last_updated": _now_iso(),
            }
            await self._redis.hset(key, mapping=init)

        new_balance = await self._redis.hincrbyfloat(key, "balance", delta)
        if delta > 0:
            await self._redis.hincrbyfloat(key, "total_earned", delta)
        else:
            await self._redis.hincrbyfloat(key, "total_spent", abs(delta))
        await self._redis.hset(key, "last_updated", _now_iso())
        await self._redis.hset(key, "type", agent_type)
        return float(new_balance)

    async def _redis_append_txn(self, tenant_id: str, transaction: Dict) -> None:
        """Append a transaction record to the Redis list (newest first via LPUSH)."""
        key = self._txn_key(tenant_id)
        # Serialise datetime objects
        record = {
            k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in transaction.items()
        }
        await self._redis.lpush(key, json.dumps(record))
        # Cap the list at 10,000 transactions per tenant to prevent unbounded growth
        await self._redis.ltrim(key, 0, 9999)

    async def _redis_get_txns(
        self,
        tenant_id: str,
        limit: int,
        offset: int,
        agent_id: Optional[str] = None,
    ) -> List[Dict]:
        """Read transactions from Redis list with optional agent filter."""
        key = self._txn_key(tenant_id)
        if agent_id:
            # Must scan the full list to filter — cap at 10k
            raw_all = await self._redis.lrange(key, 0, 9999)
            records = [json.loads(r) for r in raw_all]
            records = [r for r in records if r.get("agent_id") == agent_id]
            return records[offset : offset + limit]
        else:
            raw = await self._redis.lrange(key, offset, offset + limit - 1)
            return [json.loads(r) for r in raw]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_balance(self, tenant_id: str, agent_id: str) -> Optional[Dict]:
        """
        Get credit balance for a specific agent.

        Returns:
            {
                "type": "commander",
                "balance": 1000.0,
                "total_earned": 5000.0,
                "total_spent": 4000.0,
                "last_updated": datetime | str
            }
        """
        if self._redis_ready:
            try:
                return await self._redis_get_balance(tenant_id, agent_id)
            except Exception as exc:
                logger.warning(f"Economy Redis read error: {exc} — falling back to memory")

        # In-memory fallback
        async with self._lock:
            if agent_id not in self._balances[tenant_id]:
                self._balances[tenant_id][agent_id] = {
                    "type": "unknown",
                    "balance": _STARTING_BALANCE,
                    "total_earned": _STARTING_BALANCE,
                    "total_spent": 0.0,
                    "last_updated": datetime.utcnow(),
                }
            return dict(self._balances[tenant_id][agent_id])

    async def get_tenant_balances(self, tenant_id: str) -> Dict[str, Dict]:
        """Get all agent balances for a tenant."""
        if self._redis_ready:
            try:
                pattern = f"economy:{tenant_id}:balance:*"
                keys = await self._redis.keys(pattern)
                result = {}
                for key in keys:
                    agent_id = key.split(":")[-1]
                    result[agent_id] = await self._redis_get_balance(tenant_id, agent_id)
                return result
            except Exception as exc:
                logger.warning(f"Economy Redis scan error: {exc} — falling back to memory")

        async with self._lock:
            return dict(self._balances[tenant_id])

    async def charge(
        self,
        tenant_id: str,
        agent_id: str,
        amount: float,
        resource_type: str,
        mission_id: Optional[str] = None,
        agent_type: str = "unknown",
    ) -> Dict:
        """
        Charge an agent for resource usage.

        Args:
            tenant_id: Tenant identifier
            agent_id: Agent identifier
            amount: Amount to charge (positive number)
            resource_type: Type of resource consumed
            mission_id: Optional mission identifier
            agent_type: Type of agent

        Returns:
            Transaction record
        """
        transaction = {
            "id": str(uuid.uuid4()),
            "agent_id": agent_id,
            "type": "charge",
            "amount": amount,
            "resource_type": resource_type,
            "mission_id": mission_id,
            "timestamp": datetime.utcnow(),
        }

        if self._redis_ready:
            try:
                new_balance = await self._redis_mutate_balance(
                    tenant_id, agent_id, -amount, agent_type
                )
                await self._redis_append_txn(tenant_id, transaction)
                metrics.record_credits_spent(agent_id, resource_type, amount)
                metrics.update_agent_balance(agent_id, new_balance)
                return transaction
            except Exception as exc:
                logger.warning(f"Economy Redis charge error: {exc} — falling back to memory")

        # In-memory fallback
        async with self._lock:
            if agent_id not in self._balances[tenant_id]:
                self._balances[tenant_id][agent_id] = {
                    "type": agent_type,
                    "balance": _STARTING_BALANCE,
                    "total_earned": _STARTING_BALANCE,
                    "total_spent": 0.0,
                    "last_updated": datetime.utcnow(),
                }
            balance_data = self._balances[tenant_id][agent_id]
            balance_data["balance"] -= amount
            balance_data["total_spent"] += amount
            balance_data["last_updated"] = datetime.utcnow()
            self._transactions[tenant_id].append(transaction)
            metrics.record_credits_spent(agent_id, resource_type, amount)
            metrics.update_agent_balance(agent_id, balance_data["balance"])
            return transaction

    async def reward(
        self,
        tenant_id: str,
        agent_id: str,
        amount: float,
        resource_type: str,
        mission_id: Optional[str] = None,
        agent_type: str = "unknown",
    ) -> Dict:
        """
        Reward an agent with credits.

        Args:
            tenant_id: Tenant identifier
            agent_id: Agent identifier
            amount: Amount to reward (positive number)
            resource_type: Reward category
            mission_id: Optional mission identifier
            agent_type: Type of agent

        Returns:
            Transaction record
        """
        transaction = {
            "id": str(uuid.uuid4()),
            "agent_id": agent_id,
            "type": "reward",
            "amount": amount,
            "resource_type": resource_type,
            "mission_id": mission_id,
            "timestamp": datetime.utcnow(),
        }

        if self._redis_ready:
            try:
                new_balance = await self._redis_mutate_balance(
                    tenant_id, agent_id, amount, agent_type
                )
                await self._redis_append_txn(tenant_id, transaction)
                metrics.record_credits_earned(agent_id, resource_type, amount)
                metrics.update_agent_balance(agent_id, new_balance)
                return transaction
            except Exception as exc:
                logger.warning(f"Economy Redis reward error: {exc} — falling back to memory")

        # In-memory fallback
        async with self._lock:
            if agent_id not in self._balances[tenant_id]:
                self._balances[tenant_id][agent_id] = {
                    "type": agent_type,
                    "balance": _STARTING_BALANCE,
                    "total_earned": _STARTING_BALANCE,
                    "total_spent": 0.0,
                    "last_updated": datetime.utcnow(),
                }
            balance_data = self._balances[tenant_id][agent_id]
            balance_data["balance"] += amount
            balance_data["total_earned"] += amount
            balance_data["last_updated"] = datetime.utcnow()
            self._transactions[tenant_id].append(transaction)
            metrics.record_credits_earned(agent_id, resource_type, amount)
            metrics.update_agent_balance(agent_id, balance_data["balance"])
            return transaction

    async def get_transactions(
        self,
        tenant_id: str,
        limit: int = 100,
        offset: int = 0,
        agent_id: Optional[str] = None,
    ) -> List[Dict]:
        """
        Get transaction history for a tenant.

        Args:
            tenant_id: Tenant identifier
            limit: Maximum number of transactions to return
            offset: Number of transactions to skip
            agent_id: Optional filter by agent

        Returns:
            List of transaction records (newest first)
        """
        if self._redis_ready:
            try:
                return await self._redis_get_txns(tenant_id, limit, offset, agent_id)
            except Exception as exc:
                logger.warning(f"Economy Redis txn read error: {exc} — falling back to memory")

        async with self._lock:
            transactions = list(self._transactions[tenant_id])
            if agent_id:
                transactions = [tx for tx in transactions if tx["agent_id"] == agent_id]
            transactions.sort(
                key=lambda x: (
                    x["timestamp"]
                    if isinstance(x["timestamp"], datetime)
                    else datetime.fromisoformat(x["timestamp"])
                ),
                reverse=True,
            )
            return transactions[offset : offset + limit]

    async def get_tenant_stats(self, tenant_id: str) -> Dict:
        """
        Get tenant-wide economy statistics.

        Returns aggregate metrics including total balance, daily spend/earn,
        average mission cost, and top agents by spend and earnings.
        """
        balances = await self.get_tenant_balances(tenant_id)
        transactions = await self.get_transactions(tenant_id, limit=10000)

        total_agents = len(balances)
        total_balance = sum(float(data["balance"]) for data in balances.values())

        today = _today_str()
        today_transactions = [
            tx
            for tx in transactions
            if (
                tx["timestamp"][:10]
                if isinstance(tx["timestamp"], str)
                else tx["timestamp"].date().isoformat()
            )
            == today
        ]

        total_spent_today = sum(
            float(tx["amount"]) for tx in today_transactions if tx["type"] == "charge"
        )
        total_earned_today = sum(
            float(tx["amount"]) for tx in today_transactions if tx["type"] == "reward"
        )

        mission_transactions = [tx for tx in transactions if tx.get("mission_id")]
        missions = set(tx["mission_id"] for tx in mission_transactions)
        average_cost_per_mission = (
            sum(float(tx["amount"]) for tx in mission_transactions if tx["type"] == "charge")
            / len(missions)
            if missions
            else 0.0
        )

        most_expensive_agent = max(
            balances.items(),
            key=lambda x: float(x[1].get("total_spent", 0)),
            default=(None, {"total_spent": 0}),
        )[0]

        most_profitable_agent = max(
            balances.items(),
            key=lambda x: float(x[1].get("total_earned", 0)),
            default=(None, {"total_earned": 0}),
        )[0]

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
            "most_profitable_agent": most_profitable_agent,
        }

    async def add_tenant_credits(self, tenant_id: str, amount: float) -> None:
        """
        Add credits to the tenant's economy, distributed evenly across all agents.

        In production this would integrate with a payment processor.
        """
        balances = await self.get_tenant_balances(tenant_id)

        if not balances:
            default_agent_id = f"{tenant_id}_default"
            await self.reward(
                tenant_id=tenant_id,
                agent_id=default_agent_id,
                amount=amount,
                resource_type="tenant_top_up",
            )
            return

        per_agent = amount / len(balances)
        for agent_id in balances:
            await self.reward(
                tenant_id=tenant_id,
                agent_id=agent_id,
                amount=per_agent,
                resource_type="tenant_top_up",
            )

    async def get_tenant_total_balance(self, tenant_id: str) -> float:
        """Get total balance across all agents in the tenant."""
        balances = await self.get_tenant_balances(tenant_id)
        return sum(float(data["balance"]) for data in balances.values())
