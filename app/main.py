from contextlib import asynccontextmanager


from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger

from .api.auth import verify_jwt
from .api.base import router as base_router
from .api.librechat import router as librechat_router
from .api.container import router as docker_router
from .services.database import db_manager
from .services.cleanup import cleanup_service
from .shared.config import get_settings
from .utils.logging import setup_logging, RequestLoggingMiddleware
from .services.docker_executor import docker_executor


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan events for the FastAPI application."""
    # Setup logging first thing
    setup_logging()
    logger.info("Starting application")

    if get_settings().JWT_PUBLIC_KEY_PEM is None:
        logger.warning("CODEAPI_JWT_PUBLIC_KEY not set — API is UNAUTHENTICATED (dev mode only)")

    # Initialize database
    await db_manager.initialize()

    # Initialize Docker executor
    await docker_executor.initialize()

    # Start cleanup service
    await cleanup_service.start()

    # Verify logging is working
    logger.info("Application initialized successfully")

    yield

    # Cleanup
    logger.info("Shutting down application")
    await cleanup_service.stop()
    await docker_executor.close()
    await db_manager.close()


# Create FastAPI application
app = FastAPI(
    title="Code Interpreter API",
    description="API for executing Python and R code in a sandboxed environment",
    version="1.0.0",
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add logging middleware
app.add_middleware(RequestLoggingMiddleware)

# Include routers (all /v1 routes require a LibreChat JWT when a public key is configured)
app.include_router(base_router, dependencies=[Depends(verify_jwt)])
app.include_router(librechat_router, dependencies=[Depends(verify_jwt)])
app.include_router(docker_router, dependencies=[Depends(verify_jwt)])


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Use the LibreChat error format ({"message": ...}) on /v1/librechat paths."""
    settings = get_settings()
    if request.url.path.startswith(f"{settings.API_PREFIX}/librechat"):
        return JSONResponse(status_code=exc.status_code, content={"message": str(exc.detail)}, headers=exc.headers)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=exc.headers)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok"}
