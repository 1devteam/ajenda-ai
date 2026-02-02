"""
Omnipath v4.5 - Main Application Entry Point
Multi-agent AI system with emotional intelligence, agent economy, and self-improvement
"""
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging

# Import configuration
from backend.config.settings import Settings

# Import API routes
from backend.api.routes import economy, performance, metrics, missions_v45
# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize settings
settings = Settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager
    Handles startup and shutdown events
    """
    # Startup
    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION}")
    logger.info(f"Environment: {settings.ENVIRONMENT}")
    logger.info(f"Debug mode: {settings.DEBUG}")
    
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
    
    yield
    
    # Shutdown
    logger.info(f"Shutting down {settings.APP_NAME}")


# Initialize FastAPI application
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Multi-agent AI system with emotional intelligence, agent economy, and self-improvement capabilities",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.DEBUG else ["https://yourdomain.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Handle uncaught exceptions gracefully"""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    
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
        "environment": settings.ENVIRONMENT
    }


# Root endpoint
@app.get("/", tags=["system"])
async def root():
    """
    Root endpoint with API information
    """
    return {
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "description": "Multi-agent AI system with emotional intelligence",
        "docs": "/docs",
        "health": "/health",
        "metrics": "/metrics"
    }


# Include API routers
app.include_router(economy.router)
app.include_router(performance.router)
app.include_router(metrics.router)
app.include_router(missions_v45.router)


# Startup message
@app.on_event("startup")
async def startup_message():
    """Log startup completion"""
    logger.info("=" * 60)
    logger.info(f"{settings.APP_NAME} v{settings.APP_VERSION} is ready!")
    logger.info(f"API Documentation: http://localhost:8000/docs")
    logger.info(f"Health Check: http://localhost:8000/health")
    logger.info(f"Metrics: http://localhost:8000/metrics")
    logger.info("=" * 60)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG
    )
