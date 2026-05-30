"""Agent 系统的核心类型定义。

定义 @agent 装饰器和 AgentRegistry 使用的基础类型。
AgentMetadata 承载子 Agent 的标识、系统提示、工具集和预算配置。
AgentToolResult 封装子 Agent 执行完成后回传给主 Agent 的结构化摘要。

决策引用:
    D-01: @agent 装饰器——类似 @tool，定义子 Agent 的 system prompt、工具集、预算。
    D-02: 子 Agent 通过 AgentRegistry 注册，与 ToolRegistry 独立管理。
    D-05: 结构化摘要——{summary, tool_calls, token_usage, steps, session_id}。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AgentMetadata(BaseModel):
    """子 Agent 的元数据，由 @agent 装饰器创建（D-01）。

    Attributes:
        name: 子 Agent 的唯一标识符。
        description: 子 Agent 能力和用途的描述（供主 Agent LLM 理解）。
        system_prompt: 子 Agent 的系统提示，定义其角色和行为。
        tool_registry: 子 Agent 可用的工具注册表。
        max_steps: 子 Agent 的最大步骤预算。
        timeout: 子 Agent 整体执行超时时间（秒）。
        param_schema: Agent 参数的 JSON Schema（从装饰函数的类型提示生成）。
        validation_model: 用于运行时参数验证的 Pydantic 模型。
    """

    name: str
    description: str
    system_prompt: str
    tool_registry: Any = Field(default=None, exclude=True)
    max_steps: int = 10
    timeout: float = 120.0
    param_schema: dict = Field(default_factory=dict)
    validation_model: Any = Field(default=None, exclude=True)

    model_config = {"arbitrary_types_allowed": True}


class AgentToolResult(BaseModel):
    """子 Agent 执行完成后回传给主 Agent 的结构化摘要（D-05）。

    Attributes:
        summary: 子 Agent 最终回复的文本摘要。
        tool_calls: 子 Agent 执行过程中的工具调用记录列表。
        token_usage: 子 Agent 的总 token 使用量。
        steps: 子 Agent 执行的总步数。
        session_id: 子 Agent 独立 Session 的标识符。
        success: 子 Agent 是否成功完成（非 ERROR 状态）。
    """

    summary: str = ""
    tool_calls: list[dict[str, Any]] = []
    token_usage: dict[str, int] | None = None
    steps: int = 0
    session_id: str = ""
    success: bool = True
