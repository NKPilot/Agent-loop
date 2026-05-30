"""SSE 流端点：GET /api/sessions/{session_id}/stream。

通过 Server-Sent Events (SSE) 提供实时 Agent 事件流。
该端点通过 SSE 桥接连接到 EventBus，
将给定 session_id 的所有事件流式传输到浏览器。

路由处理器是一个异步生成器，委托给 SSE 桥接。
使用 ``response_class=EventSourceResponse`` 触发 FastAPI 内置的
SSE 序列化路径，将产出 ``ServerSentEvent`` 对象
格式化为传输协议（event:、data:、id:、retry: 字段）。
"""

from fastapi import APIRouter, Request
from fastapi.sse import EventSourceResponse

from loopai.api.sse_bridge import event_stream

router = APIRouter()


@router.get("/sessions/{session_id}/stream", response_class=EventSourceResponse)
async def stream_session(session_id: str, request: Request):
    """通过 SSE 流式传输会话的 Agent 事件。

    一个异步生成器，先重放历史事件，
    然后流式传输 Agent 循环发布的新事件。FastAPI 将每个
    产出的 ``ServerSentEvent`` 序列化为 SSE 传输格式。

    Args:
        session_id: 要为其流式传输事件的会话。
        request: FastAPI 请求对象，用于访问 app.state.bus。
    """
    bus = request.app.state.bus
    async for sse_event in event_stream(session_id, bus):
        yield sse_event
