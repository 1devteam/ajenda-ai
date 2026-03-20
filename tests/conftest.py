"""
Pytest Configuration and Shared Fixtures
Provides reusable test fixtures for all test modules
"""
<<<<<<< ours
=======

>>>>>>> theirs
import os
import pytest
import asyncio
from typing import Generator, AsyncGenerator
from fastapi.testclient import TestClient
from httpx import AsyncClient
from sqlalchemy.engine.url import make_url

# Force lightweight, deterministic runtime for tests before importing app settings
os.environ.setdefault("TESTING", "1")
os.environ.setdefault("NATS_ENABLED", "false")
os.environ.setdefault("OTEL_ENABLED", "false")
os.environ.setdefault("PROMETHEUS_ENABLED", "false")

# Force lightweight, deterministic runtime for tests before importing app settings
os.environ.setdefault("TESTING", "1")
os.environ.setdefault("NATS_ENABLED", "false")
os.environ.setdefault("OTEL_ENABLED", "false")
os.environ.setdefault("PROMETHEUS_ENABLED", "false")

from backend.main import app
from backend.models.domain.user import User, UserRole
from backend.middleware.auth.auth_middleware import create_access_token
from backend.economy.resource_marketplace import ResourceMarketplace
from backend.config.settings import Settings
from backend.database.base import Base
from backend.database.session import engine


# ============================================================================
# Pytest Configuration
# ============================================================================


@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for the entire test session"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def test_settings():
    """
    Shared settings instance for all tests
    Uses a fixed JWT secret key to ensure token signing/verification works
    """
    import os

    os.environ["JWT_SECRET_KEY"] = (
        "test-secret-key-for-jwt-tokens-do-not-use-in-production"
    )
    os.environ["SECRET_KEY"] = "test-secret-key-do-not-use-in-production"
    return Settings()


<<<<<<< ours

@pytest.fixture(scope="session", autouse=True)
def initialize_test_database():
    """Ensure database schema exists for API/integration tests."""
    db_url = str(engine.url)
    parsed_url = make_url(db_url)

    # Guard against accidental DDL on shared/staging/prod databases.
    database_name = (parsed_url.database or "").lower()
    is_sqlite = parsed_url.get_backend_name().startswith("sqlite")
    is_test_database = "test" in database_name

    if not (is_sqlite or is_test_database):
        raise pytest.UsageError(
            "Refusing to run test schema bootstrap on a non-test database. "
            f"Current database: {db_url}. "
            "Use a dedicated test DB (name containing 'test') or SQLite."
        )

=======
@pytest.fixture(scope="session", autouse=True)
def initialize_test_database():
    """Ensure database schema exists for API/integration tests."""
>>>>>>> theirs
    Base.metadata.create_all(bind=engine)
    yield


# ============================================================================
# Application Fixtures
# ============================================================================


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    """
    Synchronous test client for FastAPI

    Usage:
        def test_health(client):
            response = client.get("/health")
            assert response.status_code == 200
    """
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
async def async_client() -> AsyncGenerator[AsyncClient, None]:
    """
    Asynchronous test client for FastAPI

    Usage:
        async def test_health(async_client):
            response = await async_client.get("http://test/health")
            assert response.status_code == 200
    """
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac


# ============================================================================
# User & Auth Fixtures
# ============================================================================


@pytest.fixture
def mock_user() -> User:
    """
    Create a mock user for testing

    Returns a standard user with DEVELOPER role
    """
    return User(
        id="test_user_123",
        email="test@example.com",
        username="testuser",
        tenant_id="test_tenant",
        role=UserRole.DEVELOPER,
        is_active=True,
    )


@pytest.fixture
def mock_admin_user() -> User:
    """Create a mock admin user for testing"""
    return User(
        id="admin_user_123",
        email="admin@example.com",
        username="adminuser",
        tenant_id="test_tenant",
        role=UserRole.ADMIN,
        is_active=True,
    )


@pytest.fixture
def mock_viewer_user() -> User:
    """Create a mock viewer user for testing"""
    return User(
        id="viewer_user_123",
        email="viewer@example.com",
        username="vieweruser",
        tenant_id="test_tenant",
        role=UserRole.VIEWER,
        is_active=True,
    )


@pytest.fixture
def auth_token(mock_user: User) -> str:
    """
    Create a valid JWT token for testing authenticated endpoints

    Usage:
        def test_protected_endpoint(client, auth_token):
            response = client.get(
                "/api/v1/economy/balance",
                headers={"Authorization": f"Bearer {auth_token}"}
            )
            assert response.status_code == 200
    """
    token_data = {
        "user_id": mock_user.id,
        "email": mock_user.email,
        "tenant_id": mock_user.tenant_id,
        "role": mock_user.role.value,
    }
    return create_access_token(token_data)


@pytest.fixture
def admin_auth_token(mock_admin_user: User) -> str:
    """Create a valid JWT token for admin user"""
    token_data = {
        "user_id": mock_admin_user.id,
        "email": mock_admin_user.email,
        "tenant_id": mock_admin_user.tenant_id,
        "role": mock_admin_user.role.value,
    }
    return create_access_token(token_data)


@pytest.fixture
def auth_headers(auth_token: str) -> dict:
    """
    Create authorization headers for authenticated requests

    Usage:
        def test_endpoint(client, auth_headers):
            response = client.get("/api/v1/economy/balance", headers=auth_headers)
    """
    return {"Authorization": f"Bearer {auth_token}"}


@pytest.fixture
def admin_auth_headers(admin_auth_token: str) -> dict:
    """Create authorization headers for admin user"""
    return {"Authorization": f"Bearer {admin_auth_token}"}


# ============================================================================
# Economy System Fixtures
# ============================================================================


@pytest.fixture
async def marketplace() -> ResourceMarketplace:
    """
    Create a fresh ResourceMarketplace instance for testing

    Each test gets its own isolated marketplace with clean state
    """
    mp = ResourceMarketplace()
    # Explicitly clear any shared state to ensure isolation
    mp._balances.clear()
    mp._transactions.clear()
    return mp


@pytest.fixture
async def marketplace_with_data(
    marketplace: ResourceMarketplace, mock_user: User
) -> ResourceMarketplace:
    """
    Create a marketplace with pre-populated test data

    Includes:
    - 3 agents with different balances
    - Multiple transactions
    - Various resource types
    """
    tenant_id = mock_user.tenant_id

    # Create agents with different balances
    await marketplace.charge(
        tenant_id, "agent_commander", 50.0, "llm_call", agent_type="commander"
    )
    await marketplace.reward(
        tenant_id, "agent_commander", 100.0, "mission_success", agent_type="commander"
    )

    await marketplace.charge(
        tenant_id, "agent_guardian", 10.0, "llm_call", agent_type="guardian"
    )
    await marketplace.charge(
        tenant_id, "agent_guardian", 5.0, "compute", agent_type="guardian"
    )

    await marketplace.charge(
        tenant_id, "agent_archivist", 200.0, "storage", agent_type="archivist"
    )
    await marketplace.reward(
        tenant_id, "agent_archivist", 50.0, "quality_bonus", agent_type="archivist"
    )

    return marketplace


# ============================================================================
# Test Data Fixtures
# ============================================================================


@pytest.fixture
def sample_mission_data() -> dict:
    """Sample mission data for testing"""
    return {
        "mission_id": "mission_test_001",
        "title": "Test Mission",
        "description": "A test mission for integration testing",
        "priority": "high",
        "assigned_agents": ["agent_commander", "agent_guardian"],
        "status": "pending",
    }


@pytest.fixture
def sample_agent_data() -> dict:
    """Sample agent data for testing"""
    return {
        "agent_id": "agent_test_001",
        "agent_type": "commander",
        "name": "Test Commander",
        "capabilities": ["planning", "coordination"],
        "status": "active",
    }


# ============================================================================
# Cleanup Fixtures
# ============================================================================


@pytest.fixture(autouse=True)
async def cleanup():
    """
    Automatic cleanup after each test

    This runs after every test to ensure clean state
    """
    yield
    # Add any cleanup logic here
    # For example: clear caches, reset singletons, etc.
