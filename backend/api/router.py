"""API router for Ajenda AI.

Versioning strategy:
- All business API routes are mounted under /v1/ prefix.
- Health and readiness probes remain at the root (/) so that K8s probes,
  load balancers, and Docker healthchecks do not need to know the API version.
- The /metrics endpoint (Prometheus) also remains at root.

When v2 is introduced, a new v2 APIRouter will be mounted alongside v1.
Both versions will coexist until v1 is formally deprecated.

Route inventory under /v1/:
  /v1/auth/*          — OIDC token exchange and introspection
  /v1/api-keys/*      — API key lifecycle management
  /v1/missions/*      — Mission queuing and management
  /v1/tasks/*         — Task queuing and state management
  /v1/workforce/*     — Workforce fleet management
  /v1/branches/*      — Execution branch management
  /v1/runtime/*       — Runtime governor controls
  /v1/operations/*    — Operational controls (pause, drain, resume)
  /v1/system/*        — System status and diagnostics
  /v1/observability/* — Observability endpoints (lineage, governance events)
  /v1/webhooks/*      — Tenant webhook endpoint management
  /v1/admin/*         — Platform admin control plane

Routes at root (/):
  /health             — Liveness probe (no auth required)
  /readiness          — Readiness probe (DB ping, no auth required)
  /metrics            — Prometheus metrics scrape endpoint
"""
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
from backend.api.routes.admin import router as admin_router
from backend.api.routes.webhooks import router as webhooks_router


def build_api_router() -> APIRouter:
    """Build and return the root API router.

    Health and metrics routes are mounted at / (no version prefix).
    All business routes are mounted under /v1/.
    """
    root = APIRouter()

    # --- Unversioned infrastructure routes ---
    # These must remain stable regardless of API version changes.
    root.include_router(health_router)  # /health, /readiness

    # --- v1 versioned business routes ---
    v1 = APIRouter(prefix="/v1")
    v1.include_router(auth_router)           # /v1/auth/*
    v1.include_router(api_keys_router)       # /v1/api-keys/*
    v1.include_router(mission_router)        # /v1/missions/*
    v1.include_router(task_router)           # /v1/tasks/*
    v1.include_router(workforce_router)      # /v1/workforce/*
    v1.include_router(branch_router)         # /v1/branches/*
    v1.include_router(runtime_router)        # /v1/runtime/*
    v1.include_router(operations_router)     # /v1/operations/*
    v1.include_router(system_router)         # /v1/system/*
    v1.include_router(observability_router)  # /v1/observability/*
    v1.include_router(webhooks_router)       # /v1/webhooks/*
    v1.include_router(admin_router)          # /v1/admin/* (platform control plane)

    root.include_router(v1)
    return root
