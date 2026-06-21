"""Client IP extraction and hashing for abuse prevention."""

from __future__ import annotations

import hashlib

from starlette.requests import Request


def extract_client_ip(request: Request) -> str:
    """Return the best-effort client IP for rate limiting.

    Uses the first hop of ``X-Forwarded-For`` when present; otherwise falls
    back to ``request.client.host``.
    """
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        first_hop = forwarded_for.split(",", 1)[0].strip()
        if first_hop:
            return first_hop
    if request.client is not None and request.client.host:
        return request.client.host
    return "unknown"


def hash_client_ip(ip: str, *, salt: str = "ajenda-signup-ip-v1") -> str:
    """Return a stable SHA-256 hex digest for an IP address."""
    normalized = ip.strip().lower()
    payload = f"{salt}:{normalized}".encode()
    return hashlib.sha256(payload).hexdigest()
