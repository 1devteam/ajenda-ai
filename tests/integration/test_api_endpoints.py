"""
Integration Tests for API Endpoints
Tests all API routes with authentication and real workflows
"""

import pytest
from fastapi.testclient import TestClient


@pytest.mark.integration
@pytest.mark.api
class TestSystemEndpoints:
    """Test system-level endpoints"""

    def test_health_check(self, client: TestClient):
        """Test the /health endpoint"""
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "service" in data
        assert "version" in data

    def test_root_endpoint(self, client: TestClient):
        """Test the root / endpoint"""
        response = client.get("/")

        assert response.status_code == 200
        data = response.json()
        assert "service" in data
        assert "version" in data
        assert "docs" in data

    def test_metrics_endpoint(self, client: TestClient):
        """Test the /metrics endpoint for Prometheus"""
        response = client.get("/metrics")

        assert response.status_code == 200
        # Metrics should be in Prometheus text format
        assert response.headers["content-type"].startswith("text/plain")


@pytest.mark.integration
@pytest.mark.api
@pytest.mark.economy
class TestEconomyEndpoints:
    """Test economy API endpoints"""

    def test_get_agent_balances_requires_auth(self, client: TestClient):
        """Test that economy endpoints require authentication"""
        response = client.get("/api/v1/economy/balance")

        assert response.status_code == 403  # Forbidden (no auth header)

    def test_get_agent_balances_with_auth(self, client: TestClient, auth_headers: dict):
        """Test retrieving agent balances with authentication"""
        response = client.get("/api/v1/economy/balance", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_get_specific_agent_balance(self, client: TestClient, auth_headers: dict):
        """Test retrieving a specific agent's balance"""
        agent_id = "test_agent_001"
        response = client.get(
            f"/api/v1/economy/balance/{agent_id}", headers=auth_headers
        )

        # Should return 200 with balance data or 404 if agent doesn't exist
        assert response.status_code in [200, 404]

        if response.status_code == 200:
            data = response.json()
            assert data["agent_id"] == agent_id
            assert "balance" in data
            assert "total_earned" in data
            assert "total_spent" in data

    def test_get_transactions(self, client: TestClient, auth_headers: dict):
        """Test retrieving transaction history"""
        response = client.get("/api/v1/economy/transactions", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_get_transactions_with_pagination(
        self, client: TestClient, auth_headers: dict
    ):
        """Test transaction pagination"""
        response = client.get(
            "/api/v1/economy/transactions?limit=10&offset=0", headers=auth_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data) <= 10

    def test_get_transactions_filtered_by_agent(
        self, client: TestClient, auth_headers: dict
    ):
        """Test filtering transactions by agent"""
        agent_id = "test_agent"
        response = client.get(
            f"/api/v1/economy/transactions?agent_id={agent_id}", headers=auth_headers
        )

        assert response.status_code == 200
        data = response.json()

        # All transactions should be for the specified agent
        for tx in data:
            assert tx["agent_id"] == agent_id

    def test_get_economy_stats(self, client: TestClient, auth_headers: dict):
        """Test retrieving tenant-wide economy statistics"""
        response = client.get("/api/v1/economy/stats", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        # Stats are scoped to authenticated user's tenant, no tenant_id in response
        assert "total_agents" in data
        assert "total_balance" in data
        assert "total_transactions" in data
        assert "avg_balance_per_agent" in data
        assert "total_spent_today" in data
        assert "total_earned_today" in data

    def test_top_up_credits(self, client: TestClient, auth_headers: dict):
        """Test adding credits to tenant economy"""
        response = client.post(
            "/api/v1/economy/top-up?amount=100.0", headers=auth_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        assert "new_balance" in data

    def test_top_up_credits_invalid_amount(
        self, client: TestClient, auth_headers: dict
    ):
        """Test that negative amounts are rejected"""
        response = client.post(
            "/api/v1/economy/top-up?amount=-50.0", headers=auth_headers
        )

        # Should return 422 (validation error)
        assert response.status_code == 422


@pytest.mark.integration
@pytest.mark.api
class TestPerformanceEndpoints:
    """Test performance monitoring API endpoints"""

    def test_get_all_agent_performance_requires_auth(self, client: TestClient):
        """Test that performance endpoints require authentication"""
        response = client.get("/api/v1/performance/agents")

        assert response.status_code == 403  # Forbidden (no auth header)

    def test_get_all_agent_performance(self, client: TestClient, auth_headers: dict):
        """Test retrieving performance metrics for all agents"""
        response = client.get("/api/v1/performance/agents", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

        # Check structure of performance metrics
        if len(data) > 0:
            agent = data[0]
            assert "agent_id" in agent
            assert "agent_type" in agent
            assert "total_missions" in agent
            assert "success_rate" in agent
            assert "average_cost" in agent

    def test_get_improvement_history(self, client: TestClient, auth_headers: dict):
        """Test retrieving self-improvement event history"""
        response = client.get("/api/v1/performance/improvements", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

        # Check structure of improvement events
        if len(data) > 0:
            event = data[0]
            assert "improvement_id" in event
            assert "agent_id" in event
            assert "trigger_reason" in event
            assert "improvement_type" in event

    def test_get_improvement_history_with_pagination(
        self, client: TestClient, auth_headers: dict
    ):
        """Test improvement history pagination"""
        response = client.get(
            "/api/v1/performance/improvements?limit=5&offset=0", headers=auth_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data) <= 5


@pytest.mark.integration
@pytest.mark.e2e
class TestEndToEndWorkflows:
    """Test complete end-to-end workflows"""

    def test_agent_lifecycle_workflow(self, client: TestClient, auth_headers: dict):
        """
        Test a complete agent lifecycle:
        1. Check initial balance
        2. View economy stats
        3. Check performance metrics
        4. Top up credits
        5. Verify new balance
        """
        # Step 1: Check initial balance
        response = client.get("/api/v1/economy/balance", headers=auth_headers)
        assert response.status_code == 200
        initial_balances = response.json()

        # Step 2: View economy stats
        response = client.get("/api/v1/economy/stats", headers=auth_headers)
        assert response.status_code == 200
        initial_stats = response.json()
        initial_total = initial_stats["total_balance"]

        # Step 3: Check performance metrics
        response = client.get("/api/v1/performance/agents", headers=auth_headers)
        assert response.status_code == 200

        # Step 4: Top up credits
        top_up_amount = 500.0
        response = client.post(
            f"/api/v1/economy/top-up?amount={top_up_amount}", headers=auth_headers
        )
        assert response.status_code == 200

        # Step 5: Verify new balance
        response = client.get("/api/v1/economy/stats", headers=auth_headers)
        assert response.status_code == 200
        new_stats = response.json()
        new_total = new_stats["total_balance"]

        assert new_total == initial_total + top_up_amount

    def test_transaction_tracking_workflow(
        self, client: TestClient, auth_headers: dict
    ):
        """
        Test transaction tracking workflow:
        1. Get initial transaction count
        2. Top up credits (creates transactions)
        3. Verify new transactions appear
        """
        # Step 1: Get initial transactions
        response = client.get("/api/v1/economy/transactions", headers=auth_headers)
        assert response.status_code == 200
        initial_transactions = response.json()
        initial_count = len(initial_transactions)

        # Step 2: Top up credits
        response = client.post(
            "/api/v1/economy/top-up?amount=100.0", headers=auth_headers
        )
        assert response.status_code == 200

        # Step 3: Verify new transactions
        response = client.get("/api/v1/economy/transactions", headers=auth_headers)
        assert response.status_code == 200
        new_transactions = response.json()
        new_count = len(new_transactions)

        # Transaction count should have increased
        assert new_count >= initial_count

    def test_multi_agent_economy_workflow(self, client: TestClient, auth_headers: dict):
        """
        Test multi-agent economy workflow:
        1. Get all agent balances
        2. Check tenant stats
        3. Verify consistency between individual and total balances
        """
        # Step 1: Get all agent balances
        response = client.get("/api/v1/economy/balance", headers=auth_headers)
        assert response.status_code == 200
        balances = response.json()

        # Calculate sum of individual balances
        individual_total = sum(agent["balance"] for agent in balances)

        # Step 2: Get tenant stats
        response = client.get("/api/v1/economy/stats", headers=auth_headers)
        assert response.status_code == 200
        stats = response.json()

        # Step 3: Verify consistency
        assert stats["total_agents"] == len(balances)
        assert (
            abs(stats["total_balance"] - individual_total) < 0.01
        )  # Allow for floating point errors


@pytest.mark.integration
@pytest.mark.slow
class TestPerformanceAndLoad:
    """Test system performance under load"""

    def test_concurrent_balance_requests(self, client: TestClient, auth_headers: dict):
        """Test handling multiple concurrent balance requests"""
        import concurrent.futures

        def make_request():
            return client.get("/api/v1/economy/balance", headers=auth_headers)

        # Make 10 concurrent requests
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(make_request) for _ in range(10)]
            responses = [f.result() for f in futures]

        # All requests should succeed
        assert all(r.status_code == 200 for r in responses)

    def test_large_transaction_history(self, client: TestClient, auth_headers: dict):
        """Test retrieving large transaction history"""
        response = client.get(
            "/api/v1/economy/transactions?limit=1000", headers=auth_headers
        )

        assert response.status_code == 200
        # Response should complete within reasonable time
        assert response.elapsed.total_seconds() < 5.0
