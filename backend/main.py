"""
Omnipath v5.0 - Main Application Entry Point
Multi-agent AI system with observability, meta-learning, and agent economy
"""
from fastapi import FastAPI, Request, status, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging
import time

# Import configuration
from backend.config.settings import Settings
from backend.version import VERSION, VERSION_INFO

# Import observability
from backend.integrations.observability.telemetry import get_telemetry
from backend.integrations.observability.prometheus_metrics import get_metrics, metrics_endpoint

# Import API routes
from backend.api.routes import economy, performance, metrics, missions_v45, meta_learning, tenants, agents, missions, auth, approval, compliance_reports, registry

# Import core services
from backend.integrations.llm.llm_service import LLMService
from backend.economy.resource_marketplace import ResourceMarketplace
from backend.core.event_bus.nats_bus import NATSEventBus
from backend.orchestration.mission_executor import MissionExecutor
from backend.middleware.rate_limit import RateLimitMiddleware
from typing import Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager
    Handles startup and shutdown events
    """
    # Startup
    logger.info("=" * 60)
    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION}")
    logger.info(f"Environment: {settings.ENVIRONMENT}")
    logger.info(f"Debug mode: {settings.DEBUG}")
    logger.info("=" * 60)
    
    # Run database migrations
    logger.info("Running database migrations...")
    try:
        from alembic.config import Config
        from alembic import command
        import os
        
        alembic_cfg = Config(os.path.join(os.path.dirname(os.path.dirname(__file__)), "alembic.ini"))
        command.upgrade(alembic_cfg, "head")
        logger.info("✅ Database migrations completed")
    except Exception as e:
        logger.warning(f"Database migration failed: {e}")
        logger.warning("Continuing startup without migrations...")
    
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
            version=settings.APP_VERSION,
            environment=settings.ENVIRONMENT
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
    
    # Initialize Resource Marketplace
    logger.info("Initializing Resource Marketplace...")
    marketplace = ResourceMarketplace()
    logger.info("✅ Resource Marketplace initialized")
    
    # Initialize Event Bus
    logger.info("Initializing NATS Event Bus...")
    event_bus = NATSEventBus(settings.NATS_URL)
    if settings.NATS_ENABLED:
        try:
            await event_bus.connect()
            logger.info("✅ NATS Event Bus connected")
        except Exception as e:
            logger.warning(f"NATS connection failed, using stub mode: {e}")
    else:
        logger.info("NATS disabled, using stub mode")
    
    # Initialize Mission Executor
    logger.info("Initializing Mission Executor...")
    mission_executor = MissionExecutor(
        marketplace=marketplace,
        event_bus=event_bus,
        llm_service=llm_service
    )
    logger.info("✅ Mission Executor initialized")
    
    logger.info("=" * 60)
    logger.info(f"🚀 {settings.APP_NAME} v{settings.APP_VERSION} is ready!")
    logger.info(f"📚 API Documentation: http://localhost:8000/docs")
    logger.info(f"❤️  Health Check: http://localhost:8000/health")
    logger.info(f"📊 Metrics: http://localhost:8000{settings.METRICS_ENDPOINT}")
    if settings.OTEL_ENABLED:
        logger.info(f"🔍 Traces: http://localhost:16686 (Jaeger UI)")
    logger.info("=" * 60)
    
    yield
    
    # Shutdown
    logger.info(f"Shutting down {settings.APP_NAME}")
    
    # Disconnect event bus
    if event_bus:
        logger.info("Disconnecting NATS Event Bus...")
        await event_bus.disconnect()
    
    telemetry.shutdown()
    logger.info("✅ Shutdown complete")


# Initialize FastAPI application
app = FastAPI(
    title=settings.APP_NAME,
    version=VERSION,
    description="Multi-agent AI system with observability, meta-learning, and agent economy",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)

# Instrument FastAPI with OpenTelemetry
if settings.OTEL_ENABLED:
    telemetry.instrument_fastapi(app)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.DEBUG else settings.CORS_ORIGINS,
    allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate limiting middleware
if settings.RATE_LIMIT_ENABLED:
    logger.info(f"Rate limiting enabled: {settings.RATE_LIMIT_PER_MINUTE}/min, {settings.RATE_LIMIT_PER_HOUR}/hour")
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
        duration_seconds=duration
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
            "error": str(exc) if settings.DEBUG else "An unexpected error occurred"
        }
    )


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
            detail="Mission executor not initialized"
        )
    return mission_executor


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
            "prometheus": settings.PROMETHEUS_ENABLED
        }
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
        "docs": "/docs",
        "health": "/health",
        "metrics": settings.METRICS_ENDPOINT,
        "version_info": "/version"
    }


# Include API routers
app.include_router(auth.router)
app.include_router(tenants.router)
app.include_router(agents.router)
app.include_router(missions.router)
app.include_router(economy.router)
app.include_router(performance.router)
app.include_router(metrics.router)
app.include_router(missions_v45.router)
app.include_router(meta_learning.router)
app.include_router(approval.router)
app.include_router(compliance_reports.router)
app.include_router(registry.router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG
    )
