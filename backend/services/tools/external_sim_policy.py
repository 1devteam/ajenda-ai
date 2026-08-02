"""Policy for uncredentialed external tool paths.

Default: fail closed. Simulated external success is only allowed when
``AJENDA_ALLOW_SIMULATED_EXTERNAL=1`` (unit tests / local proof that intentionally
exercise the sim branch).
"""

from __future__ import annotations

import os


def allow_simulated_external() -> bool:
    """Return whether explicit external simulation is allowed in this process."""

    environment = (os.environ.get("AJENDA_ENV") or "development").strip().lower()
    if environment == "production":
        return False
    raw = (os.environ.get("AJENDA_ALLOW_SIMULATED_EXTERNAL") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def require_external_secret(*, secret: str | None, action: str) -> None:
    """Raise when a secret is missing and non-production simulation is not allowed."""

    if secret:
        return
    if allow_simulated_external():
        return
    raise ValueError(
        f"{action} requires a runtime credential; simulated external success is disabled "
        "(set AJENDA_ALLOW_SIMULATED_EXTERNAL=1 only for intentional local/sim tests)"
    )
