"""
Authentication API Routes
Handles user registration, login, logout, and token management

Built with Pride for Obex Blackvault
"""
from fastapi import APIRouter, HTTPException, status, Depends, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, OAuth2PasswordRequestForm
from pydantic import BaseModel, Field, EmailStr
from typing import Optional
from datetime import datetime, timedelta
import uuid
import hashlib
import secrets

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])
security = HTTPBearer()


# ============================================================================
# Request/Response Models
# ============================================================================

class UserRegister(BaseModel):
    """User registration schema"""
    email: EmailStr = Field(..., description="User email address")
    password: str = Field(..., min_length=8, description="User password (min 8 characters)")
    name: Optional[str] = Field(None, min_length=1, description="User full name")
    full_name: Optional[str] = Field(None, min_length=1, description="User full name (alias for name)")
    tenant_id: Optional[str] = Field(None, description="Tenant ID (optional, will create if not provided)")
    
    def get_name(self) -> str:
        """Get name from either name or full_name field"""
        return self.name or self.full_name or "User"


class UserLogin(BaseModel):
    """User login schema (supports both JSON and form data)"""
    email: Optional[EmailStr] = Field(None, description="User email address")
    username: Optional[EmailStr] = Field(None, description="User email (OAuth2 compatibility)")
    password: str = Field(..., description="User password")
    
    def get_email(self) -> str:
        """Get email from either email or username field"""
        return self.email or self.username


class TokenResponse(BaseModel):
    """Token response schema"""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = 3600  # 1 hour
    user_id: str
    tenant_id: str


class TokenRefresh(BaseModel):
    """Token refresh schema"""
    refresh_token: str = Field(..., description="Refresh token")


class UserResponse(BaseModel):
    """User response schema"""
    id: str
    email: str
    name: str
    tenant_id: str
    created_at: datetime
    last_login: Optional[datetime] = None


# ============================================================================
# In-Memory Storage (Replace with database in production)
# ============================================================================

_users_db: dict[str, dict] = {}
_tokens_db: dict[str, dict] = {}  # access_token -> user_data
_refresh_tokens_db: dict[str, dict] = {}  # refresh_token -> user_data


# ============================================================================
# Helper Functions
# ============================================================================

def hash_password(password: str) -> str:
    """Hash password using SHA-256"""
    return hashlib.sha256(password.encode()).hexdigest()


def verify_password(password: str, hashed: str) -> bool:
    """Verify password against hash"""
    return hash_password(password) == hashed


def generate_token() -> str:
    """Generate secure random token"""
    return secrets.token_urlsafe(32)


def create_tokens(user_id: str, tenant_id: str) -> dict:
    """Create access and refresh tokens"""
    access_token = generate_token()
    refresh_token = generate_token()
    
    now = datetime.utcnow()
    expires_at = now + timedelta(hours=1)
    
    token_data = {
        "user_id": user_id,
        "tenant_id": tenant_id,
        "created_at": now,
        "expires_at": expires_at
    }
    
    _tokens_db[access_token] = token_data
    _refresh_tokens_db[refresh_token] = {
        **token_data,
        "expires_at": now + timedelta(days=30)  # Refresh token lasts 30 days
    }
    
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_in": 3600
    }


def verify_token(token: str) -> Optional[dict]:
    """Verify access token and return user data"""
    if token not in _tokens_db:
        return None
    
    token_data = _tokens_db[token]
    
    # Check if token expired
    if datetime.utcnow() > token_data["expires_at"]:
        del _tokens_db[token]
        return None
    
    return token_data


def revoke_token(token: str):
    """Revoke access token"""
    if token in _tokens_db:
        del _tokens_db[token]

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> dict:
    """
    Validate token and return current user info
    
    This dependency should be used on all protected endpoints to:
    1. Validate the access token
    2. Return user_id and tenant_id for authorization
    3. Raise 401 if token is invalid or expired
    
    Usage:
        @router.get("/protected")
        async def protected_endpoint(current_user: dict = Depends(get_current_user)):
            user_id = current_user["user_id"]
            tenant_id = current_user["tenant_id"]
            # ... endpoint logic
    
    Returns:
        dict: {
            "user_id": str,
            "tenant_id": str
        }
    
    Raises:
        HTTPException: 401 if token is invalid or expired
    """
    token = credentials.credentials
    token_data = verify_token(token)
    
    if not token_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    return {
        "user_id": token_data["user_id"],
        "tenant_id": token_data["tenant_id"]
    }

# ============================================================================
# API Endpoints
# ============================================================================

@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(user_data: UserRegister):
    """
    Register a new user
    
    Creates a new user account with email and password.
    """
    # Check if user already exists
    for user in _users_db.values():
        if user["email"] == user_data.email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User with this email already exists"
            )
    
    # Get name from either field
    user_name = user_data.get_name()
    
    # Create tenant if not provided
    tenant_id = user_data.tenant_id
    if not tenant_id:
        from backend.api.routes.tenants import _tenants_db
        tenant_id = f"tenant_{uuid.uuid4().hex[:12]}"
        _tenants_db[tenant_id] = {
            "id": tenant_id,
            "name": f"{user_name}'s Organization",
            "slug": f"org-{uuid.uuid4().hex[:8]}",
            "created_at": datetime.utcnow(),
            "settings": {}
        }
    
    # Create user
    user_id = f"user_{uuid.uuid4().hex[:12]}"
    now = datetime.utcnow()
    
    user = {
        "id": user_id,
        "email": user_data.email,
        "password_hash": hash_password(user_data.password),
        "name": user_name,
        "tenant_id": tenant_id,
        "created_at": now,
        "last_login": None
    }
    
    _users_db[user_id] = user
    
    return UserResponse(
        id=user["id"],
        email=user["email"],
        name=user["name"],
        tenant_id=user["tenant_id"],
        created_at=user["created_at"],
        last_login=user["last_login"]
    )


@router.post("/login", response_model=TokenResponse)
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    """
    User login
    
    Authenticates user and returns access and refresh tokens.
    Uses OAuth2 form data (username/password).
    """
    # OAuth2 uses 'username' field for email
    user_email = form_data.username
    
    # Find user by email
    user = None
    for u in _users_db.values():
        if u["email"] == user_email:
            user = u
            break
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )
    
    # Verify password
    if not verify_password(form_data.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )
    
    # Update last login
    user["last_login"] = datetime.utcnow()
    
    # Create tokens
    tokens = create_tokens(user["id"], user["tenant_id"])
    
    return TokenResponse(
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        token_type="bearer",
        expires_in=tokens["expires_in"],
        user_id=user["id"],
        tenant_id=user["tenant_id"]
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(token_data: TokenRefresh):
    """
    Refresh access token
    
    Uses refresh token to generate a new access token.
    """
    refresh_token = token_data.refresh_token
    
    if refresh_token not in _refresh_tokens_db:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token"
        )
    
    token_info = _refresh_tokens_db[refresh_token]
    
    # Check if refresh token expired
    if datetime.utcnow() > token_info["expires_at"]:
        del _refresh_tokens_db[refresh_token]
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token expired"
        )
    
    # Create new tokens
    tokens = create_tokens(token_info["user_id"], token_info["tenant_id"])
    
    # Revoke old refresh token
    del _refresh_tokens_db[refresh_token]
    
    return TokenResponse(
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        token_type="bearer",
        expires_in=tokens["expires_in"],
        user_id=token_info["user_id"],
        tenant_id=token_info["tenant_id"]
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    User logout
    
    Revokes the access token.
    """
    token = credentials.credentials
    revoke_token(token)
    return None


@router.get("/me", response_model=UserResponse)
async def get_me(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    Get current user information
    
    Returns information about the authenticated user.
    """
    token = credentials.credentials
    token_data = verify_token(token)
    
    if not token_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token"
        )
    
    user_id = token_data["user_id"]
    
    if user_id not in _users_db:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    user = _users_db[user_id]
    
    return UserResponse(
        id=user["id"],
        email=user["email"],
        name=user["name"],
        tenant_id=user["tenant_id"],
        created_at=user["created_at"],
        last_login=user["last_login"]
    )


@router.get("/verify", status_code=status.HTTP_200_OK)
async def verify_token_endpoint(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    Verify token validity
    
    Returns 200 if token is valid, 401 if invalid or expired.
    """
    token = credentials.credentials
    token_data = verify_token(token)
    
    if not token_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token"
        )
    
    return {
        "valid": True,
        "user_id": token_data["user_id"],
        "tenant_id": token_data["tenant_id"],
        "expires_at": token_data["expires_at"].isoformat()
    }
