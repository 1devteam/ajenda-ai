"""Recurring multi-tenant continuous-assurance loop."""

from __future__ import annotations

import logging
import time

from backend.app.config import get_settings
from backend.db.session import DatabaseRuntime
from backend.db.tenant_session import activate_tenant_session
from backend.repositories.tenant_repository import TenantRepository
from backend.services.continuous_assurance import ContinuousAssuranceService

logger = logging.getLogger("ajenda.assurance_loop")


def run_once(runtime: DatabaseRuntime) -> int:
    admin_session = runtime.session_factory()
    try:
        tenant_ids = TenantRepository(admin_session).list_active_tenant_ids()
        admin_session.rollback()
    finally:
        admin_session.close()

    snapshots = 0
    for tenant_id in tenant_ids:
        session = runtime.session_factory()
        try:
            activate_tenant_session(session, tenant_id)
            records = ContinuousAssuranceService(session).run_tenant(tenant_id=tenant_id)
            session.commit()
            snapshots += len(records)
        except Exception:
            session.rollback()
            logger.exception("continuous_assurance_tenant_failed", extra={"tenant_id": tenant_id})
        finally:
            session.close()
    return snapshots


def main() -> int:
    settings = get_settings()
    runtime = DatabaseRuntime(settings)
    interval = max(30.0, float(settings.assurance_interval_seconds))
    logger.info("continuous_assurance_started", extra={"interval_seconds": interval})
    try:
        while True:
            count = run_once(runtime)
            logger.info("continuous_assurance_cycle_completed", extra={"snapshot_count": count})
            time.sleep(interval)
    finally:
        runtime.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
