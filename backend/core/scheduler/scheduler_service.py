"""
Scheduler Service — Omnipath v6.1 (The Scheduled Agent)

APScheduler-backed service for managing recurring and one-off agent missions.
Integrates with the EventStore to emit scheduler lifecycle events.

Design:
  - Uses AsyncIOScheduler (APScheduler 3.x) — runs inside the FastAPI event loop.
  - Jobs are persisted in PostgreSQL via the ScheduledJob model.
  - On startup, all active jobs are loaded from the DB and re-registered with APScheduler.
  - Each job fires _trigger_job(), which creates a new mission via MissionExecutor.
  - Scheduler events (job.triggered, job.completed, job.failed) are written to EventStore.

Built with Pride for Obex Blackvault
"""

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.core.logging_config import get_logger, LoggerMixin
from backend.database.models import ScheduledJob

logger = get_logger(__name__)


class SchedulerService(LoggerMixin):
    """
    Manages scheduled agent missions.

    Lifecycle:
        1. ``start()``  — called from FastAPI lifespan startup.
        2. ``stop()``   — called from FastAPI lifespan shutdown.
        3. ``create_job()``   — persists a new ScheduledJob and registers it.
        4. ``pause_job()``    — marks job inactive and removes from APScheduler.
        5. ``resume_job()``   — marks job active and re-registers with APScheduler.
        6. ``delete_job()``   — removes from DB and APScheduler.
        7. ``trigger_now()``  — fires a job immediately (outside its schedule).
        8. ``list_jobs()``    — returns all jobs for a tenant.
        9. ``get_job()``      — returns a single job by ID.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker,
        mission_executor: Any,
        event_store: Any,
    ) -> None:
        """
        Args:
            session_factory:  AsyncSessionLocal — opens per-operation sessions.
            mission_executor: MissionExecutor instance for running missions.
            event_store:      EventStore instance for lifecycle event emission.
        """
        self._session_factory = session_factory
        self._mission_executor = mission_executor
        self._event_store = event_store
        self._scheduler = AsyncIOScheduler(timezone="UTC")

    # =========================================================================
    # Lifecycle
    # =========================================================================

    async def start(self) -> None:
        """
        Start the APScheduler and reload all active jobs from the database.

        Called once from the FastAPI lifespan startup handler.
        """
        self._scheduler.start()
        await self._reload_jobs()
        self.log_info("SchedulerService started")

    async def stop(self) -> None:
        """
        Gracefully shut down APScheduler.

        Called once from the FastAPI lifespan shutdown handler.
        """
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
        self.log_info("SchedulerService stopped")

    # =========================================================================
    # Job Management
    # =========================================================================

    async def create_job(
        self,
        tenant_id: str,
        agent_id: str,
        created_by: str,
        name: str,
        trigger_type: str,
        mission_payload: Dict[str, Any],
        description: Optional[str] = None,
        cron_expression: Optional[str] = None,
        interval_seconds: Optional[int] = None,
        max_runs: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Create a new scheduled job and register it with APScheduler.

        Args:
            tenant_id:         Owning tenant.
            agent_id:          Agent that will execute the missions.
            created_by:        User ID of the creator.
            name:              Human-readable job name.
            trigger_type:      ``"cron"`` or ``"interval"``.
            mission_payload:   Dict passed to MissionExecutor on each trigger.
            description:       Optional description.
            cron_expression:   Required when trigger_type == ``"cron"``.
            interval_seconds:  Required when trigger_type == ``"interval"``.
            max_runs:          Optional cap on total runs (None = unlimited).

        Returns:
            Serialised ScheduledJob dict.

        Raises:
            ValueError: If trigger configuration is invalid.
        """
        self._validate_trigger(trigger_type, cron_expression, interval_seconds)

        job_id = f"job_{uuid.uuid4().hex[:16]}"

        async with self._session_factory() as session:
            job = ScheduledJob(
                id=job_id,
                name=name,
                description=description,
                tenant_id=tenant_id,
                agent_id=agent_id,
                created_by=created_by,
                trigger_type=trigger_type,
                cron_expression=cron_expression,
                interval_seconds=interval_seconds,
                mission_payload=mission_payload,
                is_active=True,
                max_runs=max_runs,
                run_count=0,
            )
            session.add(job)
            await session.commit()
            await session.refresh(job)
            result = self._job_to_dict(job)

        # Register with APScheduler
        self._register_job(job_id, trigger_type, cron_expression, interval_seconds)

        await self._emit_event(
            aggregate_id=job_id,
            event_type="scheduler.job.created",
            data={
                "job_id": job_id,
                "name": name,
                "tenant_id": tenant_id,
                "agent_id": agent_id,
                "trigger_type": trigger_type,
            },
        )
        self.log_info(f"Job created: {name}", job_id=job_id, trigger_type=trigger_type)
        return result

    async def pause_job(self, job_id: str, tenant_id: str) -> Dict[str, Any]:
        """
        Pause a job — marks it inactive and removes it from APScheduler.

        Args:
            job_id:    Job to pause.
            tenant_id: Tenant guard (prevents cross-tenant access).

        Returns:
            Updated job dict.

        Raises:
            ValueError: If job not found or not owned by tenant.
        """
        job = await self._get_db_job(job_id, tenant_id)
        if not job:
            raise ValueError(f"Job {job_id} not found for tenant {tenant_id}")

        async with self._session_factory() as session:
            await session.execute(
                update(ScheduledJob)
                .where(ScheduledJob.id == job_id)
                .values(is_active=False, updated_at=datetime.utcnow())
            )
            await session.commit()

        if self._scheduler.get_job(job_id):
            self._scheduler.remove_job(job_id)

        await self._emit_event(
            aggregate_id=job_id,
            event_type="scheduler.job.paused",
            data={"job_id": job_id, "tenant_id": tenant_id},
        )
        self.log_info(f"Job paused: {job_id}")
        return await self.get_job(job_id, tenant_id)

    async def resume_job(self, job_id: str, tenant_id: str) -> Dict[str, Any]:
        """
        Resume a paused job — marks it active and re-registers with APScheduler.

        Args:
            job_id:    Job to resume.
            tenant_id: Tenant guard.

        Returns:
            Updated job dict.
        """
        job = await self._get_db_job(job_id, tenant_id)
        if not job:
            raise ValueError(f"Job {job_id} not found for tenant {tenant_id}")

        async with self._session_factory() as session:
            await session.execute(
                update(ScheduledJob)
                .where(ScheduledJob.id == job_id)
                .values(is_active=True, updated_at=datetime.utcnow())
            )
            await session.commit()

        self._register_job(
            job_id,
            job.trigger_type,
            job.cron_expression,
            job.interval_seconds,
        )

        await self._emit_event(
            aggregate_id=job_id,
            event_type="scheduler.job.resumed",
            data={"job_id": job_id, "tenant_id": tenant_id},
        )
        self.log_info(f"Job resumed: {job_id}")
        return await self.get_job(job_id, tenant_id)

    async def delete_job(self, job_id: str, tenant_id: str) -> None:
        """
        Permanently delete a job from the DB and APScheduler.

        Args:
            job_id:    Job to delete.
            tenant_id: Tenant guard.

        Raises:
            ValueError: If job not found or not owned by tenant.
        """
        job = await self._get_db_job(job_id, tenant_id)
        if not job:
            raise ValueError(f"Job {job_id} not found for tenant {tenant_id}")

        if self._scheduler.get_job(job_id):
            self._scheduler.remove_job(job_id)

        async with self._session_factory() as session:
            db_job = await session.get(ScheduledJob, job_id)
            if db_job:
                await session.delete(db_job)
                await session.commit()

        await self._emit_event(
            aggregate_id=job_id,
            event_type="scheduler.job.deleted",
            data={"job_id": job_id, "tenant_id": tenant_id},
        )
        self.log_info(f"Job deleted: {job_id}")

    async def trigger_now(self, job_id: str, tenant_id: str) -> str:
        """
        Fire a job immediately, outside its normal schedule.

        Args:
            job_id:    Job to trigger.
            tenant_id: Tenant guard.

        Returns:
            Mission ID of the triggered mission.

        Raises:
            ValueError: If job not found or not owned by tenant.
        """
        job = await self._get_db_job(job_id, tenant_id)
        if not job:
            raise ValueError(f"Job {job_id} not found for tenant {tenant_id}")

        mission_id = await self._trigger_job(job_id)
        self.log_info(f"Job triggered manually: {job_id}", mission_id=mission_id)
        return mission_id

    async def list_jobs(
        self,
        tenant_id: str,
        active_only: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        List all scheduled jobs for a tenant.

        Args:
            tenant_id:   Owning tenant.
            active_only: If True, return only active jobs.

        Returns:
            List of serialised job dicts.
        """
        async with self._session_factory() as session:
            query = select(ScheduledJob).where(ScheduledJob.tenant_id == tenant_id)
            if active_only:
                query = query.where(ScheduledJob.is_active.is_(True))
            query = query.order_by(ScheduledJob.created_at.desc())
            result = await session.execute(query)
            jobs = result.scalars().all()
            return [self._job_to_dict(j) for j in jobs]

    async def get_job(self, job_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a single job by ID.

        Args:
            job_id:    Job identifier.
            tenant_id: Tenant guard.

        Returns:
            Serialised job dict, or None if not found.
        """
        job = await self._get_db_job(job_id, tenant_id)
        if job is None:
            return None
        return self._job_to_dict(job)

    # =========================================================================
    # Internal helpers
    # =========================================================================

    async def _reload_jobs(self) -> None:
        """
        Load all active jobs from the database and register them with APScheduler.

        Called once at startup.  Jobs that were active before a restart are
        automatically re-registered so they continue to fire on schedule.
        """
        async with self._session_factory() as session:
            query = select(ScheduledJob).where(ScheduledJob.is_active.is_(True))
            result = await session.execute(query)
            jobs = result.scalars().all()

        count = 0
        for job in jobs:
            try:
                self._register_job(
                    job.id,
                    job.trigger_type,
                    job.cron_expression,
                    job.interval_seconds,
                )
                count += 1
            except Exception as exc:
                self.log_error(
                    f"Failed to reload job {job.id}: {exc}",
                    exc_info=True,
                    job_id=job.id,
                )
        self.log_info(f"Reloaded {count} scheduled jobs from database")

    def _register_job(
        self,
        job_id: str,
        trigger_type: str,
        cron_expression: Optional[str],
        interval_seconds: Optional[int],
    ) -> None:
        """
        Register a job with APScheduler.

        If a job with the same ID already exists it is replaced.
        """
        # Remove stale registration if present
        if self._scheduler.get_job(job_id):
            self._scheduler.remove_job(job_id)

        if trigger_type == "cron":
            trigger = CronTrigger.from_crontab(cron_expression, timezone="UTC")
        else:
            trigger = IntervalTrigger(seconds=interval_seconds, timezone="UTC")

        self._scheduler.add_job(
            func=self._trigger_job,
            trigger=trigger,
            id=job_id,
            args=[job_id],
            replace_existing=True,
            misfire_grace_time=300,  # Allow up to 5 min late firing
        )

    async def _trigger_job(self, job_id: str) -> str:
        """
        Execute a scheduled job: create and run a mission.

        This is the callback invoked by APScheduler on each trigger.
        It is also called directly by ``trigger_now()``.

        Args:
            job_id: The ScheduledJob ID.

        Returns:
            Mission ID of the created mission.
        """
        async with self._session_factory() as session:
            job = await session.get(ScheduledJob, job_id)
            if job is None:
                self.log_error(f"Job {job_id} not found during trigger")
                return ""

            if not job.is_active:
                self.log_info(f"Skipping inactive job: {job_id}")
                return ""

            # Enforce max_runs cap
            if job.max_runs is not None and job.run_count >= job.max_runs:
                self.log_info(f"Job {job_id} has reached max_runs={job.max_runs}; pausing")
                job.is_active = False
                await session.commit()
                if self._scheduler.get_job(job_id):
                    self._scheduler.remove_job(job_id)
                return ""

            # Snapshot job data before releasing the session
            tenant_id = job.tenant_id
            agent_id = job.agent_id
            mission_payload = dict(job.mission_payload)
            run_count = job.run_count

            # Mark as running
            job.last_run_at = datetime.utcnow()
            job.last_run_status = "running"
            job.run_count = run_count + 1
            await session.commit()

        mission_id = f"mission_{uuid.uuid4().hex[:16]}"
        try:
            await self._emit_event(
                aggregate_id=job_id,
                event_type="scheduler.job.triggered",
                data={
                    "job_id": job_id,
                    "mission_id": mission_id,
                    "tenant_id": tenant_id,
                    "agent_id": agent_id,
                    "run_count": run_count + 1,
                },
            )

            result = await self._mission_executor.execute_mission(
                mission_id=mission_id,
                goal=mission_payload.get("objective", "Scheduled mission"),
                tenant_id=tenant_id,
                user_id=mission_payload.get("user_id", "scheduler"),
                budget=mission_payload.get("budget"),
            )

            status = result.get("status", "COMPLETED") if result else "COMPLETED"
            async with self._session_factory() as session:
                await session.execute(
                    update(ScheduledJob)
                    .where(ScheduledJob.id == job_id)
                    .values(
                        last_run_status="success",
                        last_run_mission_id=mission_id,
                        updated_at=datetime.utcnow(),
                    )
                )
                await session.commit()

            await self._emit_event(
                aggregate_id=job_id,
                event_type="scheduler.job.completed",
                data={
                    "job_id": job_id,
                    "mission_id": mission_id,
                    "status": status,
                },
            )
            self.log_info(
                f"Job completed: {job_id}",
                mission_id=mission_id,
                status=status,
            )

        except Exception as exc:
            self.log_error(
                f"Job failed: {job_id}",
                exc_info=True,
                job_id=job_id,
                error=str(exc),
            )
            async with self._session_factory() as session:
                await session.execute(
                    update(ScheduledJob)
                    .where(ScheduledJob.id == job_id)
                    .values(
                        last_run_status="failed",
                        last_run_mission_id=mission_id,
                        updated_at=datetime.utcnow(),
                    )
                )
                await session.commit()

            await self._emit_event(
                aggregate_id=job_id,
                event_type="scheduler.job.failed",
                data={
                    "job_id": job_id,
                    "mission_id": mission_id,
                    "error": str(exc),
                },
            )

        return mission_id

    async def _get_db_job(self, job_id: str, tenant_id: str) -> Optional[ScheduledJob]:
        """Fetch a ScheduledJob from the DB, enforcing tenant isolation."""
        async with self._session_factory() as session:
            query = (
                select(ScheduledJob)
                .where(ScheduledJob.id == job_id)
                .where(ScheduledJob.tenant_id == tenant_id)
            )
            result = await session.execute(query)
            return result.scalar_one_or_none()

    async def _emit_event(
        self,
        aggregate_id: str,
        event_type: str,
        data: Dict[str, Any],
    ) -> None:
        """Emit a scheduler lifecycle event to the EventStore (non-fatal)."""
        if self._event_store is None:
            return
        try:
            await self._event_store.append(
                aggregate_id=aggregate_id,
                aggregate_type="scheduler",
                event_type=event_type,
                data=data,
            )
        except Exception as exc:
            self.log_error(
                f"Failed to emit scheduler event {event_type}: {exc}",
                exc_info=True,
            )

    @staticmethod
    def _validate_trigger(
        trigger_type: str,
        cron_expression: Optional[str],
        interval_seconds: Optional[int],
    ) -> None:
        """Validate trigger configuration before persisting."""
        if trigger_type not in ("cron", "interval"):
            raise ValueError(
                f"Invalid trigger_type '{trigger_type}'. Must be 'cron' or 'interval'."
            )
        if trigger_type == "cron":
            if not cron_expression:
                raise ValueError("cron_expression is required when trigger_type='cron'")
            # Validate the cron expression by constructing the trigger
            try:
                CronTrigger.from_crontab(cron_expression, timezone="UTC")
            except Exception as exc:
                raise ValueError(f"Invalid cron_expression '{cron_expression}': {exc}")
        else:
            if not interval_seconds or interval_seconds < 1:
                raise ValueError(
                    "interval_seconds must be a positive integer when trigger_type='interval'"
                )

    @staticmethod
    def _job_to_dict(job: ScheduledJob) -> Dict[str, Any]:
        """Serialise a ScheduledJob ORM object to a plain dict."""
        return {
            "id": job.id,
            "name": job.name,
            "description": job.description,
            "tenant_id": job.tenant_id,
            "agent_id": job.agent_id,
            "created_by": job.created_by,
            "trigger_type": job.trigger_type,
            "cron_expression": job.cron_expression,
            "interval_seconds": job.interval_seconds,
            "mission_payload": job.mission_payload,
            "is_active": job.is_active,
            "max_runs": job.max_runs,
            "run_count": job.run_count,
            "last_run_at": job.last_run_at.isoformat() if job.last_run_at else None,
            "next_run_at": job.next_run_at.isoformat() if job.next_run_at else None,
            "last_run_status": job.last_run_status,
            "last_run_mission_id": job.last_run_mission_id,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "updated_at": job.updated_at.isoformat() if job.updated_at else None,
        }
