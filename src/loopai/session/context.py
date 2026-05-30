"""loopAI Agent 框架的 Session 数据类和 AgentState 枚举。

Session 为 ReAct FSM 提供标准化的状态容器：
- OpenAI 兼容格式的消息数组
- 步骤计数器和工具调用历史
- 通过 REASON/ACT/OBSERVE/FINISH/ERROR 循环的 AgentState 追踪

参见: .planning/phases/01-agent-core-loop/01-CONTEXT.md D-02（五个状态）
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from loopai.config import AgentConfig


class AgentState(str, Enum):
    """D-02 中定义的 ReAct Agent FSM 状态。

    REASON 是入口点。每次循环迭代从 REASON 开始。
    """

    REASON = "reason"
    ACT = "act"
    OBSERVE = "observe"
    FINISH = "finish"
    ERROR = "error"


@dataclass
class Session:
    """ReAct Agent 循环的规范状态容器。

    持有对话历史、步骤计数器、工具调用日志和当前的 AgentState。
    FSM（Plan 05）在每个步骤中读取和写入此对象。

    Attributes:
        session_id: 标识此会话的自动生成 UUID 字符串。
        state: 当前 Agent 状态，默认为 REASON。
        messages: OpenAI 兼容格式的消息字典列表。
        step_count: 已完成的循环迭代次数。
        tool_history: 用于循环检测的 (tool_name, signature) 元组日志。
        created_at: 会话创建的 ISO 8601 时间戳。
        config: 此会话的可选 AgentConfig 引用。
    """

    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    state: AgentState = AgentState.REASON
    messages: list[dict[str, Any]] = field(default_factory=list)
    step_count: int = 0
    tool_history: list[tuple[str, str]] = field(default_factory=list)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    config: AgentConfig | None = None

    def add_message(
        self,
        role: str,
        content: str | None = None,
        *,
        tool_calls: list[dict[str, Any]] | None = None,
        tool_call_id: str | None = None,
        name: str | None = None,
    ) -> dict[str, Any]:
        """向对话历史追加一条消息。

        为给定的 role 构建一个 OpenAI 兼容的消息字典。
        支持所有四种 API 角色：system、user、assistant、tool。

        Args:
            role: "system"、"user"、"assistant"、"tool" 之一。
            content: 消息的文本内容（tool_calls 可为 None）。
            tool_calls: 可选的工具调用字典列表（仅 assistant 角色）。
            tool_call_id: 此消息响应的工具调用 ID（仅 tool 角色）。
            name: 可选的函数名称（仅 tool 角色）。

        Returns:
            追加到 messages 的已构造消息字典。

        Raises:
            ValueError: 如果 role 不是四种有效 API 角色之一。
        """
        valid_roles = {"system", "user", "assistant", "tool"}
        if role not in valid_roles:
            raise ValueError(
                f"Invalid role {role!r}. Must be one of: {', '.join(sorted(valid_roles))}"
            )

        message: dict[str, Any] = {"role": role}

        if content is not None or role not in ("assistant", "tool"):
            message["content"] = content

        if tool_calls is not None:
            message["tool_calls"] = tool_calls

        if tool_call_id is not None:
            message["tool_call_id"] = tool_call_id

        if name is not None:
            message["name"] = name

        self.messages.append(message)
        return message

    def increment_step(self) -> int:
        """将步骤计数器加一。

        Returns:
            递增后的新步骤计数。
        """
        self.step_count += 1
        return self.step_count

    def record_tool_call(self, tool_name: str, signature: str) -> None:
        """在工具历史中记录一次工具调用。

        signature 应该是工具参数的哈希或唯一表示，
        由循环检测器（Plan 02 guards）使用以检测
        重复的完全相同的调用。

        Args:
            tool_name: 被调用工具的名称。
            signature: 用于检测重复调用的唯一参数签名。
        """
        self.tool_history.append((tool_name, signature))
