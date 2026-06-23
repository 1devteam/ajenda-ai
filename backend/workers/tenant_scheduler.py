"""Worker tenant claim targets — single-tenant pin or multi-tenant round-robin."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Protocol

from sqlalchemy.orm import sessionmaker

from backend.app.config import Settings
from backend.repositories.tenant_repository import TenantRepository

logger = logging.getLogger("ajenda.worker_tenant_scheduler")


class TenantClaimTarget(Protocol):
    """Resolves which tenant queue a worker poll cycle should attempt to claim from."""

    def next_tenant_id(self) -> str | None: ...


@dataclass(slots=True)
class FixedTenantClaimTarget:
    """Single-tenant mode: always poll one configured tenant queue."""

    tenant_id: str

    def next_tenant_id(self) -> str | None:
        normalized = self.tenant_id.strip()
        return normalized or None


@dataclass(slots=True)
class RoundRobinActiveTenantClaimTarget:
    """Multi-tenant mode: fair round-robin across active tenants from the tenants table."""

    session_factory: sessionmaker  # type: ignore[type-arg]
    refresh_interval_seconds: float = 30.0
    _tenant_ids: list[str] = field(default_factory=list)
    _index: int = 0
    _last_refresh_monotonic: float = field(default=0.0, init=False)

    def next_tenant_id(self) -> str | None:
        self._maybe_refresh()
        if not self._tenant_ids:
            return None
        tenant_id = self._tenant_ids[self._index % len(self._tenant_ids)]
        self._index = (self._index + 1) % len(self._tenant_ids)
        return tenant_id

    def _maybe_refresh(self) -> None:
        if self._tenant_ids and (time.monotonic() - self._last_refresh_monotonic) < self.refresh_interval_seconds:
            return
        session = self.session_factory()
        try:
            tenant_ids = TenantRepository(session).list_active_tenant_ids()
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

        if tenant_ids != self._tenant_ids:
            logger.info(
                "worker_tenant_roster_refreshed",
                extra={"tenant_count": len(tenant_ids)},
            )
        self._tenant_ids = tenant_ids
        self._last_refresh_monotonic = time.monotonic()


def build_claim_target(
    settings: Settings,
    *,
    session_factory: sessionmaker,  # type: ignore[type-arg]
) -> TenantClaimTarget:
    """Build the worker claim target from runtime settings."""
    if settings.worker_tenant_mode == "multi":
        return RoundRobinActiveTenantClaimTarget(
            session_factory=session_factory,
            refresh_interval_seconds=settings.worker_tenant_refresh_seconds,
        )
    return FixedTenantClaimTarget(tenant_id=settings.worker_tenant_id)
