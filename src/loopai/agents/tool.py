""":mod:`loopai.agents.tool` — AgentTool 桥接层。

AgentTool 将子 Agent（由 @agent 装饰器定义）封装为普通 Tool，
使其可被主 Agent 的 ToolRegistry 注册和调用。

当主 Agent 调用此 Tool 时，AgentTool 内部启动独立 ReActFSM session，
子 Agent 拥有自己的 EventBus（不污染主 EventBus）、Session（独立消息列表）
和 ToolRegistry（独立工具集）。完成后返回结构化 AgentToolResult 摘要。

决策引用:
    D-01: @agent 装饰器——定义子 Agent 的 system prompt、工具集、预算。
    D-03: 独立工具集——每个子 Agent 有自己独立的 ToolRegistry。
    D-04: 子 Agent 的 Bash 工作目录继承自主 Agent 配置。
    D-05: 结构化摘要——{summary, tool_calls, token_usage, steps, session_id}。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from loopai.agents.types import AgentMetadata, AgentToolResult
from loopai.config import AgentConfig
from loopai.events.bus import EventBus
from loopai.llm.client import LLMClient
from loopai.session.context import AgentState, Session
from loopai.state_machine.fsm import ReActFSM
from loopai.state_machine.guards import (
    BudgetGuard,
    LoopDetector,
    MessageValidator,
    PermissionGuard,
)
from loopai.tools.executor import ToolExecutor
from loopai.tools.registry import ToolRegistry
from loopai.tools.types import PermissionLevel, ToolMetadata


class AgentTool:
    """将子 Agent 桥接为普通 Tool 的适配器。

    通过 __tool_meta__ 属性呈现为 Tool，AgentTool 可被
    ToolRegistry.register_meta() 注册到主 Agent 的工具集。
    当主 Agent LLM 调用此工具时，execute() 内部启动独立
    子 Agent 循环并返回结构化摘要。

    Attributes:
        _agent_meta: 子 Agent 的元数据（名称、描述、系统提示、工具集等）。
        _config: 主 Agent 的配置（API 密钥、模型、基础 URL 等）。
        _bus: 主 Agent 的 EventBus（用于发布事件，可选）。
    """

    def __init__(
        self,
        agent_meta: AgentMetadata,
        config: AgentConfig,
        bus: EventBus | None = None,
    ) -> None:
        """初始化 AgentTool。

        Args:
            agent_meta: @agent 装饰器创建的 AgentMetadata。
            config: AgentConfig 实例（复用主 Agent 的 API 密钥和模型配置）。
            bus: 可选的 EventBus，用于发布子 Agent 执行事件。
        """
        self._agent_meta = agent_meta
        self._config = config
        self._bus = bus

    # ── Tool 接口 ──────────────────────────────────────────────────

    @property
    def __tool_meta__(self) -> ToolMetadata:
        """返回 ToolMetadata，使 AgentTool 表现为普通 Tool。

        返回的 ToolMetadata 包含子 Agent 的名称、描述和参数模式。
        permission_level 设为 SAFE（子 Agent 内部有自己的权限控制）。
        func_ref 指向 self.execute 供 ToolExecutor 调用。
        """
        return ToolMetadata(
            name=self._agent_meta.name,
            description=self._agent_meta.description,
            permission_level=PermissionLevel.SAFE,
            timeout=self._agent_meta.timeout,
            param_schema=self._agent_meta.param_schema,
            validation_model=self._agent_meta.validation_model,
            func_ref=self.execute,
        )

    # ── 执行入口 ───────────────────────────────────────────────────

    async def execute(self, **kwargs: Any) -> str:
        """主 Agent 调用入口——执行子 Agent 并返回结构化摘要。

        主 Agent 的 ToolExecutor 在调用 execute() 前已完成参数验证，
        因此 kwargs 已经是经过验证的参数字典。

        Returns:
            序列化为 JSON 字符串的 AgentToolResult。
        """
        result = await self._run_sub_agent(kwargs)
        return result.model_dump_json()

    # ── 子 Agent 执行 ──────────────────────────────────────────────

    async def _run_sub_agent(self, args: dict[str, Any]) -> AgentToolResult:
        """运行子 Agent 的完整生命周期。

        内部流程（D-01, D-03, D-04）：
        1. 创建独立 EventBus（子 Agent 不污染主 EventBus）
        2. 创建独立 Session，system prompt = agent_meta.system_prompt
        3. 创建独立 ToolRegistry，复用 agent_meta.tool_registry
        4. 创建 ToolExecutor + 必要 guards
        5. 创建 LLMClient（复用主 Agent 的 config）
        6. 创建 ReActFSM 并运行
        7. 收集结果 → 构建 AgentToolResult
        """
        # 1. 创建独立 EventBus
        sub_bus = EventBus()

        # 2. 创建独立 Session
        session = Session(config=self._config)
        session.add_message("system", content=self._agent_meta.system_prompt)

        # 将主 Agent 传入的参数转换为 user 消息
        args_content = json.dumps(args, ensure_ascii=False, indent=2)
        session.add_message("user", content=args_content)

        # 3. 创建 ToolRegistry（复用 agent_meta 中的注册表）
        registry: ToolRegistry
        tool_registry = self._agent_meta.tool_registry
        if tool_registry is not None:
            registry = tool_registry
        else:
            registry = ToolRegistry()

        # 4. 创建 ToolExecutor + 必要 guards
        executor = ToolExecutor(registry)
        permission_guard = PermissionGuard(
            sub_bus, confirmation_timeout=self._config.confirmation_timeout
        )
        budget_guard = BudgetGuard(max_steps=self._agent_meta.max_steps)
        loop_detector = LoopDetector()
        message_validator = MessageValidator()

        # 5. 创建 LLMClient（复用主 Agent 的 config）
        client = LLMClient(self._config, sub_bus)

        # 6. 创建 ReActFSM 并运行
        fsm = ReActFSM(
            client=client,
            bus=sub_bus,
            budget_guard=budget_guard,
            loop_detector=loop_detector,
            message_validator=message_validator,
            registry=registry,
            executor=executor,
            permission_guard=permission_guard,
        )

        # 带超时运行
        try:
            session = await asyncio.wait_for(
                fsm.run(session), timeout=self._agent_meta.timeout
            )
        except asyncio.TimeoutError:
            return AgentToolResult(
                summary=f"子 Agent '{self._agent_meta.name}' 执行超时 "
                        f"（{self._agent_meta.timeout}s）",
                steps=session.step_count,
                session_id=session.session_id,
                success=False,
            )

        # 7. 收集结果 → 构建 AgentToolResult
        return self._extract_summary(session)

    # ── 结果摘要提取 ───────────────────────────────────────────────

    def _extract_summary(self, session: Session) -> AgentToolResult:
        """从已完成的 Session 中提取结构化摘要（D-05）。

        Args:
            session: 执行完毕的 Session 对象。

        Returns:
            包含 summary、tool_calls、token_usage、steps、session_id
            的 AgentToolResult。
        """
        # summary: 取 session.messages 最后一条 assistant 回复
        summary = ""
        for msg in reversed(session.messages):
            if msg.get("role") == "assistant" and msg.get("content"):
                summary = msg["content"]
                break

        # tool_calls: 从 session 消息中提取
        tool_calls: list[dict[str, Any]] = []
        for msg in session.messages:
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    tool_calls.append(tc)

        # token_usage 无法从 Session 直接获取——FSM 会发布 step_end 事件
        # 但不会汇总写入 Session。留空由上层或前端补充。
        token_usage = None

        return AgentToolResult(
            summary=summary,
            tool_calls=tool_calls,
            token_usage=token_usage,
            steps=session.step_count,
            session_id=session.session_id,
            success=session.state != AgentState.ERROR,
        )
