"""SSE stream endpoint: GET /api/sessions/{session_id}/stream.

Provides real-time agent event streaming via Server-Sent Events (SSE).
The endpoint connects to the EventBus via the SSE bridge and streams all
events for a given session_id to the browser.
"""

from fastapi import APIRouter, Request
from fastapi.sse import EventSourceResponse

from loopai.api.sse_bridge import event_stream

router = APIRouter()


@router.get("/sessions/{session_id}/stream", response_class=EventSourceResponse)
async def stream_session(session_id: str, request: Request) -> EventSourceResponse:
    """Stream agent events for a session via SSE.

    Opens a persistent SSE connection that replays historical events
    then streams new events as they are published by the agent loop.

    Args:
        session_id: The session to stream events for.
        request: FastAPI request object used to access app.state.bus.

    Returns:
        EventSourceResponse that yields typed ServerSentEvent objects.
    """
    bus = request.app.state.bus
    return EventSourceResponse(event_stream(session_id, bus))
