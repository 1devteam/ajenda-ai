"""Quota enforcement bridge helpers."""

from __future__ import annotations

from fastapi import HTTPException

from backend.services.quota_enforcement import QuotaExceededError


def quota_exceeded_response(exc: QuotaExceededError) -> HTTPException:
    return HTTPException(
        status_code=429,
        detail={
            "code": "QUOTA_EXCEEDED",
            "field": exc.field,
            "limit": exc.limit,
            "current": exc.current,
            "plan": exc.plan,
            "message": (
                f"You have reached the {exc.field} limit ({exc.limit}) for the {exc.plan!r} plan. Upgrade to continue."
            ),
        },
    )
