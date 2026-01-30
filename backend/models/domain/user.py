"""
User Domain Model
Represents authenticated users in the Omnipath system
"""
from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from datetime import datetime
from enum import Enum


class UserRole(str, Enum):
    """User roles for RBAC"""
    ADMIN = "admin"
    DEVELOPER = "developer"
    OPERATOR = "operator"
    VIEWER = "viewer"


class User(BaseModel):
    """
    User model for authentication and authorization
    
    Used by the auth middleware to represent the current user
    """
    id: str = Field(..., description="Unique user identifier")
    email: EmailStr = Field(..., description="User email address")
    username: str = Field(..., description="Username")
    tenant_id: str = Field(..., description="Tenant/organization identifier")
    role: UserRole = Field(default=UserRole.VIEWER, description="User role for RBAC")
    is_active: bool = Field(default=True, description="Whether the user account is active")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Account creation timestamp")
    last_login: Optional[datetime] = Field(None, description="Last login timestamp")
    
    class Config:
        """Pydantic model configuration"""
        json_schema_extra = {
            "example": {
                "id": "usr_123456",
                "email": "user@example.com",
                "username": "johndoe",
                "tenant_id": "tenant_abc",
                "role": "developer",
                "is_active": True,
                "created_at": "2024-01-01T00:00:00Z",
                "last_login": "2024-01-30T12:00:00Z"
            }
        }


class UserCreate(BaseModel):
    """Schema for creating a new user"""
    email: EmailStr
    username: str
    password: str = Field(..., min_length=8, description="Password (min 8 characters)")
    tenant_id: str
    role: UserRole = UserRole.VIEWER


class UserLogin(BaseModel):
    """Schema for user login"""
    email: EmailStr
    password: str


class Token(BaseModel):
    """JWT token response"""
    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(..., description="Token expiration time in seconds")


class TokenData(BaseModel):
    """Data encoded in JWT token"""
    user_id: str
    email: str
    tenant_id: str
    role: str
