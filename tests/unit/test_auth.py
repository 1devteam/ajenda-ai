"""
Unit Tests for Authentication and Authorization
Tests JWT tokens, user authentication, and role-based access control
"""
import pytest
from datetime import timedelta
from jose import jwt, JWTError

from backend.middleware.auth.auth_middleware import (
    create_access_token,
    decode_access_token
)
from backend.models.domain.user import User, UserRole, TokenData
from backend.config.settings import Settings
import os

# Set fixed JWT secret for testing
os.environ["JWT_SECRET_KEY"] = "test-secret-key-for-jwt-tokens-do-not-use-in-production"
os.environ["SECRET_KEY"] = "test-secret-key-do-not-use-in-production"

# Force reload of settings after environment variables are set
import importlib
import backend.middleware.auth.auth_middleware as auth_module
settings = Settings()
auth_module.settings = settings  # Override the module-level settings instance


@pytest.mark.unit
@pytest.mark.auth
class TestJWTTokens:
    """Test JWT token creation and validation"""
    
    def test_create_access_token(self, mock_user: User):
        """Test creating a valid JWT access token"""
        token_data = {
            "user_id": mock_user.id,
            "email": mock_user.email,
            "tenant_id": mock_user.tenant_id,
            "role": mock_user.role.value
        }
        
        token = create_access_token(token_data)
        
        assert isinstance(token, str)
        assert len(token) > 0
    
    def test_create_token_with_custom_expiration(self, mock_user: User):
        """Test creating a token with custom expiration time"""
        token_data = {
            "user_id": mock_user.id,
            "email": mock_user.email,
            "tenant_id": mock_user.tenant_id,
            "role": mock_user.role.value
        }
        
        expires_delta = timedelta(minutes=60)
        token = create_access_token(token_data, expires_delta)
        
        # Decode to verify expiration
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM]
        )
        
        assert "exp" in payload
    
    def test_decode_valid_token(self, mock_user: User):
        """Test decoding a valid JWT token"""
        token_data = {
            "user_id": mock_user.id,
            "email": mock_user.email,
            "tenant_id": mock_user.tenant_id,
            "role": mock_user.role.value
        }
        
        token = create_access_token(token_data)
        decoded = decode_access_token(token)
        
        assert decoded.user_id == mock_user.id
        assert decoded.email == mock_user.email
        assert decoded.tenant_id == mock_user.tenant_id
        assert decoded.role == mock_user.role.value
    
    def test_decode_invalid_token(self):
        """Test that invalid tokens are rejected"""
        from fastapi import HTTPException
        
        invalid_token = "invalid.token.here"
        
        with pytest.raises(HTTPException) as exc_info:
            decode_access_token(invalid_token)
        
        assert exc_info.value.status_code == 401
    
    def test_decode_expired_token(self, mock_user: User):
        """Test that expired tokens are rejected"""
        from fastapi import HTTPException
        
        token_data = {
            "user_id": mock_user.id,
            "email": mock_user.email,
            "tenant_id": mock_user.tenant_id,
            "role": mock_user.role.value
        }
        
        # Create token that expires immediately
        expires_delta = timedelta(seconds=-1)
        token = create_access_token(token_data, expires_delta)
        
        with pytest.raises(HTTPException) as exc_info:
            decode_access_token(token)
        
        assert exc_info.value.status_code == 401
    
    def test_token_contains_required_fields(self, mock_user: User):
        """Test that tokens contain all required fields"""
        token_data = {
            "user_id": mock_user.id,
            "email": mock_user.email,
            "tenant_id": mock_user.tenant_id,
            "role": mock_user.role.value
        }
        
        token = create_access_token(token_data)
        
        # Decode without validation to inspect payload
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM]
        )
        
        assert "user_id" in payload
        assert "email" in payload
        assert "tenant_id" in payload
        assert "role" in payload
        assert "exp" in payload


@pytest.mark.unit
@pytest.mark.auth
class TestUserModels:
    """Test user domain models"""
    
    def test_user_model_creation(self):
        """Test creating a User model"""
        user = User(
            id="test_123",
            email="test@example.com",
            username="testuser",
            tenant_id="tenant_123",
            role=UserRole.DEVELOPER
        )
        
        assert user.id == "test_123"
        assert user.email == "test@example.com"
        assert user.role == UserRole.DEVELOPER
        assert user.is_active is True
    
    def test_user_roles_enum(self):
        """Test UserRole enum values"""
        assert UserRole.ADMIN.value == "admin"
        assert UserRole.DEVELOPER.value == "developer"
        assert UserRole.OPERATOR.value == "operator"
        assert UserRole.VIEWER.value == "viewer"
    
    def test_user_model_validation(self):
        """Test that User model validates email format"""
        from pydantic import ValidationError
        
        with pytest.raises(ValidationError):
            User(
                id="test_123",
                email="invalid-email",  # Invalid email format
                username="testuser",
                tenant_id="tenant_123",
                role=UserRole.VIEWER
            )


@pytest.mark.integration
@pytest.mark.auth
class TestAuthenticationFlow:
    """Test complete authentication workflows"""
    
    @pytest.mark.asyncio
    async def test_get_current_user_with_valid_token(self, mock_user: User, auth_token: str):
        """Test getting current user with a valid token"""
        from fastapi.security import HTTPAuthorizationCredentials
        from backend.middleware.auth.auth_middleware import get_current_user
        
        credentials = HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials=auth_token
        )
        
        user = await get_current_user(credentials)
        
        assert user.id == mock_user.id
        assert user.email == mock_user.email
        assert user.tenant_id == mock_user.tenant_id
    
    @pytest.mark.asyncio
    async def test_get_current_user_with_invalid_token(self):
        """Test that invalid tokens are rejected"""
        from fastapi import HTTPException
        from fastapi.security import HTTPAuthorizationCredentials
        from backend.middleware.auth.auth_middleware import get_current_user
        
        credentials = HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials="invalid.token.here"
        )
        
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(credentials)
        
        assert exc_info.value.status_code == 401


@pytest.mark.integration
@pytest.mark.auth
class TestRoleBasedAccessControl:
    """Test role-based access control (RBAC)"""
    
    @pytest.mark.asyncio
    async def test_admin_has_highest_permissions(self, mock_admin_user: User):
        """Test that admin role has access to all resources"""
        from backend.middleware.auth.auth_middleware import require_role
        
        # Admin should pass all role checks
        for role in [UserRole.VIEWER, UserRole.OPERATOR, UserRole.DEVELOPER, UserRole.ADMIN]:
            checker = require_role(role)
            # This should not raise an exception
            result = await checker(mock_admin_user)
            assert result == mock_admin_user
    
    @pytest.mark.asyncio
    async def test_viewer_has_limited_permissions(self, mock_viewer_user: User):
        """Test that viewer role has limited access"""
        from fastapi import HTTPException
        from backend.middleware.auth.auth_middleware import require_role
        
        # Viewer should only pass viewer check
        viewer_checker = require_role(UserRole.VIEWER)
        result = await viewer_checker(mock_viewer_user)
        assert result == mock_viewer_user
        
        # Viewer should fail higher role checks
        admin_checker = require_role(UserRole.ADMIN)
        with pytest.raises(HTTPException) as exc_info:
            await admin_checker(mock_viewer_user)
        
        assert exc_info.value.status_code == 403
    
    @pytest.mark.asyncio
    async def test_role_hierarchy(self):
        """Test that role hierarchy is enforced correctly"""
        from backend.middleware.auth.auth_middleware import require_role
        
        # Create users with different roles
        viewer = User(
            id="viewer_1",
            email="viewer@test.com",
            username="viewer",
            tenant_id="test",
            role=UserRole.VIEWER
        )
        
        operator = User(
            id="operator_1",
            email="operator@test.com",
            username="operator",
            tenant_id="test",
            role=UserRole.OPERATOR
        )
        
        developer = User(
            id="dev_1",
            email="dev@test.com",
            username="developer",
            tenant_id="test",
            role=UserRole.DEVELOPER
        )
        
        # Test hierarchy: VIEWER < OPERATOR < DEVELOPER < ADMIN
        operator_checker = require_role(UserRole.OPERATOR)
        
        # Viewer should fail
        with pytest.raises(Exception):
            await operator_checker(viewer)
        
        # Operator should pass
        result = await operator_checker(operator)
        assert result == operator
        
        # Developer should pass (higher role)
        result = await operator_checker(developer)
        assert result == developer


@pytest.mark.integration
@pytest.mark.auth
class TestProtectedEndpoints:
    """Test that endpoints are properly protected"""
    
    def test_protected_endpoint_without_auth(self, client):
        """Test that protected endpoints reject requests without auth"""
        response = client.get("/api/v1/economy/balance")
        assert response.status_code == 403  # Forbidden (no auth header)
    
    def test_protected_endpoint_with_auth(self, client, auth_headers):
        """Test that protected endpoints accept valid auth"""
        response = client.get("/api/v1/economy/balance", headers=auth_headers)
        assert response.status_code == 200
    
    def test_protected_endpoint_with_invalid_token(self, client):
        """Test that protected endpoints reject invalid tokens"""
        headers = {"Authorization": "Bearer invalid.token.here"}
        response = client.get("/api/v1/economy/balance", headers=headers)
        assert response.status_code == 401
    
    def test_public_endpoints_dont_require_auth(self, client):
        """Test that public endpoints work without auth"""
        # Health check should be public
        response = client.get("/health")
        assert response.status_code == 200
        
        # Root endpoint should be public
        response = client.get("/")
        assert response.status_code == 200
