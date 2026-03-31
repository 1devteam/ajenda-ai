from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from backend.services.api_key_service import ApiKeyService
from backend.services.identity_service import IdentityService


class AuthContextMiddleware(BaseHTTPMiddleware):
    """Fail-closed authentication middleware with explicit public-route allowlist."""

    _PUBLIC_PATH_PREFIXES = (
        "/health",
        "/readiness",
    )

    def __init__(self, app, identity_service: IdentityService | None = None, api_key_service: ApiKeyService | None = None):
        super().__init__(app)
        self._identity_service = identity_service or IdentityService()
        self._api_key_service = api_key_service or ApiKeyService()

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        path = request.url.path
        if self._is_public_path(path):
            return await call_next(request)

        authorization = request.headers.get("Authorization")
        api_key = request.headers.get("X-Api-Key")
        tenant_id = getattr(request.state, "tenant_id", None)

        if authorization and authorization.startswith("Bearer "):
            token = authorization.removeprefix("Bearer ").strip()
            try:
                request.state.principal = self._identity_service.authenticate_user_bearer(token)
            except ValueError as exc:
                return JSONResponse(status_code=401, content={"detail": str(exc)})
            return await call_next(request)

        if api_key:
            if tenant_id is None:
                return JSONResponse(status_code=400, content={"detail": "tenant context required for api key auth"})
            try:
                key_id, plaintext = api_key.split(".", 1)
                request.state.principal = self._api_key_service.authenticate_machine(
                    tenant_id=tenant_id,
                    key_id=key_id,
                    plaintext=plaintext,
                )
            except Exception as exc:  # noqa: BLE001
                return JSONResponse(status_code=401, content={"detail": str(exc)})
            return await call_next(request)

        return JSONResponse(status_code=401, content={"detail": "missing authentication"})

    @classmethod
    def _is_public_path(cls, path: str) -> bool:
        return any(path.startswith(prefix) for prefix in cls._PUBLIC_PATH_PREFIXES)
