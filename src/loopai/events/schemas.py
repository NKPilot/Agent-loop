"""loopAI 事件总线的事件模式定义。

定义了 ReAct Agent 循环中所有事件类型的 13 个 Pydantic 模型
（1 个基类 + 12 个具体模型）。使用区分联合类型实现类型安全的
反序列化和路由。
"""

from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, Field


class EventBase(BaseModel):
    """所有事件类型共享字段的基础事件模型。"""

    event_type: Literal[str]
    session_id: str
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# ── 顶层生命周期事件 ──────────────────────────────────────────────────


class StepStart(EventBase):
    """每个 Agent 循环步骤开始时发出。"""

    event_type: Literal["step_start"] = "step_start"
    step_num: int


class StepEnd(EventBase):
    """步骤完成时发出，包含状态转换信息。"""

    event_type: Literal["step_end"] = "step_end"
    step_num: int
    state_transition: str
    token_usage: dict | None = None


class SessionEnd(EventBase):
    """Agent 会话终止时发出。"""

    event_type: Literal["session_end"] = "session_end"
    final_state: str
    total_steps: int
    exit_reason: str


# ── 内部流式事件 ──────────────────────────────────────────────────────


class LLMToken(EventBase):
    """LLM 流式输出中每个 token 增量时发出。"""

    event_type: Literal["llm_token"] = "llm_token"
    step_num: int
    content_delta: str


class LLMContentDone(EventBase):
    """LLM 完成某步骤的内容生成时发出。"""

    event_type: Literal["llm_content_done"] = "llm_content_done"
    step_num: int
    full_content: str


class ToolCallStart(EventBase):
    """LLM 发起工具调用时发出。"""

    event_type: Literal["tool_call_start"] = "tool_call_start"
    step_num: int
    tool_name: str
    tool_call_id: str


class ToolCallArgs(EventBase):
    """流式工具参数生成期间每个参数增量时发出。"""

    event_type: Literal["tool_call_args"] = "tool_call_args"
    step_num: int
    tool_name: str
    args_delta: str


class ToolCallDone(EventBase):
    """所有工具参数接收完成时发出。"""

    event_type: Literal["tool_call_done"] = "tool_call_done"
    step_num: int
    tool_name: str
    tool_call_id: str
    full_args: dict


class ToolResult(EventBase):
    """工具执行完成后发出。"""

    event_type: Literal["tool_result"] = "tool_result"
    step_num: int
    tool_name: str
    tool_call_id: str
    result: str
    is_error: bool = False
    duration_ms: float


# ── 守卫事件 ──────────────────────────────────────────────────────────


class BudgetWarning(EventBase):
    """步骤预算达到 80% 阈值时发出。"""

    event_type: Literal["budget_warning"] = "budget_warning"
    step_num: int
    used_pct: float
    max_steps: int


class BudgetExhausted(EventBase):
    """步骤预算完全耗尽时发出。"""

    event_type: Literal["budget_exhausted"] = "budget_exhausted"
    step_num: int


class LoopDetected(EventBase):
    """检测到工具调用循环时发出。"""

    event_type: Literal["loop_detected"] = "loop_detected"
    step_num: int
    tool_name: str
    consecutive_count: int


class Error(EventBase):
    """Agent 执行期间发生错误时发出。"""

    event_type: Literal["error"] = "error"
    step_num: int
    error_type: str
    message: str
    traceback: str | None = None


# ── 确认事件（Phase 2, D-09）───────────────────────────────────────────


class ConfirmationRequired(EventBase):
    """危险命令确认请求——由 PermissionGuard 通过 EventBus 发布。

    决策 D-09：事件驱动的确认暂停。Agent 循环在 ACT 状态中暂停，
    等待用户对 confirmation_required 事件的响应（y/n）。
    CLI 消费者（或 Phase 5 Web 仪表盘）显示命令详情并
    收集用户决定。
    """

    event_type: Literal["confirmation_required"] = "confirmation_required"
    step_num: int
    confirmation_id: str
    tool_name: str
    tool_args: dict
    permission_level: str  # "dangerous"——匹配 PermissionLevel.DANGEROUS.value
    reason: str  # 人类可读（中文）说明，如"命中黑名单命令 rm"


class ConfirmationResponse(EventBase):
    """用户对确认请求的响应——由 CLI 消费者发布。

    PermissionGuard.wait() 协程在此事件发布后解除阻塞。
    ``approved`` 字段携带用户的 y/n 决定。
    """

    event_type: Literal["confirmation_response"] = "confirmation_response"
    step_num: int
    confirmation_id: str
    approved: bool


# ── 上下文管理事件 ────────────────────────────────────────────────────


class ContextCompacted(EventBase):
    """当上下文压缩减少 token 数量时发布。

    压缩引擎在成功压缩后发出此事件，
    记录释放了多少 token 以及多少个对话轮次被摘要。
    """

    event_type: Literal["context_compacted"] = "context_compacted"
    step_num: int
    tokens_before: int
    tokens_after: int
    tokens_saved: int
    rounds_preserved: int
    summary_message_count: int


class TokenWarning(EventBase):
    """当 token 使用量接近上下文窗口限制时发布。

    TokenGuard 在使用量达到可配置阈值（通常为 75%）时发出此事件，
    允许消费者提前预览情况或触发压缩。
    """

    event_type: Literal["token_warning"] = "token_warning"
    step_num: int
    token_count: int
    max_tokens: int
    used_pct: float
    action: str


# ── 弹性事件（Phase 4）────────────────────────────────────────────────


class CheckpointSaved(EventBase):
    """会话状态持久化到检查点文件后发布。"""

    event_type: Literal["checkpoint_saved"] = "checkpoint_saved"
    step_count: int
    state: str  # AgentState.value，如 "reason"、"act"
    file_path: str  # 检查点文件路径


class CircuitOpened(EventBase):
    """工具的熔断器打开时发布。"""

    event_type: Literal["circuit_opened"] = "circuit_opened"
    tool_name: str
    failure_rate: float  # 触发打开的失败率（0.0-1.0）
    window_size: int
    previous_state: str  # 转换前的状态
    new_state: str  # "open"


class CircuitClosed(EventBase):
    """工具的熔断器关闭时发布。"""

    event_type: Literal["circuit_closed"] = "circuit_closed"
    tool_name: str
    previous_state: str
    new_state: str  # "closed"


class FailureRegistered(EventBase):
    """工具失败被记录到 FailureRegistry 时发布。"""

    event_type: Literal["failure_registered"] = "failure_registered"
    tool_name: str
    signature: str  # 确定性哈希（与 LoopDetector._signature 格式相同）
    error_message: str


class EscalationRequired(EventBase):
    """4 层恢复到达人工升级（第 4 层）时发布。"""

    event_type: Literal["escalation_required"] = "escalation_required"
    tool_name: str
    layer: int  # 到达的恢复层级
    attempt_count: int
    error_message: str


# ── 区分联合类型 ──────────────────────────────────────────────────────

Event = Annotated[
    StepStart
    | StepEnd
    | SessionEnd
    | LLMToken
    | LLMContentDone
    | ToolCallStart
    | ToolCallArgs
    | ToolCallDone
    | ToolResult
    | BudgetWarning
    | BudgetExhausted
    | LoopDetected
    | Error
    | ConfirmationRequired
    | ConfirmationResponse
    | ContextCompacted
    | TokenWarning
    | CheckpointSaved
    | CircuitOpened
    | CircuitClosed
    | FailureRegistered
    | EscalationRequired,
    Field(discriminator="event_type"),
]
