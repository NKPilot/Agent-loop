"""loopAI FastAPI 服务器的 Pydantic API 响应模型。

定义会话管理、SSE 流式传输和 Agent 控制端点的
请求和响应模式。
"""

from pydantic import BaseModel


class SessionSummary(BaseModel):
    """列表端点的轻量级会话元数据。"""

    id: str
    created_at: str
    step_count: int
    status: str
    exit_reason: str | None = None

    model_config = {"from_attributes": True}


class SessionListResponse(BaseModel):
    """GET /api/sessions 的响应模型。"""

    sessions: list[SessionSummary]


class SessionDetailResponse(BaseModel):
    """GET /api/sessions/{id} 的响应模型。

    session 字典包含完整的会话数据，
    包括 id、事件列表和所有元数据。
    """

    session: dict


class StartSessionRequest(BaseModel):
    """POST /api/sessions/start 的请求体。"""

    prompt: str
    max_steps: int = 15


class StartSessionResponse(BaseModel):
    """POST /api/sessions/start 的响应模型。"""

    session_id: str


class ConfirmRequest(BaseModel):
    """POST /api/sessions/{id}/confirm 的请求体。

    包含确认 ID（由 PermissionGuard 生成）和
    用户的批准/拒绝决定。
    """

    confirmation_id: str
    approved: bool


class DeleteResponse(BaseModel):
    """DELETE /api/sessions/{id} 的响应模型。"""

    deleted: bool


class SendMessageRequest(BaseModel):
    """POST /api/sessions/{id}/messages 的请求体。"""

    content: str


class SendMessageResponse(BaseModel):
    """POST /api/sessions/{id}/messages 的响应。"""

    message: str = "Message queued"
    session_id: str
    round_num: int


__all__ = [
    "SessionSummary",
    "SessionListResponse",
    "SessionDetailResponse",
    "StartSessionRequest",
    "StartSessionResponse",
    "ConfirmRequest",
    "DeleteResponse",
    "SendMessageRequest",
    "SendMessageResponse",
]
