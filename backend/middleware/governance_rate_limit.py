"""
Governance-Aware Rate Limiting
Risk-based rate limits for governance operations

Built with Pride for Obex Blackvault
"""
from fastapi import Request, HTTPException, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from typing import Dict, Tuple, Optional
import time
from collections import defaultdict
import asyncio
import logging

from backend.config.settings import settings
from backend.database.session import get_db
from backend.database.repositories import AssetRepository
from backend.database.governance_models import RiskTier

logger = logging.getLogger(__name__)


class GovernanceRateLimiter(BaseHTTPMiddleware):
    """
    Governance-aware rate limiting with risk-based limits
    
    Rate limits vary by:
    - User authority level
    - Asset risk tier
    - Operation type
    """
    
    # Base rate limits (requests per minute)
    BASE_LIMITS = {
        "guest": 10,
        "user": 30,
        "operator": 60,
        "admin": 120,
        "compliance_officer": 200
    }
    
    # Risk tier multipliers (reduce limits for high-risk operations)
    RISK_MULTIPLIERS = {
        RiskTier.MINIMAL: 1.0,
        RiskTier.LIMITED: 0.8,
        RiskTier.HIGH: 0.5,
        RiskTier.UNACCEPTABLE: 0.3
    }
    
    # Operation type multipliers
    OPERATION_MULTIPLIERS = {
        "read": 1.0,
        "write": 0.7,
        "delete": 0.5,
        "approve": 0.3
    }
    
    def __init__(self, app):
        super().__init__(app)
        self.request_history: Dict[str, list] = defaultdict(list)
        self.lock = asyncio.Lock()
        self.enabled = settings.RATE_LIMIT_ENABLED
    
    async def dispatch(self, request: Request, call_next):
        """Process request with governance-aware rate limiting"""
        
        if not self.enabled:
            return await call_next(request)
        
        # Skip health/metrics endpoints
        if request.url.path in ["/health", "/metrics", "/docs", "/openapi.json"]:
            return await call_next(request)
        
        # Get user and determine authority
        user = getattr(request.state, "user", None)
        if not user:
            # No user, apply strictest limit
            authority = "guest"
        else:
            authority = self._get_authority_level(user)
        
        # Determine operation type from method
        operation = self._get_operation_type(request.method)
        
        # Get risk tier if asset-related operation
        risk_tier = await self._get_risk_tier_from_request(request)
        
        # Calculate effective rate limit
        limit = self._calculate_rate_limit(authority, operation, risk_tier)
        
        # Check rate limit
        identifier = self._get_identifier(user, request)
        is_allowed, retry_after = await self._check_rate_limit(identifier, limit)
        
        if not is_allowed:
            logger.warning(
                f"Rate limit exceeded for {identifier} "
                f"(authority={authority}, operation={operation}, risk={risk_tier})"
            )
            
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "error": "Rate limit exceeded",
                    "message": f"Too many requests. Limit: {limit}/min. Retry in {retry_after}s.",
                    "retry_after": retry_after,
                    "limit": limit,
                    "authority": authority,
                    "risk_tier": risk_tier.value if risk_tier else None
                },
                headers={"Retry-After": str(retry_after)}
            )
        
        # Record request
        await self._record_request(identifier)
        
        # Process request
        response = await call_next(request)
        
        # Add rate limit headers
        remaining = await self._get_remaining(identifier, limit)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Authority"] = authority
        if risk_tier:
            response.headers["X-RateLimit-RiskTier"] = risk_tier.value
        
        return response
    
    def _get_authority_level(self, user) -> str:
        """Get user authority level"""
        if not user:
            return "guest"
        
        role = getattr(user, "role", None)
        if not role:
            return "user"
        
        role_str = role.value if hasattr(role, "value") else str(role)
        
        authority_map = {
            "viewer": "guest",
            "operator": "operator",
            "developer": "user",
            "admin": "admin",
            "compliance_officer": "compliance_officer"
        }
        
        return authority_map.get(role_str.lower(), "user")
    
    def _get_operation_type(self, method: str) -> str:
        """Get operation type from HTTP method"""
        operation_map = {
            "GET": "read",
            "POST": "write",
            "PUT": "write",
            "PATCH": "write",
            "DELETE": "delete"
        }
        return operation_map.get(method.upper(), "write")
    
    async def _get_risk_tier_from_request(
        self,
        request: Request
    ) -> Optional[RiskTier]:
        """
        Extract risk tier from request if asset-related
        
        Looks for asset_id in path or body
        """
        try:
            # Check path parameters
            asset_id = request.path_params.get("asset_id")
            if not asset_id:
                # Check query parameters
                asset_id = request.query_params.get("asset_id")
            
            if not asset_id:
                # Try to get from body (for POST/PUT)
                if request.method in ["POST", "PUT", "PATCH"]:
                    try:
                        body = await request.json()
                        asset_id = body.get("asset_id")
                    except:
                        pass
            
            if asset_id:
                # Fetch asset from database
                db = next(get_db())
                asset_repo = AssetRepository(db)
                asset = asset_repo.get(asset_id)
                if asset and asset.risk_tier:
                    return asset.risk_tier
        
        except Exception as e:
            logger.debug(f"Could not extract risk tier: {e}")
        
        return None
    
    def _calculate_rate_limit(
        self,
        authority: str,
        operation: str,
        risk_tier: Optional[RiskTier]
    ) -> int:
        """
        Calculate effective rate limit
        
        Formula: base_limit * operation_multiplier * risk_multiplier
        """
        base = self.BASE_LIMITS.get(authority, 30)
        
        op_mult = self.OPERATION_MULTIPLIERS.get(operation, 0.7)
        
        risk_mult = 1.0
        if risk_tier:
            risk_mult = self.RISK_MULTIPLIERS.get(risk_tier, 0.5)
        
        effective_limit = int(base * op_mult * risk_mult)
        
        # Minimum limit of 5 requests per minute
        return max(5, effective_limit)
    
    def _get_identifier(self, user, request: Request) -> str:
        """Get unique identifier for rate limiting"""
        if user and hasattr(user, "id"):
            return f"user:{user.id}"
        
        # Fall back to IP
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            ip = forwarded.split(",")[0].strip()
        else:
            ip = request.client.host if request.client else "unknown"
        
        return f"ip:{ip}"
    
    async def _check_rate_limit(
        self,
        identifier: str,
        limit: int
    ) -> Tuple[bool, int]:
        """
        Check if request is within rate limit
        
        Returns (is_allowed, retry_after_seconds)
        """
        async with self.lock:
            now = time.time()
            history = self.request_history[identifier]
            
            # Remove entries older than 1 minute
            minute_ago = now - 60
            history[:] = [ts for ts in history if ts > minute_ago]
            
            # Count requests in last minute
            count = len(history)
            
            if count >= limit:
                # Calculate retry after
                oldest = min(history)
                retry_after = int(60 - (now - oldest)) + 1
                return False, retry_after
            
            return True, 0
    
    async def _record_request(self, identifier: str):
        """Record request timestamp"""
        async with self.lock:
            now = time.time()
            self.request_history[identifier].append(now)
    
    async def _get_remaining(self, identifier: str, limit: int) -> int:
        """Get remaining requests in current window"""
        async with self.lock:
            now = time.time()
            history = self.request_history[identifier]
            
            minute_ago = now - 60
            count = sum(1 for ts in history if ts > minute_ago)
            
            return max(0, limit - count)
    
    async def cleanup_old_entries(self):
        """Periodic cleanup (every 5 minutes)"""
        while True:
            await asyncio.sleep(300)
            async with self.lock:
                now = time.time()
                minute_ago = now - 60
                
                for identifier in list(self.request_history.keys()):
                    history = self.request_history[identifier]
                    history[:] = [ts for ts in history if ts > minute_ago]
                    
                    if not history:
                        del self.request_history[identifier]
