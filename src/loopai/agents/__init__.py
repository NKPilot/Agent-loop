""":mod:`loopai.agents` — Agent-as-Tool 子 Agent 系统。

将子 Agent 封装为可被主 Agent 调用的 Tool（Agent-as-Tool 模式）。
子 Agent 拥有独立 Session 和工具集，完成后结构化回传结果。

公共 API 导出：
    - 类型定义：AgentMetadata、AgentToolResult
    - 装饰器：agent（类似 @tool，定义子 Agent 的 system prompt、工具集、预算）
    - 注册表：AgentRegistry（基于实例的 Agent 查找）
    - 桥接：AgentTool（将子 Agent 桥接为普通 Tool，可被 ToolRegistry 注册）

决策引用:
    D-01: @agent 装饰器——类似 @tool，定义子 Agent 的配置。
    D-02: AgentRegistry 与 ToolRegistry 独立管理。
"""

from loopai.agents.decorator import agent, get_default_registry
from loopai.agents.registry import AgentRegistry
from loopai.agents.tool import AgentTool
from loopai.agents.types import AgentMetadata, AgentToolResult

__all__ = [
    "AgentMetadata",
    "AgentToolResult",
    "agent",
    "AgentRegistry",
    "get_default_registry",
    "AgentTool",
]
