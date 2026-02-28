"""
FastAPI Logging Middleware for Omnipath v5.0
Automatically logs all API requests with structured data

Built with Pride for Obex Blackvault
"""

import time
import uuid
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from backend.core.logging_config import (
    get_logger,
    set_request_context,
    clear_request_context,
    log_api_request,
)


logger = get_logger(__name__)


class LoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware that logs all HTTP requests with structured data
    """

    def __init__(self, app: ASGIApp):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Process request and log details

        Args:
            request: Incoming HTTP request
            call_next: Next middleware/handler in chain

        Returns:
            HTTP response
        """
        # Generate request ID
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id

        # Extract user and tenant from request (if authenticated)
        user_id = getattr(request.state, "user_id", None)
        tenant_id = getattr(request.state, "tenant_id", None)

        # Set logging context
        set_request_context(request_id=request_id, user_id=user_id, tenant_id=tenant_id)

        # Start timer
        start_time = time.time()

        # Log request start
        logger.info(
            f"Request started: {request.method} {request.url.path}",
            extra={
                "event_type": "request_started",
                "http": {
                    "method": request.method,
                    "path": request.url.path,
                    "query_params": dict(request.query_params),
                    "client_host": request.client.host if request.client else None,
                    "user_agent": request.headers.get("user-agent"),
                },
            },
        )

        # Process request
        try:
            response = await call_next(request)

            # Calculate duration
            duration_ms = (time.time() - start_time) * 1000

            # Log successful request
            log_api_request(
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=duration_ms,
                query_params=dict(request.query_params),
            )

            # Add request ID to response headers
            response.headers["X-Request-ID"] = request_id

            return response

        except Exception as e:
            # Calculate duration
            duration_ms = (time.time() - start_time) * 1000

            # Log failed request
            logger.error(
                f"Request failed: {request.method} {request.url.path}",
                exc_info=True,
                extra={
                    "event_type": "request_failed",
                    "http": {
                        "method": request.method,
                        "path": request.url.path,
                        "query_params": dict(request.query_params),
                    },
                    "duration_ms": duration_ms,
                    "error": str(e),
                },
            )

            # Re-raise exception
            raise

        finally:
            # Clear logging context
            clear_request_context()


class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    Middleware that adds request ID to all requests
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Add request ID to request state

        Args:
            request: Incoming HTTP request
            call_next: Next middleware/handler in chain

        Returns:
            HTTP response
        """
        # Check if request ID already exists in headers
        request_id = request.headers.get("X-Request-ID")

        if not request_id:
            request_id = str(uuid.uuid4())

        # Store in request state
        request.state.request_id = request_id

        # Process request
        response = await call_next(request)

        # Add request ID to response
        response.headers["X-Request-ID"] = request_id

        return response
