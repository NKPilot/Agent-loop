"""SSE stream endpoint: GET /api/sessions/{session_id}/stream.

Provides real-time agent event streaming via Server-Sent Events (SSE).
The endpoint connects to the EventBus via the SSE bridge and streams all
events for a given session_id to the browser.

The route handler is an async generator that delegates to the SSE bridge.
Using ``response_class=EventSourceResponse`` triggers FastAPI's built-in
SSE serialization path, which formats yielded ``ServerSentEvent`` objects
into the wire protocol (event:, data:, id:, retry: fields).
"""

from fastapi import APIRouter, Request
from fastapi.sse import EventSourceResponse

from loopai.api.sse_bridge import event_stream

router = APIRouter()


@router.get("/sessions/{session_id}/stream", response_class=EventSourceResponse)
async def stream_session(session_id: str, request: Request):
    """Stream agent events for a session via SSE.

    An async generator that replays historical events then streams new
    events as they are published by the agent loop. FastAPI serializes
    each yielded ``ServerSentEvent`` into SSE wire format.

    Args:
        session_id: The session to stream events for.
        request: FastAPI request object used to access app.state.bus.
    """
    bus = request.app.state.bus
    async for sse_event in event_stream(session_id, bus):
        yield sse_event
