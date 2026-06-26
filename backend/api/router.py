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
  /v1/ability-runtime/* — Product-facing worker ability runtime launcher
  /v1/api-keys/*      — API key lifecycle management
  /v1/capabilities/*  — Capability registry contracts
  /v1/capability-adapters/* — Capability execution adapter contracts
  /v1/business-profile/* — Business Profile durable tenant context
  /v1/evidence/*     — Evidence proof/provenance contracts
  /v1/outcome-reviews/* — Outcome review contracts
  /v1/retrieval-contracts/* — Retrieval and recall contracts
  /v1/mission-brief/* — Mission Brief read-model drafts
  /v1/missions/*      — Mission queuing and management
  /v1/tasks/*         — Task queuing and state management
  /v1/workforces/*    — Workforce fleet management
  /v1/branches/*      — Execution branch management
  /v1/runtime/*       — Runtime governor controls
  /v1/operations/*    — Operational controls (pause, drain, resume)
  /v1/system/*        — System status and diagnostics
  /v1/observability/* — Observability endpoints (lineage, governance events)
  /v1/webhooks/*      — Tenant webhook endpoint management
  /v1/billing/*       — Stripe checkout, portal, and webhook
  /v1/account/*       — Tenant self-service account, plan, usage, billing reads
  /v1/admin/*         — Platform admin control plane
  /v1/onboarding/*    — Self-serve tenant signup and verification
  /v1/plugins/*       — Plugin discovery and standard contracts

Routes at root (/):
  /health             — Liveness probe (no auth required)
  /readiness          — Readiness probe (DB ping, no auth required)

Metrics route:
  /v1/observability/metrics — Prometheus metrics scrape endpoint
"""

from __future__ import annotations

from fastapi import APIRouter

from backend.api.routes.ability_runtime import router as ability_runtime_router
from backend.api.routes.admin import router as admin_router
from backend.api.routes.api_keys import router as api_keys_router
from backend.api.routes.auth import router as auth_router
from backend.api.routes.branch import router as branch_router
from backend.api.routes.business_profile import router as business_profile_router
from backend.api.routes.capability import router as capability_router
from backend.api.routes.capability_adapter import router as capability_adapter_router
from backend.api.routes.evidence import router as evidence_router
from backend.api.routes.health import router as health_router
from backend.api.routes.mission import router as mission_router
from backend.api.routes.mission_brief import router as mission_brief_router
from backend.api.routes.observability import router as observability_router
from backend.api.routes.operations import router as operations_router
from backend.api.routes.outcome_review import router as outcome_review_router
from backend.api.routes.plugins import router as plugins_router
from backend.api.routes.retrieval_contract import router as retrieval_contract_router
from backend.api.routes.runtime import router as runtime_router
from backend.api.routes.system import router as system_router
from backend.api.routes.task import router as task_router
from backend.api.routes.webhooks import router as webhooks_router
from backend.api.routes.workforce import router as workforce_router

# Billing import is intentionally local to build_api_router() to avoid pulling
# the stripe dependency (and its import-time side effects) into every module
# that imports the router (common in unit/contract tests and non-billing paths).
# The actual app and full integration surfaces still require the billing routes.
# See PR 1 in the approved SaaS hardening plan.


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
    v1.include_router(auth_router)  # /v1/auth/*
    v1.include_router(ability_runtime_router)  # /v1/ability-runtime/*
    v1.include_router(api_keys_router)  # /v1/api-keys/*
    v1.include_router(capability_router)  # /v1/capabilities/*
    v1.include_router(capability_adapter_router)  # /v1/capability-adapters/*
    v1.include_router(business_profile_router)  # /v1/business-profile/*
    v1.include_router(evidence_router)  # /v1/evidence/*
    v1.include_router(outcome_review_router)  # /v1/outcome-reviews/*
    v1.include_router(retrieval_contract_router)  # /v1/retrieval-contracts/*
    v1.include_router(mission_brief_router)  # /v1/mission-brief/*
    v1.include_router(mission_router)  # /v1/missions/*
    v1.include_router(task_router)  # /v1/tasks/*
    v1.include_router(workforce_router)  # /v1/workforces/*
    v1.include_router(branch_router)  # /v1/branches/*
    v1.include_router(runtime_router)  # /v1/runtime/*
    v1.include_router(operations_router)  # /v1/operations/*
    v1.include_router(system_router)  # /v1/system/*
    v1.include_router(observability_router)  # /v1/observability/*
    v1.include_router(webhooks_router)  # /v1/webhooks/*

    # Lazy import of billing to keep stripe out of import-time for non-billing
    # test collection and modules. Actual build still wires the real router.
    from backend.api.routes.billing import router as billing_router

    v1.include_router(billing_router)  # /v1/billing/*

    from backend.api.routes.account import router as account_router

    v1.include_router(account_router)  # /v1/account/*

    v1.include_router(admin_router)  # /v1/admin/* (platform control plane)

    from backend.api.routes.onboarding import router as onboarding_router

    v1.include_router(onboarding_router)  # /v1/onboarding/*
    v1.include_router(plugins_router)  # /v1/plugins/*

    root.include_router(v1)
    return root
