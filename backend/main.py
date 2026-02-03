"""
Omnipath v5.0 - Main Application Entry Point
Multi-agent AI system with observability, meta-learning, and agent economy
"""
from fastapi import FastAPI, Request, status
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
from backend.api.routes import economy, performance, metrics, missions_v45, meta_learning, tenants, agents, missions

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
    telemetry.shutdown()


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


# Metrics endpoint
@app.get(settings.METRICS_ENDPOINT, tags=["system"])
async def get_prometheus_metrics():
    """
    Prometheus metrics endpoint
    Returns metrics in Prometheus format
    """
    return metrics_endpoint()


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
app.include_router(tenants.router)
app.include_router(agents.router)
app.include_router(missions.router)
app.include_router(economy.router)
app.include_router(performance.router)
app.include_router(metrics.router)
app.include_router(missions_v45.router)
app.include_router(meta_learning.router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG
    )
