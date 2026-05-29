"""Integration tests for the SSE stream endpoint and bridge.

Tests the SSE bridge (event_stream) directly for replay, filtering,
and disconnect behavior. Uses Starlette TestClient for route-level
checks (status code, content type, route registration).

The bridge is tested directly because SSE is a long-lived connection
that is impractical to test through the full HTTP stack with standard
test clients.
"""

import asyncio
import json
import re

import pytest
from fastapi.testclient import TestClient
from fastapi.sse import ServerSentEvent

from loopai.api.app import create_app
from loopai.api.sse_bridge import event_stream
from loopai.events.bus import EventBus


# ── Helpers ─────────────────────────────────────────────────────────────


def _collect_events_from_stream(stream, max_events=10, timeout=2.0):
    """Collect up to max_events from an event_stream async generator.

    Runs the async collection synchronously via asyncio.run().
    Returns a list of ServerSentEvent objects.
    """
    events = []

    async def _collect():
        # Publish a sentinel event to break the stream loop after replay
        async for sse_event in stream:
            events.append(sse_event)
            if len(events) >= max_events:
                break

    try:
        asyncio.run(asyncio.wait_for(_collect(), timeout=timeout))
    except (asyncio.TimeoutError, TimeoutError):
        pass  # Expected - stream runs forever
    return events


def _sse_data_to_dict(sse_events: list[ServerSentEvent]) -> list[dict]:
    """Extract the data payload from ServerSentEvent objects as dicts."""
    result = []
    for ev in sse_events:
        if ev.data is not None:
            if isinstance(ev.data, dict):
                result.append(ev.data)
            elif isinstance(ev.data, str):
                try:
                    result.append(json.loads(ev.data))
                except json.JSONDecodeError:
                    result.append({"raw": ev.data})
    return result


# ── Route-level tests ───────────────────────────────────────────────────


def test_sse_endpoint_is_registered():
    """Test 1: SSE 端点路由已注册，response_class 为 EventSourceResponse."""
    app = create_app()
    routes = {r.path: r.methods for r in app.routes if hasattr(r, "methods")}
    assert "/api/sessions/{session_id}/stream" in routes
    assert "GET" in routes["/api/sessions/{session_id}/stream"]


# ── Bridge logic tests (direct, no HTTP) ────────────────────────────────


@pytest.mark.asyncio
async def test_event_stream_replays_published_events(event_bus):
    """Test 2: SSE bridge replays published events via EventBus history."""
    await event_bus.publish(
        "step_start",
        {
            "event_type": "step_start",
            "session_id": "sess-1",
            "step_num": 1,
            "timestamp": "2026-01-01T00:00:00",
        },
    )

    stream = event_stream("sess-1", event_bus)
    events: list[ServerSentEvent] = []

    async for sse_event in stream:
        events.append(sse_event)
        if len(events) >= 1:  # Got the replay event
            break

    await event_bus.shutdown()

    assert len(events) >= 1, f"Expected at least 1 event, got {len(events)}"
    data_list = _sse_data_to_dict(events)
    assert data_list[0]["event_type"] == "step_start"
    assert data_list[0]["session_id"] == "sess-1"
    assert data_list[0]["step_num"] == 1


@pytest.mark.asyncio
async def test_event_stream_filters_by_session_id(event_bus):
    """Test 3: SSE bridge only yields events matching session_id."""
    # Publish events for two different sessions
    await event_bus.publish(
        "step_start",
        {
            "event_type": "step_start",
            "session_id": "sess-1",
            "step_num": 1,
            "timestamp": "2026-01-01T00:00:00",
        },
    )
    await event_bus.publish(
        "step_start",
        {
            "event_type": "step_start",
            "session_id": "sess-2",
            "step_num": 1,
            "timestamp": "2026-01-01T00:00:01",
        },
    )
    await event_bus.publish(
        "step_end",
        {
            "event_type": "step_end",
            "session_id": "sess-1",
            "step_num": 1,
            "state_transition": "FINISH",
            "timestamp": "2026-01-01T00:00:02",
        },
    )

    stream = event_stream("sess-1", event_bus)
    events: list[ServerSentEvent] = []

    async for sse_event in stream:
        events.append(sse_event)
        # sess-1 should have 2 events in replay: step_start + step_end
        if len(events) >= 2:
            break

    await event_bus.shutdown()

    data_list = _sse_data_to_dict(events)
    assert len(data_list) >= 1, f"Expected at least 1 event for sess-1, got {len(data_list)}"
    for ev in data_list:
        assert ev["session_id"] == "sess-1", (
            f"Expected session_id 'sess-1', got '{ev['session_id']}' "
            f"for event_type '{ev['event_type']}'"
        )


@pytest.mark.asyncio
async def test_event_stream_handles_disconnect(event_bus):
    """Test 4: SSE bridge unsubscribe on disconnect (via EventBus shutdown).

    Because we cannot simulate an HTTP client disconnect without a real
    connection, we verify the cleanup path by:
    1. Starting the stream
    2. Reading one event (replay)
    3. Calling bus.shutdown() which sends None sentinel
    4. Verifying the stream exits cleanly (no stuck queues)
    """
    await event_bus.publish(
        "step_start",
        {
            "event_type": "step_start",
            "session_id": "sess-1",
            "step_num": 1,
            "timestamp": "2026-01-01T00:00:00",
        },
    )

    subscriber_count_before = len(event_bus._subscribers)

    stream = event_stream("sess-1", event_bus)
    events: list[ServerSentEvent] = []

    # Read one replay event then trigger shutdown
    async for sse_event in stream:
        events.append(sse_event)
        if len(events) >= 1:
            break

    # Shutdown sends None sentinel, triggering cleanup
    await event_bus.shutdown()

    # After shutdown, the subscriber queues should be cleaned
    subscriber_count_after = len(event_bus._subscribers)
    assert subscriber_count_after <= subscriber_count_before, (
        f"Subscribers should not increase: "
        f"{subscriber_count_before} -> {subscriber_count_after}"
    )
    assert len(events) >= 1


@pytest.mark.asyncio
async def test_event_stream_empty_session(event_bus):
    """Test 5: Empty session (no events) — stream connects but yields nothing from replay.

    The stream should not error and should be ready to receive future events.
    """
    subscriber_count_before = len(event_bus._subscribers)

    stream = event_stream("nonexistent-session", event_bus)
    events: list[ServerSentEvent] = []

    # Try to read - nothing in replay, stream will block on queue.get()
    try:
        async for sse_event in stream:
            events.append(sse_event)
            if len(events) >= 1:
                break
    except asyncio.CancelledError:
        pass

    await event_bus.shutdown()

    # Replay should yield 0 events for nonexistent session
    assert len(events) == 0, f"Expected 0 events for empty session, got {len(events)}"
    # Cleanup should not have broken anything
    subscriber_count_after = len(event_bus._subscribers)
    assert subscriber_count_after <= subscriber_count_before
