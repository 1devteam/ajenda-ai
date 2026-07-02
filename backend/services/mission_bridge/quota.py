"""Quota enforcement bridge helpers."""

from __future__ import annotations

from fastapi import HTTPException

from backend.api.errors import quota_exceeded_http
from backend.services.quota_enforcement import QuotaExceededError


def quota_exceeded_response(exc: QuotaExceededError) -> HTTPException:
    return quota_exceeded_http(exc)
