"""
Authentication API Routes
Handles user registration, login, logout, and token management
Migrated to SQLAlchemy database persistence

Built with Pride for Obex Blackvault
"""
from fastapi import APIRouter, HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field, EmailStr
from typing import Optional
from datetime import datetime, timedelta
from passlib.context import CryptContext
from jose import jwt
import uuid

from sqlalchemy.orm import Session
from backend.database import get_db
from backend.database.models import User, Token, Tenant
from backend.config.settings import settings

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])
security = HTTPBearer()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


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
    expires_in: int  # seconds
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
# Authentication Functions
# ============================================================================

def hash_password(password: str) -> str:
    """Hash password using bcrypt"""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password against hash"""
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(user_id: str, tenant_id: str) -> tuple[str, datetime]:
    """Create JWT access token"""
    expires_at = datetime.utcnow() + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "user_id": user_id,
        "tenant_id": tenant_id,
        "exp": expires_at,
        "type": "access"
    }
    token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return token, expires_at


def create_refresh_token(user_id: str, tenant_id: str) -> tuple[str, datetime]:
    """Create JWT refresh token"""
    expires_at = datetime.utcnow() + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {
        "user_id": user_id,
        "tenant_id": tenant_id,
        "exp": expires_at,
        "type": "refresh"
    }
    token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return token, expires_at


def verify_token(token: str) -> Optional[dict]:
    """Verify JWT token and return payload"""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
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
    
    # Check if token is revoked in database
    db_token = db.query(Token).filter(
        Token.token == token,
        Token.revoked == False
    ).first()
    
    if not db_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked or does not exist",
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
async def register(user_data: UserRegister, db: Session = Depends(get_db)):
    """
    Register a new user
    
    Creates a new user account with email and password.
    """
    # Check if user already exists
    existing_user = db.query(User).filter(User.email == user_data.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User with this email already exists"
        )
    
    # Get name from either field
    user_name = user_data.get_name()
    
    # Create tenant if not provided
    tenant_id = user_data.tenant_id
    if not tenant_id:
        tenant_id = f"tenant_{uuid.uuid4().hex[:12]}"
        tenant = Tenant(
            id=tenant_id,
            name=f"{user_name}'s Organization",
            slug=f"org-{uuid.uuid4().hex[:8]}",
            created_at=datetime.utcnow(),
            settings={}
        )
        db.add(tenant)
    
    # Create user
    user_id = f"user_{uuid.uuid4().hex[:12]}"
    user = User(
        id=user_id,
        email=user_data.email,
        name=user_name,
        password_hash=hash_password(user_data.password),
        tenant_id=tenant_id,
        created_at=datetime.utcnow()
    )
    
    db.add(user)
    db.commit()
    db.refresh(user)
    
    return UserResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        tenant_id=user.tenant_id,
        created_at=user.created_at,
        last_login=user.last_login
    )


@router.post("/login", response_model=TokenResponse)
async def login(credentials: UserLogin, db: Session = Depends(get_db)):
    """
    User login
    
    Authenticates user and returns access and refresh tokens.
    """
    email = credentials.get_email()
    
    # Find user
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(credentials.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )
    
    # Update last login
    user.last_login = datetime.utcnow()
    db.commit()
    
    # Create tokens
    access_token, access_expires = create_access_token(user.id, user.tenant_id)
    refresh_token, refresh_expires = create_refresh_token(user.id, user.tenant_id)
    
    # Store tokens in database
    db_access_token = Token(
        token=access_token,
        token_type="access",
        user_id=user.id,
        expires_at=access_expires,
        created_at=datetime.utcnow()
    )
    db_refresh_token = Token(
        token=refresh_token,
        token_type="refresh",
        user_id=user.id,
        expires_at=refresh_expires,
        created_at=datetime.utcnow()
    )
    
    db.add(db_access_token)
    db.add(db_refresh_token)
    db.commit()
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user_id=user.id,
        tenant_id=user.tenant_id
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token_endpoint(refresh_data: TokenRefresh, db: Session = Depends(get_db)):
    """
    Refresh access token
    
    Uses refresh token to get a new access token.
    """
    refresh_token = refresh_data.refresh_token
    
    # Verify refresh token
    token_data = verify_token(refresh_token)
    if not token_data or token_data.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token"
        )
    
    # Check if token exists and not revoked
    db_token = db.query(Token).filter(
        Token.token == refresh_token,
        Token.token_type == "refresh",
        Token.revoked == False
    ).first()
    
    if not db_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has been revoked or does not exist"
        )
    
    # Create new access token
    user_id = token_data["user_id"]
    tenant_id = token_data["tenant_id"]
    access_token, access_expires = create_access_token(user_id, tenant_id)
    
    # Store new access token
    db_access_token = Token(
        token=access_token,
        token_type="access",
        user_id=user_id,
        expires_at=access_expires,
        created_at=datetime.utcnow()
    )
    db.add(db_access_token)
    db.commit()
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user_id=user_id,
        tenant_id=tenant_id
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    current_user: dict = Depends(get_current_user),
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    """
    User logout
    
    Revokes the current access token.
    """
    token = credentials.credentials
    
    # Revoke token in database
    db_token = db.query(Token).filter(Token.token == token).first()
    if db_token:
        db_token.revoked = True
        db.commit()
    
    return None


@router.get("/me", response_model=UserResponse)
async def get_me(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get current user info
    
    Returns the authenticated user's information.
    """
    user_id = current_user["user_id"]
    user = db.query(User).filter(User.id == user_id).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    return UserResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        tenant_id=user.tenant_id,
        created_at=user.created_at,
        last_login=user.last_login
    )


@router.get("/verify")
async def verify_token_endpoint(current_user: dict = Depends(get_current_user)):
    """
    Verify token validity
    
    Returns 200 if token is valid, 401 otherwise.
    """
    return {"valid": True, "user_id": current_user["user_id"], "tenant_id": current_user["tenant_id"]}
