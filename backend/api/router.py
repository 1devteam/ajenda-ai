from __future__ import annotations

from fastapi import APIRouter

from backend.api.routes.auth import router as auth_router
from backend.api.routes.api_keys import router as api_keys_router
from backend.api.routes.branch import router as branch_router
from backend.api.routes.health import router as health_router
from backend.api.routes.mission import router as mission_router
from backend.api.routes.observability import router as observability_router
from backend.api.routes.operations import router as operations_router
from backend.api.routes.runtime import router as runtime_router
from backend.api.routes.system import router as system_router
from backend.api.routes.task import router as task_router
from backend.api.routes.workforce import router as workforce_router


def build_api_router() -> APIRouter:
    router = APIRouter()
    router.include_router(health_router)
    router.include_router(system_router)
    router.include_router(observability_router)
    router.include_router(operations_router)
    router.include_router(auth_router)
    router.include_router(api_keys_router)
    router.include_router(mission_router)
    router.include_router(workforce_router)
    router.include_router(task_router)
    router.include_router(branch_router)
    router.include_router(runtime_router)
    return router
