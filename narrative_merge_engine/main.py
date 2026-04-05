"""
Narrative Merge Engine — Main Application Entry Point
Git-inspired testimony reconstruction AI system.
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import ORJSONResponse

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.db.session import db_engine

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Lifespan (startup / shutdown)
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application lifecycle: initialise resources on startup, clean up on shutdown."""
    logger.info("Starting Narrative Merge Engine", env=settings.APP_ENV)

    # Startup: verify DB connectivity
    async with db_engine.begin() as conn:
        await conn.run_sync(lambda c: None)  # ping
    logger.info("Database connection established")

    yield  # Application runs here

    # Shutdown: dispose engine cleanly
    await db_engine.dispose()
    logger.info("Narrative Merge Engine shut down gracefully")


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

def create_application() -> FastAPI:
    configure_logging()

    app = FastAPI(
        title=settings.PROJECT_NAME,
        description=(
            "Production-grade backend for the Narrative Merge Engine — "
            "a Git-inspired AI system for testimony reconstruction, "
            "event extraction, timeline alignment, and conflict detection."
        ),
        version="0.1.0",
        docs_url="/docs" if settings.DEBUG else None,
        redoc_url="/redoc" if settings.DEBUG else None,
        openapi_url="/openapi.json" if settings.DEBUG else None,
        default_response_class=ORJSONResponse,  # faster JSON serialisation
        lifespan=lifespan,
    )

    # ── Middleware (order matters — applied bottom-up) ──────────────────────
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Exception handlers ──────────────────────────────────────────────────
    register_exception_handlers(app)

    # ── Routers ─────────────────────────────────────────────────────────────
    app.include_router(api_router, prefix=settings.API_V1_PREFIX)

    # ── Health check (no auth required) ─────────────────────────────────────
    @app.get("/health", tags=["Health"], summary="Health check")
    async def health() -> dict:
        return {"status": "ok", "service": settings.PROJECT_NAME}

    # ── Frontend Static Files ───────────────────────────────────────────────
    import os
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse

    # Serve static assets
    if os.path.isdir("static"):
        app.mount("/assets", StaticFiles(directory="static/assets"), name="assets")

        # Catch-all route to serve index.html for SPA client-side routing
        @app.get("/{full_path:path}")
        async def serve_frontend(full_path: str):
            # Exclude api and docs routes from falling into this trap
            if full_path.startswith("api/") or full_path in ["docs", "openapi.json", "redoc"]:
                from fastapi import HTTPException
                raise HTTPException(status_code=404, detail="Not found")
            
            file_path = os.path.join("static", full_path)
            if os.path.isfile(file_path):
                return FileResponse(file_path)
            
            return FileResponse("static/index.html")

    return app


app = create_application()


# ---------------------------------------------------------------------------
# Dev runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG,
        log_level="debug" if settings.DEBUG else "info",
    )
