"""loopAI FastAPI 服务器的 Pydantic API 响应模型。

定义会话管理、SSE 流式传输和 Agent 控制端点的
请求和响应模式。
"""

from typing import Literal

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


# ── 动态工具创建 API Schema（Phase 8）───────────────────────────────────


PersistenceLevel = Literal["session", "sandbox", "project"]
"""动态工具的持久化级别。

- ``session``: 仅当前会话有效，会话结束后释放
- ``sandbox``: 写入沙箱工作目录，同会话复用
- ``project``: 写入项目 tools/ 目录，跨会话持久化
"""


class ConfirmToolCreationRequest(BaseModel):
    """POST /api/sessions/{id}/confirm-tool-creation 的请求体。

    携带用户对动态工具创建的确认决策、持久化级别和额外目录权限。
    """

    confirmation_id: str
    approved: bool
    persistence: PersistenceLevel = "session"
    extra_dirs: list[str] = []


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
    "ConfirmToolCreationRequest",
]
