"""FastAPI application factory for the loopAI observability server.

Provides create_app() which wires up the EventBus, CORS middleware,
API routes, and lifespan management. The app is designed to run
alongside the existing CLI entry point — both share the same
EventBus, Session, and tool infrastructure.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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

    # API routes — stream router is mounted here; sessions and control routers
    # will be added in subsequent plans.
    from loopai.api.routes import control, sessions, stream  # noqa: E402

    app.include_router(stream.router, prefix="/api")
    app.include_router(sessions.router, prefix="/api")
    app.include_router(control.router, prefix="/api")

    return app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(create_app(), host="0.0.0.0", port=8000)
