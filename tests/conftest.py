"""Shared pytest fixtures for the loopAI test suite."""

from datetime import datetime, timezone

import pytest

from loopai.events.bus import EventBus


def pytest_configure(config):
    """Configure pytest-asyncio mode as a fallback if pyproject.toml is not used."""
    config.option.asyncio_mode = "auto"


# ── Core fixtures ────────────────────────────────────────────────────


@pytest.fixture
def event_bus():
    """Return a fresh EventBus instance for each test function."""
    return EventBus()


@pytest.fixture
def sample_session_id():
    """Return a fixed session ID string for tests."""
    return "test-session-00000000-0000-0000-0000-000000000001"


# ── Sample event dict fixtures ───────────────────────────────────────


@pytest.fixture
def sample_step_start(sample_session_id):
    """Return a StepStart event dict with session_id and step_num=1."""
    return {
        "event_type": "step_start",
        "session_id": sample_session_id,
        "step_num": 1,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@pytest.fixture
def sample_llm_token(sample_session_id):
    """Return a LLMToken event dict."""
    return {
        "event_type": "llm_token",
        "session_id": sample_session_id,
        "step_num": 1,
        "content_delta": "Hello",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@pytest.fixture
def sample_tool_call_start(sample_session_id):
    """Return a ToolCallStart event dict."""
    return {
        "event_type": "tool_call_start",
        "session_id": sample_session_id,
        "step_num": 1,
        "tool_name": "test_tool",
        "tool_call_id": "call_123",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@pytest.fixture
def sample_tool_result(sample_session_id):
    """Return a ToolResult event dict."""
    return {
        "event_type": "tool_result",
        "session_id": sample_session_id,
        "step_num": 1,
        "tool_name": "test_tool",
        "tool_call_id": "call_123",
        "result": "success",
        "is_error": False,
        "duration_ms": 50.0,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
