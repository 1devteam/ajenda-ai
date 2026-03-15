"""
Scheduler API — Omnipath v6.1 (The Scheduled Agent)

REST endpoints for managing scheduled agent missions.

Endpoints:
    POST   /api/v1/scheduler/jobs              — Create a new scheduled job
    GET    /api/v1/scheduler/jobs              — List all jobs for the current tenant
    GET    /api/v1/scheduler/jobs/{job_id}     — Get a single job by ID
    PUT    /api/v1/scheduler/jobs/{job_id}     — Update job metadata (name, description)
    DELETE /api/v1/scheduler/jobs/{job_id}     — Delete a job permanently
    POST   /api/v1/scheduler/jobs/{job_id}/pause   — Pause a job
    POST   /api/v1/scheduler/jobs/{job_id}/resume  — Resume a paused job
    POST   /api/v1/scheduler/jobs/{job_id}/trigger — Fire a job immediately

All endpoints require authentication.  Tenant isolation is enforced — users can
only manage jobs belonging to their own tenant.

Built with Pride for Obex Blackvault
"""

from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional

from backend.api.routes.auth import get_current_user
from backend.core.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/scheduler", tags=["scheduler"])


# =============================================================================
# Request / Response Models
# =============================================================================


class CreateJobRequest(BaseModel):
    """Request body for creating a new scheduled job."""

    name: str = Field(..., min_length=1, max_length=255, description="Human-readable job name")
    description: Optional[str] = Field(None, description="Optional description")
    agent_id: str = Field(..., description="Agent that will execute the missions")
    trigger_type: str = Field(..., description="'cron' or 'interval'")
    cron_expression: Optional[str] = Field(
        None, description="Cron expression (required when trigger_type='cron')"
    )
    interval_seconds: Optional[int] = Field(
        None, ge=1, description="Interval in seconds (required when trigger_type='interval')"
    )
    mission_payload: Dict[str, Any] = Field(
        ..., description="Mission specification submitted to MissionExecutor on each trigger"
    )
    max_runs: Optional[int] = Field(
        None, ge=1, description="Maximum number of runs (None = unlimited)"
    )


class UpdateJobRequest(BaseModel):
    """Request body for updating job metadata."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    mission_payload: Optional[Dict[str, Any]] = None
    max_runs: Optional[int] = Field(None, ge=1)


class JobResponse(BaseModel):
    """Serialised scheduled job."""

    id: str
    name: str
    description: Optional[str]
    tenant_id: str
    agent_id: str
    created_by: str
    trigger_type: str
    cron_expression: Optional[str]
    interval_seconds: Optional[int]
    mission_payload: Dict[str, Any]
    is_active: bool
    max_runs: Optional[int]
    run_count: int
    last_run_at: Optional[str]
    next_run_at: Optional[str]
    last_run_status: Optional[str]
    last_run_mission_id: Optional[str]
    created_at: Optional[str]
    updated_at: Optional[str]


class TriggerResponse(BaseModel):
    """Response from a manual trigger."""

    job_id: str
    mission_id: str
    message: str


# =============================================================================
# Dependency: get SchedulerService from main.py module-level ref
# =============================================================================


def _get_scheduler_service():
    """
    Retrieve the SchedulerService singleton stored in the main module.

    Returns None if the scheduler was not initialised (non-fatal for reads,
    but write operations will raise 503).
    """
    try:
        from backend.main import get_scheduler_service

        return get_scheduler_service()
    except (ImportError, AttributeError):
        return None


# =============================================================================
# Endpoints
# =============================================================================


@router.post(
    "/jobs",
    response_model=JobResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new scheduled job",
)
async def create_job(
    request: CreateJobRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Create a new scheduled job for the authenticated user's tenant.

    The job will be registered with APScheduler immediately and will fire
    according to the specified trigger (cron or interval).
    """
    scheduler = _get_scheduler_service()
    if scheduler is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Scheduler service not available",
        )

    tenant_id = current_user["tenant_id"]
    user_id = current_user["user_id"]

    try:
        job = await scheduler.create_job(
            tenant_id=tenant_id,
            agent_id=request.agent_id,
            created_by=user_id,
            name=request.name,
            description=request.description,
            trigger_type=request.trigger_type,
            cron_expression=request.cron_expression,
            interval_seconds=request.interval_seconds,
            mission_payload=request.mission_payload,
            max_runs=request.max_runs,
        )
        return job
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )
    except Exception as exc:
        logger.error(f"Failed to create job: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create scheduled job",
        )


@router.get(
    "/jobs",
    response_model=List[JobResponse],
    summary="List all scheduled jobs for the current tenant",
)
async def list_jobs(
    active_only: bool = False,
    current_user: dict = Depends(get_current_user),
):
    """
    List all scheduled jobs belonging to the authenticated user's tenant.

    Pass ``active_only=true`` to filter out paused jobs.
    """
    scheduler = _get_scheduler_service()
    if scheduler is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Scheduler service not available",
        )

    tenant_id = current_user["tenant_id"]
    try:
        jobs = await scheduler.list_jobs(tenant_id=tenant_id, active_only=active_only)
        return jobs
    except Exception as exc:
        logger.error(f"Failed to list jobs: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list scheduled jobs",
        )


@router.get(
    "/jobs/{job_id}",
    response_model=JobResponse,
    summary="Get a single scheduled job by ID",
)
async def get_job(
    job_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Get the details of a single scheduled job."""
    scheduler = _get_scheduler_service()
    if scheduler is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Scheduler service not available",
        )

    tenant_id = current_user["tenant_id"]
    job = await scheduler.get_job(job_id=job_id, tenant_id=tenant_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found",
        )
    return job


@router.put(
    "/jobs/{job_id}",
    response_model=JobResponse,
    summary="Update job metadata",
)
async def update_job(
    job_id: str,
    request: UpdateJobRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Update the name, description, mission_payload, or max_runs of a job.

    Trigger configuration (cron_expression / interval_seconds) cannot be
    changed after creation — delete and recreate the job instead.
    """
    scheduler = _get_scheduler_service()
    if scheduler is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Scheduler service not available",
        )

    tenant_id = current_user["tenant_id"]

    # Verify ownership
    job = await scheduler.get_job(job_id=job_id, tenant_id=tenant_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found",
        )

    try:
        from sqlalchemy import update as sa_update
        from backend.database.models import ScheduledJob
        from datetime import datetime

        updates: Dict[str, Any] = {"updated_at": datetime.utcnow()}
        if request.name is not None:
            updates["name"] = request.name
        if request.description is not None:
            updates["description"] = request.description
        if request.mission_payload is not None:
            updates["mission_payload"] = request.mission_payload
        if request.max_runs is not None:
            updates["max_runs"] = request.max_runs

        if len(updates) > 1:  # More than just updated_at
            async with scheduler._session_factory() as session:
                await session.execute(
                    sa_update(ScheduledJob).where(ScheduledJob.id == job_id).values(**updates)
                )
                await session.commit()

        return await scheduler.get_job(job_id=job_id, tenant_id=tenant_id)

    except Exception as exc:
        logger.error(f"Failed to update job {job_id}: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update scheduled job",
        )


@router.delete(
    "/jobs/{job_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a scheduled job permanently",
)
async def delete_job(
    job_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Permanently delete a scheduled job from the DB and APScheduler."""
    scheduler = _get_scheduler_service()
    if scheduler is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Scheduler service not available",
        )

    tenant_id = current_user["tenant_id"]
    try:
        await scheduler.delete_job(job_id=job_id, tenant_id=tenant_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    except Exception as exc:
        logger.error(f"Failed to delete job {job_id}: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete scheduled job",
        )


@router.post(
    "/jobs/{job_id}/pause",
    response_model=JobResponse,
    summary="Pause a scheduled job",
)
async def pause_job(
    job_id: str,
    current_user: dict = Depends(get_current_user),
):
    """
    Pause a scheduled job.

    The job record is retained in the database but removed from APScheduler.
    It can be resumed at any time via the ``/resume`` endpoint.
    """
    scheduler = _get_scheduler_service()
    if scheduler is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Scheduler service not available",
        )

    tenant_id = current_user["tenant_id"]
    try:
        return await scheduler.pause_job(job_id=job_id, tenant_id=tenant_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    except Exception as exc:
        logger.error(f"Failed to pause job {job_id}: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to pause scheduled job",
        )


@router.post(
    "/jobs/{job_id}/resume",
    response_model=JobResponse,
    summary="Resume a paused scheduled job",
)
async def resume_job(
    job_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Resume a previously paused scheduled job."""
    scheduler = _get_scheduler_service()
    if scheduler is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Scheduler service not available",
        )

    tenant_id = current_user["tenant_id"]
    try:
        return await scheduler.resume_job(job_id=job_id, tenant_id=tenant_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    except Exception as exc:
        logger.error(f"Failed to resume job {job_id}: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to resume scheduled job",
        )


@router.post(
    "/jobs/{job_id}/trigger",
    response_model=TriggerResponse,
    summary="Fire a job immediately (outside its schedule)",
)
async def trigger_job(
    job_id: str,
    current_user: dict = Depends(get_current_user),
):
    """
    Trigger a scheduled job to run immediately, regardless of its schedule.

    This is useful for testing a job or for one-off manual execution.
    The job's run_count is incremented and last_run_at is updated.
    """
    scheduler = _get_scheduler_service()
    if scheduler is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Scheduler service not available",
        )

    tenant_id = current_user["tenant_id"]
    try:
        mission_id = await scheduler.trigger_now(job_id=job_id, tenant_id=tenant_id)
        return TriggerResponse(
            job_id=job_id,
            mission_id=mission_id,
            message=f"Job {job_id} triggered. Mission {mission_id} is running.",
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    except Exception as exc:
        logger.error(f"Failed to trigger job {job_id}: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to trigger scheduled job",
        )
