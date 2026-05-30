"""SSE Bridge: EventBus consumer that yields ServerSentEvent objects.

Bridges the in-process EventBus to FastAPI's EventSourceResponse,
enabling real-time agent event streaming to browser clients via SSE.

Architecture:
  EventBus.subscribe("*") → asyncio.Queue → filter by session_id
  → ServerSentEvent yields → EventSourceResponse → browser EventSource

Key concerns:
  - Replay: late-connecting clients receive historical events for their session
  - Filtering: cross-session isolation via session_id check on every event
  - Cleanup: try/finally ensures unsubscribe on client disconnect
  - Backpressure: no blocking I/O in the event loop — just filter and yield
"""

from typing import AsyncIterable

from fastapi.sse import ServerSentEvent

from loopai.events.bus import EventBus

# Limit replay to most recent events to prevent memory pressure
MAX_REPLAY_EVENTS = 500


async def event_stream(
    session_id: str, bus: EventBus
) -> AsyncIterable[ServerSentEvent]:
    """Bridge EventBus events to SSE for a specific session.

    Subscribes to all events ("*" wildcard), replays historical events
    for the given session, then streams new events as they arrive.
    Disconnect (client closes connection) triggers cleanup via try/finally.

    Args:
        session_id: The session to stream events for. Only events with
                    matching session_id are yielded.
        bus: The EventBus instance to subscribe to.

    Yields:
        ServerSentEvent objects with typed event field and 3s retry hint.
    """
    queue = await bus.subscribe("*")
    seq_counter = 0

    try:
        # ── REPLAY phase: catch up late-connecting clients ──────────
        # Limit to MAX_REPLAY_EVENTS to prevent unbounded memory growth
        # Filter by session_id to prevent cross-session data leaks (T-05-01)
        history = bus.replay()[-MAX_REPLAY_EVENTS:]
        for event in history:
            if event.get("session_id") == session_id:
                seq_counter += 1
                yield ServerSentEvent(
                    data=event,
                    id=str(seq_counter),
                    retry=3000,
                )

        # ── STREAM phase: forward new events in real-time ───────────
        while True:
            event = await queue.get()
            if event is None:  # shutdown sentinel from bus.shutdown()
                break
            if event.get("session_id") == session_id:
                seq_counter += 1
                yield ServerSentEvent(
                    data=event,
                    id=str(seq_counter),
                    retry=3000,
                )
    finally:
        # Always clean up subscription on disconnect or shutdown
        await bus.unsubscribe("*", queue)
