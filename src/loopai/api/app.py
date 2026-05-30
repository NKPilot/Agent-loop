"""FastAPI application factory for the loopAI observability server.

Provides create_app() which wires up the EventBus, CORS middleware,
API routes, and lifespan management. The app is designed to run
alongside the existing CLI entry point — both share the same
EventBus, Session, and tool infrastructure.
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from loopai.events.bus import EventBus


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: create EventBus and session registry.
    Shutdown: drain all subscribers gracefully.
    """
    app.state.bus = EventBus()
    app.state.active_sessions: dict = {}
    yield
    await app.state.bus.shutdown()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Returns:
        A fully configured FastAPI app with CORS, lifespan, and routes.
    """
    app = FastAPI(title="loopAI API", lifespan=lifespan)

    # CORS for Vite dev server and local development
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://localhost:8000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # API routes — stream, sessions, and control routers
    from loopai.api.routes import control, sessions, stream  # noqa: E402

    app.include_router(stream.router, prefix="/api")
    app.include_router(sessions.router, prefix="/api")
    app.include_router(control.router, prefix="/api")

    # StaticFiles: serve frontend production build (SPA fallback via html=True).
    # Must be mounted AFTER API routes so /api/* paths take priority.
    # Only mounts if frontend/dist exists (no-op during development).
    frontend_dist = os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "frontend", "dist"
    )
    frontend_dist = os.path.abspath(frontend_dist)
    if os.path.isdir(frontend_dist):
        app.mount(
            "/",
            StaticFiles(directory=frontend_dist, html=True),
            name="frontend",
        )

    return app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(create_app(), host="0.0.0.0", port=8000)
