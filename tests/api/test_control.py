"""Integration tests for agent control REST endpoints.

Tests start and confirm endpoints. Uses mocks to avoid
actual LLM calls during testing.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from loopai.api.app import create_app
from loopai.events.bus import EventBus
from loopai.state_machine.fsm import AgentState
from loopai.state_machine.guards import PermissionGuard


# ── Helpers ─────────────────────────────────────────────────────────────


class _MockSession:
    """Minimal mock Session for control endpoint tests."""

    def __init__(self, session_id: str = "test-session-id"):
        self.session_id = session_id
        self.state = AgentState.REASON
        self.step_count = 0
        self.messages = []

    def add_message(self, role, content):
        """Mock add_message."""
        self.messages.append({"role": role, "content": content})


class _MockFSM:
    """Mock FSM that immediately finishes (no LLM calls)."""

    async def run(self, session):
        """Simulate FSM execution — transition to FINISH so _run_and_cleanup exits."""
        session.state = AgentState.FINISH
        return session


class _MockLogger:
    """Mock JSONLLogger for control endpoint tests."""

    async def start(self, bus):
        """Return a mock task."""
        return AsyncMock()

    async def stop(self):
        """No-op."""
        pass


def _create_mock_components(config, prompt, bus, max_steps_override=None):
    """Mock implementation of create_agent_components for testing."""
    session = _MockSession()
    return {
        "session": session,
        "fsm": _MockFSM(),
        "logger": _MockLogger(),
        "permission_guard": PermissionGuard(bus),
        "registry": MagicMock(),
        "executor": MagicMock(),
    }


def _init_app_state(app):
    """Initialize app.state the way the lifespan would (needed for tests)."""
    app.state.bus = EventBus()
    app.state.active_sessions = {}
    app.state.session_queues = {}


# ── Test 1: Start session returns session_id (UUID format) ──────────────


def test_start_session_returns_session_id():
    """POST /api/sessions/start returns 200 with a session_id in UUID format."""
    app = create_app()
    _init_app_state(app)
    with patch(
        "loopai.api.routes.control.load_config",
        return_value=MagicMock(
            api_key=MagicMock(get_secret_value=lambda: "sk-test"),
            base_url="https://api.openai.com/v1",
            model="gpt-4o",
            max_steps=1,
            tool_working_dir=".",
            tool_timeout=60.0,
            confirmation_timeout=120.0,
            context_window=128000,
        ),
    ), patch(
        "loopai.api.routes.control.create_agent_components",
        side_effect=_create_mock_components,
    ):
        with TestClient(app) as client:
            response = client.post(
                "/api/sessions/start",
                json={"prompt": "echo hello", "max_steps": 1},
            )

    assert response.status_code == 200
    data = response.json()
    assert "session_id" in data
    # Verify it looks like a UUID (contains hyphens, alphanumeric)
    session_id = data["session_id"]
    assert len(session_id) > 0
    assert "-" in session_id  # UUID format


# ── Test 2: Start session with prompt and max_steps ─────────────────────


def test_start_session_with_prompt_and_max_steps():
    """POST /api/sessions/start agent runs and returns session_id."""
    app = create_app()
    _init_app_state(app)
    with patch(
        "loopai.api.routes.control.load_config",
        return_value=MagicMock(
            api_key=MagicMock(get_secret_value=lambda: "sk-test"),
            base_url="https://api.openai.com/v1",
            model="gpt-4o",
            max_steps=1,
            tool_working_dir=".",
            tool_timeout=60.0,
            confirmation_timeout=120.0,
            context_window=128000,
        ),
    ), patch(
        "loopai.api.routes.control.create_agent_components",
        side_effect=_create_mock_components,
    ):
        with TestClient(app) as client:
            response = client.post(
                "/api/sessions/start",
                json={"prompt": "What is 1+1?", "max_steps": 3},
            )

    assert response.status_code == 200
    data = response.json()
    assert "session_id" in data
    assert data["session_id"] == "test-session-id"


# ── Test 3: Start session missing prompt returns 422 ────────────────────


def test_start_session_missing_prompt():
    """POST /api/sessions/start without prompt returns 422."""
    app = create_app()
    _init_app_state(app)
    with TestClient(app) as client:
        response = client.post(
            "/api/sessions/start",
            json={"max_steps": 3},  # missing "prompt"
        )

    assert response.status_code == 422


# ── Test 4: Confirm approves a confirmation request ─────────────────────


def test_confirm_approve():
    """POST /api/sessions/{id}/confirm with approved=true returns success."""
    app = create_app()
    bus = EventBus()
    guard = PermissionGuard(bus)
    session_id = "test-session-1"
    confirmation_id = f"{session_id}_bash_1"

    # Simulate a pending confirmation (mimics what PermissionGuard.check() does)
    pending_event = asyncio.Event()
    guard._pending[confirmation_id] = pending_event
    guard._results[confirmation_id] = False  # Will be overwritten by respond()

    with TestClient(app) as client:
        # State must be set AFTER lifespan startup runs
        app.state.bus = bus
        app.state.active_sessions[session_id] = {
            "session": _MockSession(session_id),
            "permission_guard": guard,
        }
        app.state.session_queues = {}

        response = client.post(
            f"/api/sessions/{session_id}/confirm",
            json={"confirmation_id": confirmation_id, "approved": True},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["approved"] is True
    assert data["confirmation_id"] == confirmation_id
    # Verify the guard state was updated
    assert guard._results.get(confirmation_id) is True
    assert pending_event.is_set()

    # Cleanup
    guard._pending.pop(confirmation_id, None)
    guard._results.pop(confirmation_id, None)


# ── Test 5: Confirm denies a confirmation request ───────────────────────


def test_confirm_deny():
    """POST /api/sessions/{id}/confirm with approved=false returns success."""
    app = create_app()
    bus = EventBus()
    guard = PermissionGuard(bus)
    session_id = "test-session-2"
    confirmation_id = f"{session_id}_bash_2"

    # Simulate a pending confirmation
    pending_event = asyncio.Event()
    guard._pending[confirmation_id] = pending_event

    with TestClient(app) as client:
        app.state.bus = bus
        app.state.active_sessions[session_id] = {
            "session": _MockSession(session_id),
            "permission_guard": guard,
        }
        app.state.session_queues = {}

        response = client.post(
            f"/api/sessions/{session_id}/confirm",
            json={"confirmation_id": confirmation_id, "approved": False},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["approved"] is False
    assert data["confirmation_id"] == confirmation_id
    assert guard._results.get(confirmation_id) is False
    assert pending_event.is_set()

    # Cleanup
    guard._pending.pop(confirmation_id, None)
    guard._results.pop(confirmation_id, None)


# ── Test 6: Confirm for nonexistent confirmation_id returns 404 ─────────


def test_confirm_nonexistent_session():
    """POST /api/sessions/{id}/confirm for unknown session returns 404."""
    app = create_app()
    _init_app_state(app)
    with TestClient(app) as client:
        response = client.post(
            "/api/sessions/nonexistent-session/confirm",
            json={"confirmation_id": "nonexistent_bash_1", "approved": True},
        )

    assert response.status_code == 404
