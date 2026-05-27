"""Tests for the asyncio.Queue EventBus."""

import asyncio
import warnings

import pytest

from loopai.events.bus import EventBus


@pytest.fixture
def event_bus():
    """Return a fresh EventBus instance for each test."""
    return EventBus()


@pytest.mark.asyncio
async def test_publish_subscribe_single_topic(event_bus):
    """Subscriber receives events published to its topic."""
    queue = await event_bus.subscribe("llm_token")
    await event_bus.publish("llm_token", {"event_type": "llm_token", "delta": "Hi"})

    event = await queue.get()
    assert event == {"event_type": "llm_token", "delta": "Hi"}


@pytest.mark.asyncio
async def test_fan_out_multiple_subscribers(event_bus):
    """Multiple subscribers to the same topic all receive the event."""
    q1 = await event_bus.subscribe("step_start")
    q2 = await event_bus.subscribe("step_start")
    await event_bus.publish("step_start", {"event_type": "step_start", "step_num": 1})

    e1 = await q1.get()
    e2 = await q2.get()
    assert e1 == {"event_type": "step_start", "step_num": 1}
    assert e2 == {"event_type": "step_start", "step_num": 1}


@pytest.mark.asyncio
async def test_wildcard_subscription(event_bus):
    """Wildcard '*' subscriber receives events of any topic."""
    wildcard_q = await event_bus.subscribe("*")
    await event_bus.publish("step_start", {"event_type": "step_start", "step_num": 1})

    event = await wildcard_q.get()
    assert event == {"event_type": "step_start", "step_num": 1}

    # Verify no event on explicit topic subscriber that was never subscribed
    step_q = await event_bus.subscribe("step_end")
    await event_bus.publish("step_end", {"event_type": "step_end", "step_num": 1})

    # wildcard also receives this
    wildcard_event = await wildcard_q.get()
    assert wildcard_event["event_type"] == "step_end"
    # step_end subscriber also receives it
    step_event = await step_q.get()
    assert step_event["event_type"] == "step_end"


@pytest.mark.asyncio
async def test_replay_history(event_bus):
    """replay() returns all published events in order."""
    for i in range(3):
        await event_bus.publish("llm_token", {"event_type": "llm_token", "seq": i})

    history = event_bus.replay()
    assert len(history) == 3
    assert [e["seq"] for e in history] == [0, 1, 2]


@pytest.mark.asyncio
async def test_replay_by_topic(event_bus):
    """replay(topic) filters events by event_type."""
    await event_bus.publish("llm_token", {"event_type": "llm_token", "seq": 1})
    await event_bus.publish("step_start", {"event_type": "step_start", "seq": 2})
    await event_bus.publish("llm_token", {"event_type": "llm_token", "seq": 3})

    llm_events = event_bus.replay("llm_token")
    assert len(llm_events) == 2
    assert all(e["event_type"] == "llm_token" for e in llm_events)


@pytest.mark.asyncio
async def test_unsubscribe(event_bus):
    """Unsubscribed queue no longer receives events."""
    q = await event_bus.subscribe("llm_token")
    await event_bus.unsubscribe("llm_token", q)

    await event_bus.publish("llm_token", {"event_type": "llm_token", "seq": 1})

    # Queue should be empty — get() should block
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(q.get(), timeout=0.1)


@pytest.mark.asyncio
async def test_shutdown_sentinel(event_bus):
    """shutdown() sends None to all subscriber queues."""
    q = await event_bus.subscribe("llm_token")
    await event_bus.shutdown()

    sentinel = await q.get()
    assert sentinel is None


@pytest.mark.asyncio
async def test_bounded_queue_backpressure(event_bus):
    """Full queue causes dropped events with warning, not deadlock."""
    # Create a queue with small maxsize and fill it manually
    q = await event_bus.subscribe("test_topic")
    # Override the queue to have maxsize=2 for this test
    small_q: asyncio.Queue = asyncio.Queue(maxsize=2)
    # Replace in subscribers dict
    async with event_bus._lock:
        event_bus._subscribers["test_topic"] = [small_q]

    # Fill the queue (don't consume)
    small_q.put_nowait({"event_type": "test_topic", "seq": 0})
    small_q.put_nowait({"event_type": "test_topic", "seq": 1})
    # Queue is now full

    # Publish should drop with warning, not deadlock
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        await event_bus.publish("test_topic", {"event_type": "test_topic", "seq": 2})
        # Check warning was issued
        assert len(w) == 1
        assert "dropping event" in str(w[0].message).lower() or "dropping" in str(
            w[0].message
        ).lower()


@pytest.mark.asyncio
async def test_invalid_event_data(event_bus):
    """Non-JSON-serializable data raises TypeError."""
    # A set is not JSON-serializable
    with pytest.raises(TypeError, match="JSON-serializable"):
        await event_bus.publish(
            "test_topic", {"event_type": "test_topic", "data": {1, 2, 3}}
        )


@pytest.mark.asyncio
async def test_event_type_mismatch(event_bus):
    """Publishing with mismatched event_type raises ValueError."""
    with pytest.raises(ValueError, match="does not match"):
        await event_bus.publish("step_start", {"event_type": "step_end"})
