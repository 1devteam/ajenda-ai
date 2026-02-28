"""
Unit Tests for Agent Economy System
Tests the ResourceMarketplace and credit management
"""

import pytest
from datetime import datetime

from backend.economy.resource_marketplace import ResourceMarketplace
from backend.models.domain.user import User


@pytest.mark.unit
@pytest.mark.economy
class TestResourceMarketplace:
    """Test suite for ResourceMarketplace"""

    @pytest.mark.asyncio
    async def test_new_agent_gets_starting_balance(
        self, marketplace: ResourceMarketplace, mock_user: User
    ):
        """Test that new agents receive a starting balance"""
        tenant_id = mock_user.tenant_id
        agent_id = "new_agent_001"

        balance = await marketplace.get_balance(tenant_id, agent_id)

        assert balance is not None
        assert balance["balance"] == 1000.0  # Starting balance
        assert balance["total_earned"] == 1000.0
        assert balance["total_spent"] == 0.0

    @pytest.mark.asyncio
    async def test_charge_reduces_balance(self, marketplace: ResourceMarketplace, mock_user: User):
        """Test that charging an agent reduces their balance"""
        tenant_id = mock_user.tenant_id
        agent_id = "test_agent"

        # Get initial balance
        initial_balance = await marketplace.get_balance(tenant_id, agent_id)
        initial_amount = initial_balance["balance"]

        # Charge the agent
        charge_amount = 50.0
        transaction = await marketplace.charge(
            tenant_id, agent_id, charge_amount, "llm_call", agent_type="commander"
        )

        # Verify balance decreased
        new_balance = await marketplace.get_balance(tenant_id, agent_id)
        assert new_balance["balance"] == initial_amount - charge_amount
        assert new_balance["total_spent"] == charge_amount

        # Verify transaction was recorded
        assert transaction["type"] == "charge"
        assert transaction["amount"] == charge_amount
        assert transaction["agent_id"] == agent_id

    @pytest.mark.asyncio
    async def test_reward_increases_balance(
        self, marketplace: ResourceMarketplace, mock_user: User
    ):
        """Test that rewarding an agent increases their balance"""
        import uuid

        tenant_id = mock_user.tenant_id
        agent_id = (
            f"reward_test_agent_{uuid.uuid4().hex[:8]}"  # Unique agent ID to avoid state pollution
        )

        # Get initial balance
        initial_balance = await marketplace.get_balance(tenant_id, agent_id)
        initial_amount = initial_balance["balance"]

        # Reward the agent
        reward_amount = 100.0
        transaction = await marketplace.reward(
            tenant_id,
            agent_id,
            reward_amount,
            "mission_success",
            agent_type="commander",
        )

        # Verify balance increased
        new_balance = await marketplace.get_balance(tenant_id, agent_id)
        assert new_balance["balance"] == initial_amount + reward_amount
        assert new_balance["total_earned"] == initial_balance["total_earned"] + reward_amount

        # Verify transaction was recorded
        assert transaction["type"] == "reward"
        assert transaction["amount"] == reward_amount

    @pytest.mark.asyncio
    async def test_get_tenant_balances(
        self, marketplace_with_data: ResourceMarketplace, mock_user: User
    ):
        """Test retrieving all agent balances for a tenant"""
        tenant_id = mock_user.tenant_id

        balances = await marketplace_with_data.get_tenant_balances(tenant_id)

        assert len(balances) >= 3  # We created 3 agents in the fixture
        assert "agent_commander" in balances
        assert "agent_guardian" in balances
        assert "agent_archivist" in balances

    @pytest.mark.asyncio
    async def test_get_transactions(
        self, marketplace_with_data: ResourceMarketplace, mock_user: User
    ):
        """Test retrieving transaction history"""
        tenant_id = mock_user.tenant_id

        transactions = await marketplace_with_data.get_transactions(tenant_id, limit=100)

        assert len(transactions) > 0
        assert all("id" in tx for tx in transactions)
        assert all("agent_id" in tx for tx in transactions)
        assert all("type" in tx for tx in transactions)
        assert all("amount" in tx for tx in transactions)

    @pytest.mark.asyncio
    async def test_get_transactions_filtered_by_agent(
        self, marketplace_with_data: ResourceMarketplace, mock_user: User
    ):
        """Test filtering transactions by agent"""
        tenant_id = mock_user.tenant_id
        agent_id = "agent_commander"

        transactions = await marketplace_with_data.get_transactions(tenant_id, agent_id=agent_id)

        assert all(tx["agent_id"] == agent_id for tx in transactions)

    @pytest.mark.asyncio
    async def test_get_transactions_pagination(
        self, marketplace_with_data: ResourceMarketplace, mock_user: User
    ):
        """Test transaction pagination"""
        tenant_id = mock_user.tenant_id

        # Get first page
        page1 = await marketplace_with_data.get_transactions(tenant_id, limit=2, offset=0)

        # Get second page
        page2 = await marketplace_with_data.get_transactions(tenant_id, limit=2, offset=2)

        # Verify pages are different
        if len(page1) > 0 and len(page2) > 0:
            assert page1[0]["id"] != page2[0]["id"]

    @pytest.mark.asyncio
    async def test_get_tenant_stats(
        self, marketplace_with_data: ResourceMarketplace, mock_user: User
    ):
        """Test tenant-wide statistics"""
        tenant_id = mock_user.tenant_id

        stats = await marketplace_with_data.get_tenant_stats(tenant_id)

        assert stats["total_agents"] >= 3
        assert stats["total_balance"] > 0
        assert "total_spent_today" in stats
        assert "total_earned_today" in stats
        assert "average_cost_per_mission" in stats

    @pytest.mark.asyncio
    async def test_add_tenant_credits(
        self, marketplace_with_data: ResourceMarketplace, mock_user: User
    ):
        """Test adding credits to tenant economy"""
        tenant_id = mock_user.tenant_id

        # Get initial total balance
        initial_total = await marketplace_with_data.get_tenant_total_balance(tenant_id)

        # Add credits
        credits_to_add = 500.0
        await marketplace_with_data.add_tenant_credits(tenant_id, credits_to_add)

        # Verify total balance increased
        new_total = await marketplace_with_data.get_tenant_total_balance(tenant_id)
        assert new_total == initial_total + credits_to_add

    @pytest.mark.asyncio
    async def test_transaction_with_mission_id(
        self, marketplace: ResourceMarketplace, mock_user: User
    ):
        """Test that transactions can be linked to missions"""
        tenant_id = mock_user.tenant_id
        agent_id = "test_agent"
        mission_id = "mission_123"

        transaction = await marketplace.charge(
            tenant_id,
            agent_id,
            25.0,
            "llm_call",
            mission_id=mission_id,
            agent_type="commander",
        )

        assert transaction["mission_id"] == mission_id

    @pytest.mark.asyncio
    async def test_balance_last_updated_timestamp(
        self, marketplace: ResourceMarketplace, mock_user: User
    ):
        """Test that balance last_updated timestamp is set correctly"""
        tenant_id = mock_user.tenant_id
        agent_id = "test_agent"

        before_time = datetime.utcnow()

        await marketplace.charge(tenant_id, agent_id, 10.0, "llm_call", agent_type="commander")

        balance = await marketplace.get_balance(tenant_id, agent_id)
        after_time = datetime.utcnow()

        assert before_time <= balance["last_updated"] <= after_time

    @pytest.mark.asyncio
    async def test_multiple_resource_types(self, marketplace: ResourceMarketplace, mock_user: User):
        """Test tracking different resource types"""
        tenant_id = mock_user.tenant_id
        agent_id = "test_agent"

        # Charge for different resource types
        await marketplace.charge(tenant_id, agent_id, 10.0, "llm_call", agent_type="commander")
        await marketplace.charge(tenant_id, agent_id, 5.0, "compute", agent_type="commander")
        await marketplace.charge(tenant_id, agent_id, 2.0, "storage", agent_type="commander")

        # Get transactions
        transactions = await marketplace.get_transactions(tenant_id, agent_id=agent_id)

        resource_types = {tx["resource_type"] for tx in transactions}
        assert "llm_call" in resource_types
        assert "compute" in resource_types
        assert "storage" in resource_types

    @pytest.mark.asyncio
    async def test_concurrent_transactions(self, marketplace: ResourceMarketplace, mock_user: User):
        """Test that concurrent transactions are handled correctly"""
        import asyncio

        tenant_id = mock_user.tenant_id
        agent_id = "test_agent"

        # Get initial balance
        initial_balance = await marketplace.get_balance(tenant_id, agent_id)
        initial_amount = initial_balance["balance"]

        # Execute multiple transactions concurrently
        tasks = [
            marketplace.charge(tenant_id, agent_id, 10.0, "llm_call", agent_type="commander")
            for _ in range(5)
        ]

        await asyncio.gather(*tasks)

        # Verify all charges were applied
        final_balance = await marketplace.get_balance(tenant_id, agent_id)
        assert final_balance["balance"] == initial_amount - 50.0
        assert final_balance["total_spent"] == 50.0
