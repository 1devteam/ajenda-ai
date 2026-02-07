"""
Rate Limiting Middleware for Omnipath v5.0
Prevents system overload by limiting requests per user/IP

Built with Pride for Obex Blackvault
"""

from fastapi import Request, HTTPException, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from typing import Dict, Tuple
import time
from collections import defaultdict
import asyncio

from backend.config.settings import settings


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Rate limiting middleware using sliding window algorithm.
    Tracks requests per IP address and per authenticated user.
    """
    
    def __init__(self, app):
        super().__init__(app)
        # Storage: {key: [(timestamp, count)]}
        self.request_history: Dict[str, list] = defaultdict(list)
        self.lock = asyncio.Lock()
        
        # Configuration from settings
        self.enabled = settings.RATE_LIMIT_ENABLED
        self.per_minute = settings.RATE_LIMIT_PER_MINUTE
        self.per_hour = settings.RATE_LIMIT_PER_HOUR
        
        # Cleanup task
        self.cleanup_task = None
    
    async def dispatch(self, request: Request, call_next):
        """Process request with rate limiting"""
        
        # Skip if rate limiting is disabled
        if not self.enabled:
            return await call_next(request)
        
        # Skip health check and metrics endpoints
        if request.url.path in ["/health", "/metrics", "/docs", "/openapi.json"]:
            return await call_next(request)
        
        # Get identifier (user ID or IP address)
        identifier = await self._get_identifier(request)
        
        # Check rate limits
        is_allowed, retry_after = await self._check_rate_limit(identifier)
        
        if not is_allowed:
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "error": "Rate limit exceeded",
                    "message": f"Too many requests. Please try again in {retry_after} seconds.",
                    "retry_after": retry_after
                },
                headers={"Retry-After": str(retry_after)}
            )
        
        # Record this request
        await self._record_request(identifier)
        
        # Process request
        response = await call_next(request)
        
        # Add rate limit headers
        remaining_minute, remaining_hour = await self._get_remaining(identifier)
        response.headers["X-RateLimit-Limit-Minute"] = str(self.per_minute)
        response.headers["X-RateLimit-Limit-Hour"] = str(self.per_hour)
        response.headers["X-RateLimit-Remaining-Minute"] = str(remaining_minute)
        response.headers["X-RateLimit-Remaining-Hour"] = str(remaining_hour)
        
        return response
    
    async def _get_identifier(self, request: Request) -> str:
        """Get unique identifier for rate limiting (user ID or IP)"""
        # Try to get user ID from auth
        user = getattr(request.state, "user", None)
        if user and hasattr(user, "id"):
            return f"user:{user.id}"
        
        # Fall back to IP address
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            ip = forwarded.split(",")[0].strip()
        else:
            ip = request.client.host if request.client else "unknown"
        
        return f"ip:{ip}"
    
    async def _check_rate_limit(self, identifier: str) -> Tuple[bool, int]:
        """
        Check if request is within rate limits.
        Returns (is_allowed, retry_after_seconds)
        """
        async with self.lock:
            now = time.time()
            history = self.request_history[identifier]
            
            # Remove old entries
            minute_ago = now - 60
            hour_ago = now - 3600
            history[:] = [ts for ts in history if ts > hour_ago]
            
            # Count requests in last minute and hour
            minute_count = sum(1 for ts in history if ts > minute_ago)
            hour_count = len(history)
            
            # Check limits
            if minute_count >= self.per_minute:
                # Calculate retry after (seconds until oldest request in minute window expires)
                oldest_in_minute = min([ts for ts in history if ts > minute_ago])
                retry_after = int(60 - (now - oldest_in_minute)) + 1
                return False, retry_after
            
            if hour_count >= self.per_hour:
                # Calculate retry after (seconds until oldest request expires)
                oldest = min(history)
                retry_after = int(3600 - (now - oldest)) + 1
                return False, retry_after
            
            return True, 0
    
    async def _record_request(self, identifier: str):
        """Record a request timestamp"""
        async with self.lock:
            now = time.time()
            self.request_history[identifier].append(now)
    
    async def _get_remaining(self, identifier: str) -> Tuple[int, int]:
        """Get remaining requests for minute and hour windows"""
        async with self.lock:
            now = time.time()
            history = self.request_history[identifier]
            
            minute_ago = now - 60
            hour_ago = now - 3600
            
            minute_count = sum(1 for ts in history if ts > minute_ago)
            hour_count = sum(1 for ts in history if ts > hour_ago)
            
            remaining_minute = max(0, self.per_minute - minute_count)
            remaining_hour = max(0, self.per_hour - hour_count)
            
            return remaining_minute, remaining_hour
    
    async def cleanup_old_entries(self):
        """Periodic cleanup of old entries (runs every 5 minutes)"""
        while True:
            await asyncio.sleep(300)  # 5 minutes
            async with self.lock:
                now = time.time()
                hour_ago = now - 3600
                
                # Remove entries older than 1 hour
                for identifier in list(self.request_history.keys()):
                    history = self.request_history[identifier]
                    history[:] = [ts for ts in history if ts > hour_ago]
                    
                    # Remove empty entries
                    if not history:
                        del self.request_history[identifier]
