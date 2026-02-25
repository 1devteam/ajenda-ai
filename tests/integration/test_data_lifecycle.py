"""
Integration Tests for End-to-End Data Lifecycle
Tests the complete flow: Tenant → User → Agent → Mission with database persistence

Built with Pride for Obex Blackvault
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.main import app
from backend.database.base import Base
from backend.database import get_db

# ============================================================================
# Test Database Setup
# ============================================================================

# Use in-memory SQLite for testing
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    """Override the database dependency for testing"""
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db

client = TestClient(app)


@pytest.fixture(scope="function")
def test_db():
    """Create a fresh database for each test"""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


# ============================================================================
# Integration Tests
# ============================================================================

def test_complete_data_lifecycle(test_db):
    """
    Test the complete data lifecycle from tenant creation to mission execution
    
    This test verifies:
    1. Tenant creation and persistence
    2. User registration and authentication
    3. Agent deployment
    4. Mission creation
    5. Data integrity across all entities
    """
    
    # Step 1: Create a Tenant
    tenant_response = client.post(
        "/api/v1/tenants",
        json={
            "name": "Test Organization",
            "description": "Integration test tenant"
        }
    )
    assert tenant_response.status_code == 201
    tenant_data = tenant_response.json()
    tenant_id = tenant_data["id"]
    assert tenant_data["name"] == "Test Organization"
    assert tenant_data["slug"] == "test-organization"
    assert tenant_data["is_active"] is True
    
    # Step 2: Register a User
    user_response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "test@omnipath.ai",
            "password": "securepassword123",
            "name": "Test User",
            "tenant_id": tenant_id
        }
    )
    assert user_response.status_code == 201
    user_data = user_response.json()
    user_id = user_data["id"]
    assert user_data["email"] == "test@omnipath.ai"
    assert user_data["tenant_id"] == tenant_id
    
    # Step 3: Login and Get Access Token
    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "test@omnipath.ai",
            "password": "securepassword123"
        }
    )
    assert login_response.status_code == 200
    login_data = login_response.json()
    access_token = login_data["access_token"]
    assert login_data["user_id"] == user_id
    assert login_data["tenant_id"] == tenant_id
    
    # Step 4: Deploy an Agent
    agent_response = client.post(
        "/api/v1/agents",
        headers={"Authorization": f"Bearer {access_token}"},
        json={
            "name": "Test Commander",
            "type": "commander",
            "model": "gpt-4-turbo",
            "temperature": 0.7,
            "system_prompt": "You are a test commander agent",
            "capabilities": ["orchestration", "decision_making"]
        }
    )
    assert agent_response.status_code == 201
    agent_data = agent_response.json()
    agent_id = agent_data["id"]
    assert agent_data["name"] == "Test Commander"
    assert agent_data["type"] == "commander"
    assert agent_data["tenant_id"] == tenant_id
    assert agent_data["status"] == "idle"
    
    # Step 5: Create a Mission
    mission_response = client.post(
        "/api/v1/missions",
        headers={"Authorization": f"Bearer {access_token}"},
        json={
            "objective": "Test mission for integration testing",
            "agent_id": agent_id,
            "priority": "high",
            "context": {"test": True}
        }
    )
    assert mission_response.status_code == 201
    mission_data = mission_response.json()
    mission_id = mission_data["id"]
    assert mission_data["objective"] == "Test mission for integration testing"
    assert mission_data["agent_id"] == agent_id
    assert mission_data["tenant_id"] == tenant_id
    assert mission_data["status"] == "pending"
    
    # Step 6: Verify Data Persistence - Get Tenant
    tenant_get_response = client.get(f"/api/v1/tenants/{tenant_id}")
    assert tenant_get_response.status_code == 200
    tenant_get_data = tenant_get_response.json()
    assert tenant_get_data["agent_count"] == 1
    assert tenant_get_data["mission_count"] == 1
    
    # Step 7: Verify Data Persistence - Get Agent
    agent_get_response = client.get(
        f"/api/v1/agents/{agent_id}",
        headers={"Authorization": f"Bearer {access_token}"}
    )
    assert agent_get_response.status_code == 200
    agent_get_data = agent_get_response.json()
    assert agent_get_data["id"] == agent_id
    assert agent_get_data["total_missions"] >= 0
    
    # Step 8: Verify Data Persistence - Get Mission
    mission_get_response = client.get(
        f"/api/v1/missions/{mission_id}",
        headers={"Authorization": f"Bearer {access_token}"}
    )
    assert mission_get_response.status_code == 200
    mission_get_data = mission_get_response.json()
    assert mission_get_data["id"] == mission_id
    assert mission_get_data["status"] == "pending"


def test_tenant_isolation(test_db):
    """
    Test that tenants are properly isolated
    
    Verifies that users from one tenant cannot access resources from another tenant
    """
    
    # Create Tenant 1
    tenant1_response = client.post(
        "/api/v1/tenants",
        json={"name": "Tenant 1", "description": "First tenant"}
    )
    tenant1_id = tenant1_response.json()["id"]
    
    # Create Tenant 2
    tenant2_response = client.post(
        "/api/v1/tenants",
        json={"name": "Tenant 2", "description": "Second tenant"}
    )
    tenant2_id = tenant2_response.json()["id"]
    
    # Register User 1 in Tenant 1
    user1_response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "user1@tenant1.com",
            "password": "password123",
            "name": "User 1",
            "tenant_id": tenant1_id
        }
    )
    assert user1_response.status_code == 201
    
    # Register User 2 in Tenant 2
    user2_response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "user2@tenant2.com",
            "password": "password123",
            "name": "User 2",
            "tenant_id": tenant2_id
        }
    )
    assert user2_response.status_code == 201
    
    # Login as User 1
    login1_response = client.post(
        "/api/v1/auth/login",
        json={"email": "user1@tenant1.com", "password": "password123"}
    )
    token1 = login1_response.json()["access_token"]
    
    # Login as User 2
    login2_response = client.post(
        "/api/v1/auth/login",
        json={"email": "user2@tenant2.com", "password": "password123"}
    )
    token2 = login2_response.json()["access_token"]
    
    # Create Agent for Tenant 1
    agent1_response = client.post(
        "/api/v1/agents",
        headers={"Authorization": f"Bearer {token1}"},
        json={
            "name": "Agent 1",
            "type": "commander",
            "model": "gpt-4-turbo",
            "temperature": 0.7
        }
    )
    agent1_id = agent1_response.json()["id"]
    
    # Verify User 2 cannot access Agent 1 (tenant isolation)
    # Note: This test assumes the agents endpoint enforces tenant isolation
    # If it doesn't, this is a security issue that needs to be fixed
    agent_get_response = client.get(
        f"/api/v1/agents/{agent1_id}",
        headers={"Authorization": f"Bearer {token2}"}
    )
    # Should return 404 or 403 (not found or forbidden)
    assert agent_get_response.status_code in [403, 404]


def test_database_persistence_across_requests(test_db):
    """
    Test that data persists across multiple requests
    
    Verifies that the database correctly stores and retrieves data
    """
    
    # Create a tenant
    tenant_response = client.post(
        "/api/v1/tenants",
        json={"name": "Persistence Test", "description": "Test persistence"}
    )
    tenant_id = tenant_response.json()["id"]
    
    # Retrieve the tenant multiple times
    for _ in range(5):
        get_response = client.get(f"/api/v1/tenants/{tenant_id}")
        assert get_response.status_code == 200
        data = get_response.json()
        assert data["id"] == tenant_id
        assert data["name"] == "Persistence Test"
    
    # Update the tenant
    update_response = client.put(
        f"/api/v1/tenants/{tenant_id}",
        json={"name": "Updated Persistence Test"}
    )
    assert update_response.status_code == 200
    
    # Verify the update persisted
    get_response = client.get(f"/api/v1/tenants/{tenant_id}")
    assert get_response.json()["name"] == "Updated Persistence Test"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
