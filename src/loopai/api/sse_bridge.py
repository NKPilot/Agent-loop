"""SSE 桥接：将 EventBus 事件桥接为 ServerSentEvent 的消费者。

将进程内 EventBus 桥接到 FastAPI 的 EventSourceResponse，
实现 Agent 事件实时推送到浏览器客户端（通过 SSE）。

架构：
  EventBus.subscribe("*") → asyncio.Queue → 按 session_id 过滤
  → ServerSentEvent 产出 → EventSourceResponse → 浏览器 EventSource

关键关注点：
  - 重放：延迟连接的客户端可接收其会话的历史事件
  - 过滤：通过每个事件的 session_id 检查实现跨会话隔离
  - 清理：try/finally 确保客户端断开时取消订阅
  - 背压：事件循环中无阻塞 I/O——仅过滤和产出
"""

from typing import AsyncIterable

from fastapi.sse import ServerSentEvent

from loopai.events.bus import EventBus

# 限制重放到最近的事件，防止内存压力
MAX_REPLAY_EVENTS = 500


async def event_stream(
    session_id: str, bus: EventBus
) -> AsyncIterable[ServerSentEvent]:
    """将 EventBus 事件桥接为特定会话的 SSE 流。

    订阅所有事件（"*" 通配符），重放给定会话的历史事件，
    然后流式传输新到达的事件。
    客户端断开连接时，通过 try/finally 触发清理。

    Args:
        session_id: 要为其流式传输事件的会话 ID。仅产出匹配
                    session_id 的事件。
        bus: 要订阅的 EventBus 实例。

    Yields:
        ServerSentEvent 对象，带有类型化事件字段和 3 秒重试提示。
    """
    queue = await bus.subscribe("*")
    seq_counter = 0

    try:
        # ── REPLAY 阶段：让延迟连接的客户端赶上进度 ──────────
        # 限制为 MAX_REPLAY_EVENTS，防止无界内存增长
        # 按 session_id 过滤，防止跨会话数据泄露（T-05-01）
        history = bus.replay()[-MAX_REPLAY_EVENTS:]
        for event in history:
            if event.get("session_id") == session_id:
                seq_counter += 1
                yield ServerSentEvent(
                    data=event,
                    id=str(seq_counter),
                    retry=3000,
                )

        # ── STREAM 阶段：实时转发新事件 ─────────────────────
        while True:
            event = await queue.get()
            if event is None:  # bus.shutdown() 发送的关闭哨兵
                break
            if event.get("session_id") == session_id:
                seq_counter += 1
                yield ServerSentEvent(
                    data=event,
                    id=str(seq_counter),
                    retry=3000,
                )
    finally:
        # 断开连接或关闭时始终清理订阅
        await bus.unsubscribe("*", queue)
