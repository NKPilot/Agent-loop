"""Shared pytest fixtures for API integration tests."""

import pytest

from loopai.events.bus import EventBus


@pytest.fixture
def event_bus():
    """Return a fresh EventBus instance for each API test."""
    return EventBus()


@pytest.fixture
async def sample_events(event_bus):
    """Publish sample events with different session_ids for filter testing.

    Events:
      - sess-1: step_start (step 1)
      - sess-2: step_start (step 1)
      - sess-1: step_end (step 1)
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
