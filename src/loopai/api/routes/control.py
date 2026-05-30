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
    StartSessionRequest,
    StartSessionResponse,
)
from loopai.config import load_config
from loopai.main import create_agent_components

logger = logging.getLogger(__name__)

router = APIRouter()


# ── 辅助函数 ─────────────────────────────────────────────────────────────


async def _run_and_cleanup(session, fsm, bus, app):
    """运行 FSM 循环并在完成时发布 session_end 事件。

    用 try/except 包装 fsm.run() 以优雅地处理错误。
    在 FSM 完成后（或出错后），如果 FSM 尚未发布 session_end
    事件，则发布该事件，并在 active_sessions 中将会话标记为已完成。
    """
    session_id = session.session_id
    try:
        try:
            await fsm.run(session)
        except Exception as exc:
            logger.error(
                "Agent session %s failed: %s: %s",
                session_id,
                type(exc).__name__,
                exc,
            )
            # 发布错误事件，以便 SSE 消费者可以观察到失败
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
            # 发布带错误状态的 session_end
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
    finally:
        # 在 active_sessions 中标记为已完成
        if session_id in app.state.active_sessions:
            entry = app.state.active_sessions[session_id]
            entry["status"] = "error" if session.state.value == "ERROR" else "completed"


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

    # 启动 JSONL 日志记录器（Web 路径下唯一需要的消费者）
    logger_task = await logger_obj.start(bus)

    # 将 FSM 作为后台任务启动——非阻塞，以便立即向前端返回 session_id
    agent_task = asyncio.create_task(
        _run_and_cleanup(session, fsm, bus, request.app)
    )

    # 在活动会话中注册，用于生命周期管理
    request.app.state.active_sessions[session.session_id] = {
        "session": session,
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
