"""Agent control REST API endpoints: start and confirm.

Provides HTTP endpoints for starting agent sessions from the web
frontend and responding to dangerous command confirmation requests.
Shares the create_agent_components() factory with the CLI path.

Endpoints:
    POST /api/sessions/start              — start a new agent session
    POST /api/sessions/{session_id}/confirm — respond to confirmation request

Decision references:
    D-06: Danger confirmation dialog in web frontend
    RESEARCH.md Q2: Shared component factory for CLI/Web consistency
    RESEARCH.md Pattern 5: lifespan-managed active_sessions dict
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Request

from loopai.api.schemas import (
    ConfirmRequest,
    StartSessionRequest,
    StartSessionResponse,
)
from loopai.config import load_config
from loopai.main import create_agent_components

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Helpers ─────────────────────────────────────────────────────────────


async def _run_and_cleanup(session, fsm, bus, app):
    """Run the FSM loop and publish session_end event on completion.

    Wraps fsm.run() in try/except to handle errors gracefully.
    After the FSM completes (or errors), publishes a session_end
    event if the FSM did not already do so, and marks the session
    as completed in active_sessions.
    """
    session_id = session.session_id
    try:
        try:
            await fsm.run(session)
        except Exception as exc:
            logger.error(
                "Agent session %s failed: %s: %s",
                session_id,
                type(exc).__name__,
                exc,
            )
            # Publish error event so SSE consumers can observe the failure
            await bus.publish(
                "error",
                {
                    "event_type": "error",
                    "session_id": session_id,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "step_num": session.step_count,
                },
            )
            # Publish session_end with error status
            await bus.publish(
                "session_end",
                {
                    "event_type": "session_end",
                    "session_id": session_id,
                    "final_state": "ERROR",
                    "total_steps": session.step_count,
                    "exit_reason": f"unhandled_error: {type(exc).__name__}",
                },
            )
    finally:
        # Mark as completed in active_sessions
        if session_id in app.state.active_sessions:
            entry = app.state.active_sessions[session_id]
            entry["status"] = "error" if session.state.value == "ERROR" else "completed"


# ── Endpoints ────────────────────────────────────────────────────────────


@router.post("/sessions/start")
async def start_session(body: StartSessionRequest, request: Request):
    """Start a new agent session from the web frontend.

    Creates agent components via the shared factory, starts a JSONL logger,
    and launches the FSM as a background task. Returns the session_id
    immediately so the frontend can connect to the SSE stream.

    The session is stored in app.state.active_sessions for lifecycle
    management and confirmation handling.

    Rate limiting (T-05-06): accepted for v1 — single-user local tool.
    If exposed to network, add RateLimitGuard (Phase 4).

    Args:
        body: StartSessionRequest with prompt and optional max_steps.
        request: FastAPI request for accessing app.state.

    Returns:
        StartSessionResponse with the new session_id.
    """
    config = load_config(None)
    bus = request.app.state.bus

    components = create_agent_components(
        config, body.prompt, bus, max_steps_override=body.max_steps
    )

    session = components["session"]
    fsm = components["fsm"]
    logger_obj = components["logger"]
    permission_guard = components["permission_guard"]

    # Start the JSONL logger (only consumer needed for Web path)
    logger_task = await logger_obj.start(bus)

    # Launch FSM as background task — non-blocking so we can return the
    # session_id to the frontend immediately
    agent_task = asyncio.create_task(
        _run_and_cleanup(session, fsm, bus, request.app)
    )

    # Register in active sessions for lifecycle management
    request.app.state.active_sessions[session.session_id] = {
        "session": session,
        "task": agent_task,
        "logger_task": logger_task,
        "permission_guard": permission_guard,
        "status": "running",
    }

    return StartSessionResponse(session_id=session.session_id)


@router.post("/sessions/{session_id}/confirm")
async def confirm_session(
    session_id: str,
    body: ConfirmRequest,
    request: Request,
) -> dict:
    """Respond to a pending dangerous command confirmation request.

    Looks up the session in app.state.active_sessions, retrieves the
    PermissionGuard, and calls respond() with the user's decision.
    The PermissionGuard.respond() is synchronous (sets an asyncio.Event
    that unblocks the waiting check() coroutine).

    Confirmation ID validation (T-05-08): checks that the confirmation_id
    exists in permission_guard._pending before responding. Invalid IDs
    return 404.

    Args:
        session_id: The session to respond to.
        body: ConfirmRequest with confirmation_id and approved flag.
        request: FastAPI request for accessing app.state.

    Returns:
        Dict with confirmation_id, approved, and responded keys.

    Raises:
        HTTPException 404: If session not found or confirmation_id invalid.
    """
    active_sessions: dict = request.app.state.active_sessions

    if session_id not in active_sessions:
        raise HTTPException(
            status_code=404,
            detail=f"Session '{session_id}' not found",
        )

    entry = active_sessions[session_id]
    permission_guard = entry.get("permission_guard")

    if permission_guard is None:
        raise HTTPException(
            status_code=404,
            detail=f"No confirmation guard for session '{session_id}'",
        )

    # Validate that the confirmation_id is pending (T-05-08)
    if body.confirmation_id not in permission_guard._pending:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Confirmation '{body.confirmation_id}' not found or "
                f"already responded"
            ),
        )

    # respond() is synchronous — it stores the result and sets the Event
    permission_guard.respond(body.confirmation_id, body.approved)

    return {
        "confirmation_id": body.confirmation_id,
        "approved": body.approved,
        "responded": True,
    }
