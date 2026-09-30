#!/usr/bin/env python3
"""Seed disposable, authoritative queue/lease fixtures for the live recovery matrix.

This utility is deliberately not a runtime recovery implementation. It creates
isolated test rows, queues them through ``ExecutionCoordinator``, claims/starts
them through ``WorkerRuntimeService``, and ages only the fixture heartbeats.
It refuses production and requires an explicit confirmation flag.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from backend.domain.enums import ExecutionTaskState, WorkerLeaseState
from backend.domain.execution_task import ExecutionTask
from backend.domain.mission import Mission
from backend.domain.tenant import Tenant
from backend.domain.worker_lease import WorkerLease
from backend.queue import RedisQueueAdapter
from backend.services.execution_coordinator import ExecutionCoordinator
from backend.services.quota_enforcement import QuotaEnforcementService
from backend.services.worker_runtime_service import WorkerRuntimeService


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--confirm-isolated",
        action="store_true",
        help="confirm that the target database/Redis pair is disposable and isolated",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("/tmp/ajenda-recovery-seed.json"),
        help="path for the generated task-ID manifest",
    )
    return parser


def _required_env(name: str, *fallbacks: str) -> str:
    value = os.environ.get(name, "").strip()
    if value:
        return value
    for fallback in fallbacks:
        value = os.environ.get(fallback, "").strip()
        if value:
            return value
    raise SystemExit(f"missing required environment variable: {name}")


def _assert_safe_environment(*, confirmed: bool) -> None:
    if not confirmed:
        raise SystemExit("refusing to seed without --confirm-isolated")
    if os.environ.get("AJENDA_ENV", "development").strip().lower() == "production":
        raise SystemExit("refusing to seed when AJENDA_ENV=production")
    if os.environ.get("AJENDA_VALIDATION_ENV", "").strip().lower() != "isolated":
        raise SystemExit("set AJENDA_VALIDATION_ENV=isolated before seeding")


def _create_task(
    session: Session,
    queue: RedisQueueAdapter,
    *,
    tenant_id: str,
    kind: str,
    running: bool,
    heartbeat_age_seconds: int,
) -> dict[str, str | int]:
    mission = Mission(
        tenant_id=tenant_id,
        objective=f"Recovery matrix fixture: {kind}",
        status="running",
    )
    session.add(mission)
    session.flush()

    task = ExecutionTask(
        tenant_id=tenant_id,
        mission_id=mission.id,
        title=f"Recovery matrix fixture: {kind}",
        description="Disposable operator-proof fixture; never a customer mission.",
        status=ExecutionTaskState.PLANNED.value,
        metadata_json={"task_type": "echo", "seed_source": "recovery_matrix"},
        compliance_category="operational",
        jurisdiction="US-ALL",
        requires_human_review=False,
    )
    session.add(task)
    session.flush()
    QuotaEnforcementService(session).check_and_record_task_creation(uuid.UUID(tenant_id))

    queued = ExecutionCoordinator(session, queue).queue_task(tenant_id=tenant_id, task_id=task.id)
    if not queued.ok:
        raise RuntimeError(f"failed to queue {kind} fixture: {queued.reason}")
    session.commit()

    worker_id = f"recovery-seed-{kind}"
    runtime = WorkerRuntimeService(session, queue)
    claimed = runtime.claim_next_task(tenant_id=tenant_id, worker_id=worker_id)
    if claimed is None:
        raise RuntimeError(f"failed to claim {kind} fixture through WorkerRuntimeService")
    session.refresh(claimed)
    lease_id_raw = claimed.metadata_json.get("worker_lease_id")
    if not isinstance(lease_id_raw, str):
        raise RuntimeError(f"{kind} fixture did not receive a durable worker lease ID")

    if running:
        runtime.start_execution(tenant_id=tenant_id, lease_id=uuid.UUID(lease_id_raw), worker_id=worker_id)

    lease = session.scalar(
        select(WorkerLease).where(WorkerLease.id == uuid.UUID(lease_id_raw), WorkerLease.task_id == task.id)
    )
    if lease is None:
        raise RuntimeError(f"{kind} fixture lease was not readable after admission")
    lease.heartbeat_at = datetime.now(UTC) - timedelta(seconds=heartbeat_age_seconds)
    session.commit()

    return {
        "task_id": str(task.id),
        "mission_id": str(mission.id),
        "lease_id": lease_id_raw,
        "worker_id": worker_id,
        "expected_task_status": ExecutionTaskState.RUNNING.value if running else ExecutionTaskState.CLAIMED.value,
        "expected_lease_status": WorkerLeaseState.ACTIVE.value if running else WorkerLeaseState.CLAIMED.value,
        "heartbeat_age_seconds": heartbeat_age_seconds,
    }


def seed() -> dict[str, object]:
    database_url = _required_env("AJENDA_DATABASE_URL", "AJENDA_DB_URL")
    queue_url = _required_env("AJENDA_QUEUE_URL", "AJENDA_REDIS_URL")
    engine = create_engine(database_url, pool_pre_ping=True)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    queue = RedisQueueAdapter(queue_url)
    if not queue.ping():
        raise SystemExit("Redis PING failed; refusing to create partial fixtures")

    tenant_id = str(uuid.uuid4())
    slug = f"recovery-seed-{tenant_id[:12]}"
    manifest: dict[str, object] = {
        "seed_source": "scripts/validation/seed_recovery_matrix.py",
        "created_at": datetime.now(UTC).isoformat(),
        "validation_env": os.environ.get("AJENDA_VALIDATION_ENV"),
        "tenant_id": tenant_id,
        "tenant_slug": slug,
        "fixtures": {},
    }

    session = factory()
    try:
        session.add(Tenant(id=uuid.UUID(tenant_id), name="Ajenda Recovery Matrix Fixture", slug=slug, plan="free"))
        session.commit()
        fixtures = {
            "claimed": _create_task(
                session,
                queue,
                tenant_id=tenant_id,
                kind="claimed",
                running=False,
                heartbeat_age_seconds=600,
            ),
            "running": _create_task(
                session,
                queue,
                tenant_id=tenant_id,
                kind="running",
                running=True,
                heartbeat_age_seconds=600,
            ),
            "idempotency": _create_task(
                session,
                queue,
                tenant_id=tenant_id,
                kind="idempotency",
                running=True,
                heartbeat_age_seconds=600,
            ),
            "healthy": _create_task(
                session,
                queue,
                tenant_id=tenant_id,
                kind="healthy",
                running=True,
                heartbeat_age_seconds=5,
            ),
        }
        manifest["fixtures"] = fixtures
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        engine.dispose()
    return manifest


def main() -> int:
    args = _parser().parse_args()
    _assert_safe_environment(confirmed=args.confirm_isolated)
    manifest = seed()
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    fixtures = manifest["fixtures"]
    assert isinstance(fixtures, dict)
    print(f"manifest={args.manifest}")
    print(f"AJENDA_TENANT_ID={manifest['tenant_id']}")
    print(f"AJENDA_CLAIMED_RECOVERY_TASK_ID={fixtures['claimed']['task_id']}")
    print(f"AJENDA_RUNNING_RECOVERY_TASK_ID={fixtures['running']['task_id']}")
    print(f"AJENDA_RECOVERY_IDEMPOTENCY_TASK_ID={fixtures['idempotency']['task_id']}")
    print(f"AJENDA_RECOVERY_STALE_TASK_ID={fixtures['claimed']['task_id']}")
    print(f"AJENDA_RECOVERY_HEALTHY_TASK_ID={fixtures['healthy']['task_id']}")
    print("fixtures are disposable; run recovery proofs before tearing down the isolated environment")
    return 0


if __name__ == "__main__":
    sys.exit(main())
