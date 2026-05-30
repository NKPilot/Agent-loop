"""Agent 控制 REST API 端点：启动和确认。

提供 HTTP 端点，用于从 Web 前端启动 Agent 会话，
以及响应危险命令确认请求。通过 create_agent_components()
工厂函数与 CLI 路径共享组件。

端点：
    POST /api/sessions/start               — 启动新的 Agent 会话
    POST /api/sessions/{session_id}/confirm — 响应确认请求

决策引用：
    D-06: Web 前端的危险确认对话框
    RESEARCH.md Q2: 共享组件工厂，确保 CLI/Web 一致性
    RESEARCH.md Pattern 5: 生命周期管理的 active_sessions 字典
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Request

from loopai.api.schemas import (
    ConfirmRequest,
    SendMessageRequest,
    SendMessageResponse,
    StartSessionRequest,
    StartSessionResponse,
)
from loopai.config import load_config
from loopai.main import create_agent_components
from loopai.session.context import AgentState

logger = logging.getLogger(__name__)

router = APIRouter()


# ── 辅助函数 ─────────────────────────────────────────────────────────────


async def _run_and_cleanup(session, fsm, bus, app):
    """多轮对话运行器。

    循环调用 fsm.run()，每次运行到 FINISH_WAIT 后通过 asyncio.Queue
    等待新消息。收到新消息后添加回 Session 并继续下一轮。
    收到 None 关闭信号或 ERROR 时终止并发布 session_end。
    """
    session_id = session.session_id
    session_end_published = False

    try:
        while True:
            try:
                await fsm.run(session)
            except Exception as exc:
                logger.error(
                    "Agent session %s failed: %s: %s",
                    session_id,
                    type(exc).__name__,
                    exc,
                )
                await bus.publish(
                    "error",
                    {
                        "event_type": "error",
                        "session_id": session_id,
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                        "step_num": session.step_count,
                    },
                )
                await bus.publish(
                    "session_end",
                    {
                        "event_type": "session_end",
                        "session_id": session_id,
                        "final_state": "ERROR",
                        "total_steps": session.step_count,
                        "exit_reason": f"unhandled_error: {type(exc).__name__}",
                    },
                )
                session_end_published = True
                break

            if session.state == AgentState.ERROR:
                # fsm.run() 已发布 session_end
                session_end_published = True
                break

            if session.state == AgentState.FINISH:
                # fsm.run() 已发布 session_end
                session_end_published = True
                break

            if session.state == AgentState.FINISH_WAIT:
                # 等待下一条用户消息
                queue = app.state.session_queues.get(session_id)
                if queue is None:
                    break
                new_message = await queue.get()

                if new_message is None:
                    # 关闭信号——结束会话
                    break

                # 添加用户消息并继续循环
                session.add_message("user", content=new_message)
                session.state = AgentState.REASON

    finally:
        # 仅在 fsm.run() 未发布 session_end 时补发
        if not session_end_published:
            await bus.publish(
                "session_end",
                {
                    "event_type": "session_end",
                    "session_id": session_id,
                    "final_state": session.state.value,
                    "total_steps": session.step_count,
                    "exit_reason": "chat_ended",
                },
            )

        # 清理
        if session_id in app.state.active_sessions:
            entry = app.state.active_sessions[session_id]
            entry["status"] = "completed"
        app.state.session_queues.pop(session_id, None)


# ── 端点 ────────────────────────────────────────────────────────────────


@router.post("/sessions/start")
async def start_session(body: StartSessionRequest, request: Request):
    """从 Web 前端启动新的 Agent 会话。

    通过共享工厂创建 Agent 组件，启动 JSONL 日志记录器，
    并将 FSM 作为后台任务启动。立即返回 session_id，
    以便前端连接 SSE 流。

    会话存储在 app.state.active_sessions 中，用于生命周期
    管理和确认处理。

    速率限制（T-05-06）：v1 阶段接受——单用户本地工具。
    如暴露到网络，需添加 RateLimitGuard（Phase 4）。

    Args:
        body: StartSessionRequest，包含 prompt 和可选的 max_steps。
        request: FastAPI 请求对象，用于访问 app.state。

    Returns:
        带有新 session_id 的 StartSessionResponse。
    """
    config = load_config(None)
    bus = request.app.state.bus

    components = create_agent_components(
        config, body.prompt, bus, max_steps_override=body.max_steps
    )

    session = components["session"]
    fsm = components["fsm"]
    logger_obj = components["logger"]
    permission_guard = components["permission_guard"]

    # 注册会话消息队列（多轮对话用）
    app_state = request.app.state
    app_state.session_queues[session.session_id] = asyncio.Queue()

    # 启动 JSONL 日志记录器（Web 路径下唯一需要的消费者）
    logger_task = await logger_obj.start(bus)

    # 将 FSM 作为后台任务启动——非阻塞，以便立即向前端返回 session_id
    agent_task = asyncio.create_task(
        _run_and_cleanup(session, fsm, bus, request.app)
    )

    # 在活动会话中注册，用于生命周期管理
    app_state.active_sessions[session.session_id] = {
        "session": session,
        "fsm": fsm,
        "task": agent_task,
        "logger_task": logger_task,
        "permission_guard": permission_guard,
        "status": "running",
    }

    return StartSessionResponse(session_id=session.session_id)


@router.post("/sessions/{session_id}/confirm")
async def confirm_session(
    session_id: str,
    body: ConfirmRequest,
    request: Request,
) -> dict:
    """响应待处理的危险命令确认请求。

    在 app.state.active_sessions 中查找会话，获取
    PermissionGuard，并调用 respond() 传入用户的决定。
    PermissionGuard.respond() 是同步方法（设置一个 asyncio.Event
    来解除阻塞的 check() 协程）。

    确认 ID 验证（T-05-08）：检查 confirmation_id 是否存在于
    permission_guard._pending 中，无效 ID 返回 404。

    Args:
        session_id: 要响应的会话。
        body: 包含 confirmation_id 和 approved 标志的 ConfirmRequest。
        request: FastAPI 请求对象，用于访问 app.state。

    Returns:
        包含 confirmation_id、approved 和 responded 键的字典。

    Raises:
        HTTPException 404: 如果会话未找到或 confirmation_id 无效。
    """
    active_sessions: dict = request.app.state.active_sessions

    if session_id not in active_sessions:
        raise HTTPException(
            status_code=404,
            detail=f"Session '{session_id}' not found",
        )

    entry = active_sessions[session_id]
    permission_guard = entry.get("permission_guard")

    if permission_guard is None:
        raise HTTPException(
            status_code=404,
            detail=f"No confirmation guard for session '{session_id}'",
        )

    # 验证 confirmation_id 是否为待处理状态（T-05-08）
    if body.confirmation_id not in permission_guard._pending:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Confirmation '{body.confirmation_id}' not found or "
                f"already responded"
            ),
        )

    # respond() 是同步方法——存储结果并设置 Event
    permission_guard.respond(body.confirmation_id, body.approved)

    return {
        "confirmation_id": body.confirmation_id,
        "approved": body.approved,
        "responded": True,
    }


@router.post("/sessions/{session_id}/messages")
async def send_message(session_id: str, body: SendMessageRequest, request: Request):
    """向活跃会话发送新消息。

    将消息内容放入会话的 asyncio.Queue，FSM 的 _run_and_cleanup
    循环从中取出后处理。同时发布 user_message 事件供 SSE 推送到前端。

    Args:
        session_id: 目标会话 ID。
        body: 包含 content 字段的请求体。
        request: FastAPI 请求对象。

    Returns:
        SendMessageResponse 包含 session_id 和 round_num。
        如果会话未找到或已结束返回 404。
    """
    active = request.app.state.active_sessions
    queues = request.app.state.session_queues

    if session_id not in active:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    entry = active[session_id]
    session = entry["session"]

    # 只允许在 FINISH_WAIT 或初始 REASON 状态下发送消息
    if session.state not in (AgentState.FINISH_WAIT, AgentState.REASON):
        raise HTTPException(
            status_code=409,
            detail=f"Session is in state '{session.state.value}', cannot accept messages",
        )

    if session_id not in queues:
        raise HTTPException(
            status_code=404,
            detail=f"No message queue for session '{session_id}'",
        )

    # 发布 user_message 事件供 SSE 推流
    round_num = getattr(entry.get("fsm"), "_round_num", 0) + 1  # 下一轮的编号
    await request.app.state.bus.publish(
        "user_message",
        {
            "event_type": "user_message",
            "session_id": session_id,
            "round_num": round_num,
            "content": body.content,
        },
    )

    # 放入队列 — _run_and_cleanup 会取出并处理
    await queues[session_id].put(body.content)

    return SendMessageResponse(
        session_id=session_id,
        round_num=round_num,
    )


@router.post("/sessions/{session_id}/stop")
async def stop_session(session_id: str, request: Request):
    """结束一个活跃会话。

    向会话消息队列发送 None 关闭信号，_run_and_cleanup 收到后
    发布 session_end 并清理资源。
    """
    queues = request.app.state.session_queues
    if session_id not in queues:
        raise HTTPException(
            status_code=404, detail=f"Session '{session_id}' not found or already ended"
        )

    await queues[session_id].put(None)

    return {"session_id": session_id, "stopped": True}
