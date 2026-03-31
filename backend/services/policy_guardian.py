from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    allowed: bool
    reason: str


class PolicyGuardian:
    """Foundational deny-by-default policy validator for protected actions."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def validate_privileged_action(self, *, tenant_id: str, action: str) -> PolicyDecision:
        if not tenant_id.strip():
            return PolicyDecision(False, "tenant_id is required")
        return PolicyDecision(
            allowed=False,
            reason=f"Privileged action '{action}' is not enabled in Phase 1 foundation.",
        )
