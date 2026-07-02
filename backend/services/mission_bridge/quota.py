"""Quota enforcement bridge helpers."""

from __future__ import annotations

from backend.api.errors import quota_exceeded_http
from backend.services.quota_enforcement import QuotaExceededError


def quota_exceeded_response(exc: QuotaExceededError):
    return quota_exceeded_http(exc)