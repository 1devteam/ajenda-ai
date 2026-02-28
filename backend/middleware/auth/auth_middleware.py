"""
Authentication Middleware
Provides JWT authentication and current user dependency injection
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from datetime import datetime, timedelta
from typing import Optional

from backend.models.domain.user import User, TokenData, UserRole
from backend.config.settings import Settings

# Initialize settings
settings = Settings()

# Security scheme
security = HTTPBearer()


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Create a JWT access token

    Args:
        data: Data to encode in the token
        expires_delta: Token expiration time

    Returns:
        Encoded JWT token
    """
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({"exp": expire})

    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

    return encoded_jwt


def decode_access_token(token: str) -> TokenData:
    """
    Decode and validate a JWT access token

    Args:
        token: JWT token string

    Returns:
        TokenData extracted from the token

    Raises:
        HTTPException: If token is invalid or expired
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])

        user_id: str = payload.get("user_id")
        email: str = payload.get("email")
        tenant_id: str = payload.get("tenant_id")
        role: str = payload.get("role")

        if user_id is None or email is None:
            raise credentials_exception

        return TokenData(user_id=user_id, email=email, tenant_id=tenant_id, role=role)

    except JWTError:
        raise credentials_exception


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> User:
    """
    FastAPI dependency to get the current authenticated user

    This is used in route handlers like:
        @app.get("/protected")
        async def protected_route(current_user: User = Depends(get_current_user)):
            return {"user": current_user.email}

    Args:
        credentials: HTTP Bearer token from request header

    Returns:
        User object representing the authenticated user

    Raises:
        HTTPException: If authentication fails
    """
    token = credentials.credentials
    token_data = decode_access_token(token)

    # In production, you would fetch the user from the database here
    # For now, we construct a User object from the token data
    user = User(
        id=token_data.user_id,
        email=token_data.email,
        username=token_data.email.split("@")[0],  # Simple username from email
        tenant_id=token_data.tenant_id,
        role=UserRole(token_data.role),
        is_active=True,
        created_at=datetime.utcnow(),
        last_login=datetime.utcnow(),
    )

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user")

    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Dependency to ensure the current user is active
    """
    if not current_user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user")
    return current_user


def require_role(required_role: UserRole):
    """
    Dependency factory for role-based access control

    Usage:
        @app.get("/admin-only")
        async def admin_route(
            current_user: User = Depends(require_role(UserRole.ADMIN))
        ):
            return {"message": "Admin access granted"}
    """

    async def role_checker(current_user: User = Depends(get_current_user)) -> User:
        role_hierarchy = {
            UserRole.VIEWER: 0,
            UserRole.OPERATOR: 1,
            UserRole.DEVELOPER: 2,
            UserRole.ADMIN: 3,
        }

        if role_hierarchy.get(current_user.role, 0) < role_hierarchy.get(required_role, 999):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required role: {required_role.value}",
            )

        return current_user

    return role_checker
