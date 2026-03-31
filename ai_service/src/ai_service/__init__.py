"""
AI Service for Flood Image Classification.

This package provides a FastAPI-based microservice for classifying images
as flooded or non-flooded using an ONNX model.
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import logging.config

from ai_service.config import AppConfig, LOGGING_CONFIG
from ai_service.api import router as api_router, health_router

__version__ = "0.2.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan for startup and shutdown events."""
    logger = logging.getLogger(__name__)
    logger.info("AI Service starting up...")
    
    # Model is loaded when FloodClassifier is first instantiated in routes
    yield
    
    logger.info("AI Service shutting down...")


def create_app() -> FastAPI:
    """
    FastAPI application factory.
    
    Creates and configures the FastAPI application with all routers
    and error handlers.
    
    Returns:
        FastAPI: Configured FastAPI application instance
    """
    # Configure logging
    logging.config.dictConfig(LOGGING_CONFIG)
    logger = logging.getLogger(__name__)
    
    # Create FastAPI app
    app = FastAPI(
        title="Flood Classification AI Service",
        description="AI service for classifying images as flooded or non-flooded",
        version=__version__,
        lifespan=lifespan
    )
    
    logger.info("Initializing AI Service application")
    logger.info(f"API Version: {AppConfig.API_VERSION}")
    logger.info(f"Debug Mode: {AppConfig.DEBUG}")

    # CORS – allow the frontend to call the AI service directly
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],      # Restrict to your frontend host in production
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include routers
    app.include_router(health_router)
    app.include_router(api_router, prefix=AppConfig.API_PREFIX)

    
    logger.info("Routers registered")
    
    # Error handlers
    @app.exception_handler(404)
    async def not_found_handler(request, exc):
        """Handle 404 errors."""
        return JSONResponse(
            status_code=404,
            content={
                "success": False,
                "error": "Endpoint not found",
                "status_code": 404
            }
        )
    
    @app.exception_handler(500)
    async def internal_error_handler(request, exc):
        """Handle 500 errors."""
        logger.error(f"Internal server error: {exc}")
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": "Internal server error",
                "status_code": 500
            }
        )
    
    # Root route for basic info
    @app.get("/")
    async def index():
        """Root endpoint with service information."""
        return {
            "service": "Flood Classification AI Service",
            "version": __version__,
            "api_version": AppConfig.API_VERSION,
            "endpoints": {
                "health": "/health",
                "predict": f"{AppConfig.API_PREFIX}/predict"
            }
        }
    
    logger.info("Application initialized successfully")
    
    return app


# Create the app instance
app = create_app()


def main():
    """
    Main entry point for running the service.
    
    This function is called when running via the CLI command 'ai-service'.
    """
    import uvicorn
    
    print(f"\n{'='*60}")
    print(f"Flood Classification AI Service")
    print(f"{'='*60}")
    print(f"Server starting on http://{AppConfig.HOST}:{AppConfig.PORT}")
    print(f"API Version: {AppConfig.API_VERSION}")
    print(f"Debug Mode: {AppConfig.DEBUG}")
    print(f"\nEndpoints:")
    print(f"  - Health Check: http://{AppConfig.HOST}:{AppConfig.PORT}/health")
    print(f"  - Prediction:   http://{AppConfig.HOST}:{AppConfig.PORT}{AppConfig.API_PREFIX}/predict")
    print(f"{'='*60}\n")
    
    uvicorn.run(
        "ai_service:app",
        host=AppConfig.HOST,
        port=AppConfig.PORT,
        reload=AppConfig.DEBUG
    )


if __name__ == "__main__":
    main()
