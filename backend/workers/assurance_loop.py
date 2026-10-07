"""Recurring multi-tenant continuous-assurance loop."""

from __future__ import annotations

import logging
import time

from backend.app.config import get_settings
from backend.db.session import DatabaseRuntime
from backend.db.tenant_session import activate_tenant_session
from backend.domain.assurance_snapshot import AssuranceMetricState
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

    records_all = []
    for tenant_id in tenant_ids:
        session = runtime.session_factory()
        try:
            activate_tenant_session(session, tenant_id)
            records = ContinuousAssuranceService(session).run_tenant(tenant_id=tenant_id)
            session.commit()
            records_all.extend(records)
        except Exception:
            session.rollback()
            logger.exception("continuous_assurance_tenant_failed", extra={"tenant_id": tenant_id})
        finally:
            session.close()

    metrics_session = runtime.session_factory()
    try:
        state = metrics_session.get(AssuranceMetricState, 1) or AssuranceMetricState(id=1)
        state.snapshot_count = len(records_all)
        state.aligned_count = sum(record.status == "aligned" for record in records_all)
        state.incomplete_count = sum(record.status == "incomplete" for record in records_all)
        state.drifted_count = sum(record.status == "drifted" for record in records_all)
        state.contradictory_count = sum(record.status == "contradictory" for record in records_all)
        state.first_divergence_count = sum(record.first_divergence is not None for record in records_all)
        state.calibration_sample_count = sum(record.calibration_eligible for record in records_all)
        state.calibration_aligned_count = sum(record.calibration_outcome_aligned is True for record in records_all)
        metrics_session.add(state)
        metrics_session.commit()
        if state.contradictory_count or state.drifted_count:
            logger.warning(
                "continuous_assurance_findings_present",
                extra={
                    "contradictory_count": state.contradictory_count,
                    "drifted_count": state.drifted_count,
                    "first_divergence_count": state.first_divergence_count,
                },
            )
    except Exception:
        metrics_session.rollback()
        logger.exception("continuous_assurance_metrics_failed")
    finally:
        metrics_session.close()
    return len(records_all)


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
