"""
Omnipath v5.0 - Main Application Entry Point
Multi-agent AI system with observability, meta-learning, and agent economy
"""

from fastapi import FastAPI, Request, status, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import asyncio
import logging
import time
import os

# Import configuration
from backend.config.settings import Settings
from backend.version import VERSION, VERSION_INFO

# Import observability
from backend.integrations.observability.telemetry import get_telemetry
from backend.integrations.observability.prometheus_metrics import (
    get_metrics,
)

# Import API routes
from backend.api.routes import (
    performance,
    metrics,
    meta_learning,
    tenants,
    agents,
    missions,
    auth,
    approval,
    compliance_reports,
    registry,
    tags,
    risk,
    dashboard,
    policies,
    audit,
    integrations,
    scheduler as scheduler_router,
    vault as vault_router,
    workforces as workforces_router,
    revenue as revenue_router,
)

# Import core services
from backend.integrations.llm.llm_service import LLMService
from backend.economy.resource_marketplace import ResourceMarketplace
from backend.core.event_bus.nats_bus import NATSEventBus
from backend.orchestration.mission_executor import MissionExecutor
from backend.domain.control.repositories.execution_runtime_repository import (
    ExecutionRuntimeRepository,
)
from backend.domain.control.services.execution_coordinator import ExecutionCoordinator
from backend.database.session import SessionLocal
from backend.middleware.rate_limit import RateLimitMiddleware
from backend.middleware.security_headers import SecurityHeadersMiddleware
from backend.security.secrets_validator import validate_secrets
from backend.core.cqrs.setup import setup_cqrs, teardown_cqrs
from backend.integrations.mcp.setup import setup_mcp, teardown_mcp
from typing import Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Initialize settings
settings = Settings()

# Initialize observability
telemetry = get_telemetry()
prom_metrics = get_metrics()

# Global service instances (initialized in lifespan)
llm_service: Optional[LLMService] = None
marketplace: Optional[ResourceMarketplace] = None
event_bus: Optional[NATSEventBus] = None
mission_executor: Optional[MissionExecutor] = None
_scheduler_service_ref = None
_vault_service_ref = None
_workforce_coordinator_ref = None
_revenue_agent_ref = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager
    Handles startup and shutdown events
    """
    # Startup
    _is_test_env = os.getenv("PYTEST_CURRENT_TEST") is not None or os.getenv(
        "TESTING", ""
    ).lower() in {"1", "true", "yes"}
    logger.info("=" * 60)
    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION}")

    # Validate secrets before anything else
    try:
        validate_secrets(environment=settings.ENVIRONMENT)
    except Exception as _sec_err:
        logger.critical(f"Secrets validation failed: {_sec_err}")
        raise
    logger.info(f"Environment: {settings.ENVIRONMENT}")
    logger.info(f"Debug mode: {settings.DEBUG}")
    logger.info("=" * 60)

    # NOTE: Database migrations are run by the Dockerfile CMD before uvicorn starts
    # (alembic upgrade head && uvicorn ...). Running migrations here would cause
    # deadlocks when multiple uvicorn workers each try to migrate simultaneously.
    logger.info("Database migrations handled by Dockerfile pre-start step")

    # Initialize OpenTelemetry
    if settings.OTEL_ENABLED:
        logger.info("Initializing OpenTelemetry...")
        telemetry.service_name = settings.OTEL_SERVICE_NAME
        telemetry.otlp_endpoint = settings.OTEL_EXPORTER_OTLP_ENDPOINT
        telemetry.enabled = settings.OTEL_ENABLED
        telemetry.initialize()
    else:
        logger.info("OpenTelemetry disabled")

    # Initialize Prometheus metrics
    if settings.PROMETHEUS_ENABLED:
        logger.info("✅ Prometheus metrics enabled")
        prom_metrics.enabled = True
        prom_metrics.set_app_info(
            version=settings.APP_VERSION, environment=settings.ENVIRONMENT
        )
    else:
        logger.info("Prometheus metrics disabled")
        prom_metrics.enabled = False

    # Initialize core services
    global llm_service, marketplace, event_bus, mission_executor

    # Initialize LLM Service
    logger.info("Initializing LLM Service...")
    llm_service = LLMService(settings)
    logger.info("✅ LLM Service initialized")

    # Log LLM provider configuration
    logger.info("LLM Providers configured:")
    if settings.OPENAI_API_KEY:
        logger.info("  - OpenAI: ✓")
    if settings.ANTHROPIC_API_KEY:
        logger.info("  - Anthropic (Claude): ✓")
    if settings.GOOGLE_API_KEY:
        logger.info("  - Google (Gemini): ✓")
    if settings.XAI_API_KEY:
        logger.info("  - xAI (Grok): ✓")
    if settings.OLLAMA_BASE_URL:
        logger.info(f"  - Ollama: ✓ ({settings.OLLAMA_BASE_URL})")

    # Initialize Resource Marketplace (Redis-backed with in-memory fallback)
    logger.info("Initializing Resource Marketplace...")
    marketplace = ResourceMarketplace()
    await marketplace.connect()
    logger.info("✅ Resource Marketplace initialized")

    # Initialize Event Bus
    logger.info("Initializing NATS Event Bus...")
    event_bus = NATSEventBus(settings.NATS_URL)
    if _is_test_env:
        logger.info("Skipping NATS connection in test environment; using stub mode")
    elif settings.NATS_ENABLED:
        try:
            await asyncio.wait_for(event_bus.connect(), timeout=3.0)
            logger.info("✅ NATS Event Bus connected")
        except Exception as e:
            logger.warning(f"NATS connection failed or timed out, using stub mode: {e}")
    else:
        logger.info("NATS disabled, using stub mode")

    # Initialize Mission Executor (event_store wired in after CQRS init below)
    logger.info("Initializing Mission Executor...")
    runtime_db = SessionLocal()
    runtime_repository = ExecutionRuntimeRepository(runtime_db)
    execution_coordinator = ExecutionCoordinator(
        runtime_repository=runtime_repository
    )
    mission_executor = MissionExecutor(
        marketplace=marketplace,
        event_bus=event_bus,
        llm_service=llm_service,
        execution_coordinator=execution_coordinator,
    )
    app.state.runtime_db = runtime_db
    logger.info("✅ Mission Executor initialized")
    # Initialize CQRS buses and wire EventStore into MissionExecutor
    logger.info("Initializing CQRS buses...")
    try:
        from backend.database.session import AsyncSessionLocal
        from backend.core.event_sourcing.event_store_impl import EventStore as ESImpl

        # Pass the session factory — EventStore opens its own session per operation
        _event_store = ESImpl(session_factory=AsyncSessionLocal)
        setup_cqrs(event_store=_event_store)
        # Wire the same EventStore instance into the MissionExecutor
        mission_executor.event_store = _event_store
        # Make event store available as a FastAPI dependency
        global _event_store_ref
        _event_store_ref = _event_store
        # Start the SagaOrchestrator — manages distributed transactions
        from backend.core.saga.saga_orchestrator import SagaOrchestrator

        saga_orchestrator = SagaOrchestrator(event_store=_event_store)
        app.state.saga_orchestrator = saga_orchestrator
        logger.info("✅ CQRS buses initialised — EventStore and SagaOrchestrator wired")
    except Exception as _cqrs_err:
        logger.warning(f"CQRS setup failed (non-fatal): {_cqrs_err}")

    # Initialize VaultService (AES-256-GCM encrypted external API key storage)
    logger.info("Initializing VaultService...")
    try:
        from backend.database.session import AsyncSessionLocal
        from backend.core.vault.vault_service import VaultService

        global _vault_service_ref
        _vault_service_ref = VaultService(
            session_factory=AsyncSessionLocal,
            secret_key=settings.SECRET_KEY,
        )
        logger.info("✅ VaultService initialised")
    except Exception as _vault_err:
        logger.warning(f"VaultService init failed (non-fatal): {_vault_err}")

    # Initialize RevenueAgent (Phase 5 — sales pipeline and deal closing)
    logger.info("Initializing RevenueAgent...")
    try:
        from backend.orchestration.revenue_agent import RevenueAgent

        global _revenue_agent_ref
        _revenue_agent_ref = RevenueAgent(
            llm_service=llm_service,
            event_store=_event_store_ref,
        )
        app.state.revenue_agent = _revenue_agent_ref
        logger.info("✅ RevenueAgent initialised")
    except Exception as _rev_err:
        logger.warning(f"RevenueAgent init failed (non-fatal): {_rev_err}")

    # Initialize WorkforceCoordinator (Phase 4 — multi-agent coordination)
    logger.info("Initializing WorkforceCoordinator...")
    try:
        from backend.orchestration.workforce_coordinator import WorkforceCoordinator

        global _workforce_coordinator_ref
        _workforce_coordinator_ref = WorkforceCoordinator(
            llm_service=llm_service,
            mission_executor=mission_executor,
            event_store=_event_store_ref,
            marketplace=marketplace,
            execution_coordinator=execution_coordinator,
        )
        app.state.workforce_coordinator = _workforce_coordinator_ref
        logger.info("✅ WorkforceCoordinator initialised")
    except Exception as _wfc_err:
        logger.warning(f"WorkforceCoordinator init failed (non-fatal): {_wfc_err}")

    # Initialize SchedulerService (APScheduler-backed recurring missions)
    if _is_test_env:
        logger.info("Skipping SchedulerService initialization in test environment")
    else:
        logger.info("Initializing SchedulerService...")
        try:
            from backend.database.session import AsyncSessionLocal
            from backend.core.scheduler.scheduler_service import SchedulerService

            global _scheduler_service_ref
            _scheduler_service_ref = SchedulerService(
                session_factory=AsyncSessionLocal,
                mission_executor=mission_executor,
                event_store=_event_store_ref,
            )
            await _scheduler_service_ref.start()
            app.state.scheduler_service = _scheduler_service_ref
            logger.info("✅ SchedulerService started")
        except Exception as _sched_err:
            logger.warning(f"SchedulerService init failed (non-fatal): {_sched_err}")

    # Initialize MCP subsystem
    if _is_test_env:
        logger.info("Skipping MCP subsystem initialization in test environment")
    else:
        logger.info("Initializing MCP subsystem...")
        try:
            await setup_mcp()
            logger.info("✅ MCP subsystem initialised")
        except Exception as _mcp_err:
            logger.warning(f"MCP setup failed (non-fatal): {_mcp_err}")

    # -------------------------------------------------------------------------
    # Register the Pride Protocol as an immutable system-level governance policy.
    # This policy cannot be deleted or modified via the API — it requires a code
    # deployment to change. It is registered every startup from source constants.
    # The preamble itself is enforced at the code level in assemble_prompt();
    # this policy registration provides the audit and visibility layer.
    # -------------------------------------------------------------------------
    logger.info("Registering Pride Protocol governance policy...")
    try:
        from backend.agents.compliance.policy_engine import (
            Policy,
            PolicyAction,
            PolicyStatus,
            ActionType,
            get_policy_manager,
        )
        from backend.agents.governance import PRIDE_PROTOCOL_VERSION

        _pride_policy_id = "citadel.pride.v1"
        _policy_manager = get_policy_manager()

        # Only register if not already present (singleton PolicyManager persists
        # across hot-reloads in development; skip re-registration gracefully).
        if _policy_manager.get_policy(_pride_policy_id) is None:
            _pride_policy = Policy(
                policy_id=_pride_policy_id,
                name="Pride Protocol — Citadel Core Governance",
                description=(
                    f"Immutable governance policy (v{PRIDE_PROTOCOL_VERSION}) that enforces "
                    "the Pride Protocol on all agents. "
                    "Proper actions / total actions >= 95%. "
                    "Applied as a system prompt prefix to every agent LLM call."
                ),
                status=PolicyStatus.ACTIVE,
                conditions=[],  # Applies to ALL agents unconditionally
                actions=[
                    PolicyAction(
                        action_type=ActionType.LOG_EVENT,
                        parameters={
                            "event": "pride_protocol_applied",
                            "version": PRIDE_PROTOCOL_VERSION,
                        },
                    )
                ],
                created_by="citadel.system",
                priority=9999,  # Highest priority — evaluated before all other policies
                applies_to=[],  # Empty = applies to all agent types
                immutable=True,
                metadata={
                    "protocol_version": PRIDE_PROTOCOL_VERSION,
                    "enforcement": "system_prompt_prefix",
                    "source": "backend.agents.governance.pride_kernel",
                },
            )
            _policy_manager.create_policy(_pride_policy)
            logger.info(
                f"✅ Pride Protocol policy registered: {_pride_policy_id} "
                f"(v{PRIDE_PROTOCOL_VERSION}, immutable=True, priority=9999)"
            )
        else:
            logger.info(
                f"✅ Pride Protocol policy already registered: {_pride_policy_id}"
            )
    except Exception as _pride_err:
        # Log but do not crash — the preamble is still enforced at the code level
        # in assemble_prompt(). The policy registration is the audit layer.
        logger.error(f"Pride Protocol policy registration failed: {_pride_err}")

    logger.info("=" * 60)
    logger.info(f"🚀 {settings.APP_NAME} v{settings.APP_VERSION} is ready!")
    logger.info("📚 API Documentation: http://localhost:8000/docs")
    logger.info("❤️  Health Check: http://localhost:8000/health")
    logger.info(f"📊 Metrics: http://localhost:8000{settings.METRICS_ENDPOINT}")
    if settings.OTEL_ENABLED:
        logger.info("🔍 Traces: http://localhost:16686 (Jaeger UI)")
    logger.info("=" * 60)

    yield

    # Shutdown
    logger.info(f"Shutting down {settings.APP_NAME}")

    # Disconnect event bus
    if event_bus:
        logger.info("Disconnecting NATS Event Bus...")
        await event_bus.disconnect()

    # Stop SchedulerService
    if _scheduler_service_ref is not None:
        try:
            await _scheduler_service_ref.stop()
            logger.info("✅ SchedulerService stopped")
        except Exception as _sched_stop_err:
            logger.warning(f"SchedulerService stop error: {_sched_stop_err}")

    # Teardown MCP subsystem
    await teardown_mcp()
    # Teardown CQRS buses
    teardown_cqrs()

    # Close durable runtime DB session if present
    runtime_db = getattr(app.state, "runtime_db", None)
    if runtime_db is not None:
        try:
            runtime_db.close()
            logger.info("✅ Runtime DB session closed")
        except Exception as _runtime_db_close_err:
            logger.warning(f"Runtime DB session close error: {_runtime_db_close_err}")

    telemetry.shutdown()
    logger.info("✅ Shutdown complete")


# Initialize FastAPI application
# Disable interactive API docs in non-development environments to prevent API surface disclosure
_is_development = settings.ENVIRONMENT == "development"
app = FastAPI(
    title=settings.APP_NAME,
    version=VERSION,
    description="Multi-agent AI system with observability, meta-learning, and agent economy",
    lifespan=lifespan,
    docs_url="/docs" if _is_development else None,
    redoc_url="/redoc" if _is_development else None,
    openapi_url="/openapi.json",
)

# Instrument FastAPI with OpenTelemetry
if settings.OTEL_ENABLED:
    telemetry.instrument_fastapi(app)

# Security headers middleware (outermost — applied to all responses)
app.add_middleware(SecurityHeadersMiddleware)

# CORS middleware
# In production: only allow explicitly whitelisted origins.
# In development: allow all origins for convenience.
_cors_origins = ["*"] if settings.DEBUG else settings.CORS_ORIGINS
_cors_methods = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
_cors_headers = [
    "Authorization",
    "Content-Type",
    "X-Request-ID",
    "X-Tenant-ID",
    "Accept",
    "Origin",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
    allow_methods=_cors_methods,
    allow_headers=_cors_headers,
    expose_headers=[
        "X-RateLimit-Limit-Minute",
        "X-RateLimit-Limit-Hour",
        "X-RateLimit-Remaining",
        "Retry-After",
    ],
    max_age=600,
)

# Rate limiting middleware
if settings.RATE_LIMIT_ENABLED:
    logger.info(
        f"Rate limiting enabled: {settings.RATE_LIMIT_PER_MINUTE}/min, {settings.RATE_LIMIT_PER_HOUR}/hour"  # noqa: E501
    )
    app.add_middleware(RateLimitMiddleware)


# Middleware for request metrics
@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    """Record HTTP request metrics"""
    start_time = time.time()

    # Process request
    response = await call_next(request)

    # Record metrics
    duration = time.time() - start_time
    prom_metrics.record_http_request(
        method=request.method,
        endpoint=request.url.path,
        status=response.status_code,
        duration_seconds=duration,
    )

    return response


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Handle uncaught exceptions gracefully"""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)

    # Record error metric
    prom_metrics.record_system_error(error_type=type(exc).__name__)

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "Internal server error",
            "error": str(exc) if settings.DEBUG else "An unexpected error occurred",
        },
    )


# Module-level references to services (set during lifespan startup)
_event_store_ref = None
# Note: _scheduler_service_ref and _vault_service_ref are declared in globals above


# Dependency function to get mission executor
def get_mission_executor() -> MissionExecutor:
    """
    Dependency to get mission executor instance

    Raises:
        HTTPException: If mission executor not initialized
    """
    if mission_executor is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Mission executor not initialized",
        )
    return mission_executor


def get_event_store():
    """
    Dependency to get the EventStore instance.
    Returns None if CQRS initialisation failed (non-fatal).
    """
    return _event_store_ref


def get_scheduler_service():
    """
    Dependency to get the SchedulerService instance.
    Returns None if SchedulerService initialisation failed (non-fatal).
    """
    return _scheduler_service_ref


def get_vault_service():
    """
    Dependency to get the VaultService instance.
    Returns None if VaultService initialisation failed (non-fatal).
    """
    return _vault_service_ref


def get_workforce_coordinator():
    """
    Dependency to get the WorkforceCoordinator instance.
    Returns None if WorkforceCoordinator initialisation failed (non-fatal).
    """
    return _workforce_coordinator_ref


def get_revenue_agent():
    """
    Dependency to get the RevenueAgent instance.
    Returns None if RevenueAgent initialisation failed (non-fatal).
    """
    return _revenue_agent_ref


# Health check endpoint
@app.get("/health", tags=["system"])
async def health_check():
    """
    Health check endpoint for monitoring and load balancers
    """
    return {
        "status": "ok",
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT,
        "observability": {
            "opentelemetry": settings.OTEL_ENABLED,
            "prometheus": settings.PROMETHEUS_ENABLED,
        },
    }


# Metrics endpoint is handled by backend.api.routes.metrics router


# Version endpoint
@app.get("/version", tags=["system"])
async def get_version():
    """
    Get version information
    """
    return VERSION_INFO


# Root endpoint
@app.get("/", tags=["system"])
async def root():
    """
    Root endpoint with API information
    """
    return {
        "service": settings.APP_NAME,
        "version": VERSION,
        "description": "Multi-agent AI system with observability and meta-learning",
        "docs": "/docs" if _is_development else None,
        "health": "/health",
        "metrics": settings.METRICS_ENDPOINT,
        "version_info": "/version",
    }


# Include API routers
app.include_router(auth.router)
app.include_router(tenants.router)
app.include_router(agents.router)
app.include_router(missions.router)
app.include_router(performance.router)
app.include_router(metrics.router)

app.include_router(meta_learning.router)
app.include_router(approval.router)
app.include_router(compliance_reports.router)
app.include_router(registry.router)
app.include_router(tags.router)
app.include_router(risk.router)
app.include_router(dashboard.router)
app.include_router(policies.router)
app.include_router(audit.router)
app.include_router(integrations.router)
app.include_router(scheduler_router.router)
app.include_router(vault_router.router)
app.include_router(workforces_router.router)
app.include_router(revenue_router.router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=settings.DEBUG)
