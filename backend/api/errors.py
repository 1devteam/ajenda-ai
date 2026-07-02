"""Shared API error envelope for middleware and routes.

Structured errors use::

    {"detail": {"code": "...", "message": "...", ...}}

Simple legacy string errors remain ``{"detail": "..."}`` where routes have not
been migrated yet.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from fastapi.responses import JSONResponse

from backend.services.quota_enforcement import QuotaExceededError

AUTHENTICATION_REQUIRED_CODE = "AUTHENTICATION_REQUIRED"
AUTHENTICATION_REQUIRED_MESSAGE = "missing authentication credentials"
QUOTA_EXCEEDED_CODE = "QUOTA_EXCEEDED"
QUOTA_CHECK_UNAVAILABLE_CODE = "QUOTA_CHECK_UNAVAILABLE"
VALIDATION_ERROR_CODE = "VALIDATION_ERROR"


def structured_detail(*, code: str, message: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"code": code, "message": message}
    payload.update(extra)
    return payload


def api_json_response(*, status_code: int, code: str, message: str, **extra: Any) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"detail": structured_detail(code=code, message=message, **extra)},
    )


def http_error(*, status_code: int, code: str, message: str, **extra: Any) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail=structured_detail(code=code, message=message, **extra),
    )


def authentication_required_json() -> JSONResponse:
    return api_json_response(
        status_code=401,
        code=AUTHENTICATION_REQUIRED_CODE,
        message=AUTHENTICATION_REQUIRED_MESSAGE,
    )


def authentication_required_http() -> HTTPException:
    return http_error(
        status_code=401,
        code=AUTHENTICATION_REQUIRED_CODE,
        message=AUTHENTICATION_REQUIRED_MESSAGE,
    )


def quota_exceeded_detail(exc: QuotaExceededError) -> dict[str, Any]:
    return structured_detail(
        code=QUOTA_EXCEEDED_CODE,
        message=(
            f"You have reached the {exc.field} limit ({exc.limit}) "
            f"for the {exc.plan!r} plan. Upgrade to continue."
        ),
        field=exc.field,
        limit=exc.limit,
        current=exc.current,
        plan=exc.plan,
    )


def quota_exceeded_json(exc: QuotaExceededError) -> JSONResponse:
    return JSONResponse(status_code=402, content={"detail": quota_exceeded_detail(exc)})


def quota_exceeded_http(exc: QuotaExceededError) -> HTTPException:
    return HTTPException(status_code=402, detail=quota_exceeded_detail(exc))