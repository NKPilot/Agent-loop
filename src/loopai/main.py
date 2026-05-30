"""loopAI Agent 的 CLI 入口点和会话编排。

提供 run_session() 用于编程式使用，main_cli() 用于命令行接口。
编排完整的 Agent 生命周期：
创建组件 → 运行 FSM → 带哨兵清理的优雅关闭。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import TYPE_CHECKING

from loopai.config import add_cli_args, load_config
from loopai.consumers.cli_renderer import CLIAgentRenderer
from loopai.consumers.jsonl_logger import JSONLLogger
from loopai.context.compressor import ContextCompressor
from loopai.context.token_counter import TokenCounter
from loopai.events.bus import EventBus
from loopai.llm.client import LLMClient
from loopai.resilience.checkpoint import CheckpointManager
from loopai.resilience.circuit_breaker import CircuitBreaker
from loopai.resilience.failure_registry import FailureRegistry
from loopai.session.context import Session
from loopai.state_machine.fsm import ReActFSM
from loopai.state_machine.guards import (
    BudgetGuard,
    CostGuard,
    GuardPipeline,
    LoopDetector,
    MessageValidator,
    PermissionGuard,
    RateLimitGuard,
    TokenGuard,
)
from loopai.tools.bash import create_bash_tool
from loopai.tools.executor import ToolExecutor
from loopai.tools.registry import ToolRegistry

if TYPE_CHECKING:
    from loopai.config import AgentConfig


def create_agent_components(
    config: AgentConfig,
    prompt: str,
    bus: EventBus,
    max_steps_override: int | None = None,
) -> dict:
    """创建所有 Agent 组件但不启动消费者。

    从 run_session() 中提取组件创建逻辑，使其可在 CLI 和 Web
    路径之间共享。Web 路径使用自己的消费者集合（SSE 桥接而非 CLI 渲染器）。

    决策引用：RESEARCH.md Q2——将组件创建提取到可复用的
    工厂函数中，确保 CLI/Web 一致性。

    Args:
        config: 包含 API 密钥、模型和默认设置的 AgentConfig。
        prompt: 用户的问题或指令。
        bus: 现有的 EventBus 实例（可跨会话共享）。
        max_steps_override: 如果提供，覆盖 config.max_steps 用于 BudgetGuard。

    Returns:
        包含以下内容的字典：
        - session: 带有初始 system + user 消息的 Session
        - fsm: 装配了所有守卫和工具的 ReActFSM
        - logger: JSONLLogger（未启动）
        - permission_guard: 用于确认流程的 PermissionGuard
        - registry: 已注册 bash 工具的 ToolRegistry
        - executor: 连接到 registry 的 ToolExecutor
        - checkpoint_manager: 用于恢复的 CheckpointManager
        - failure_registry: 用于错误追踪的 FailureRegistry
        - bus: 传入的 EventBus 实例
    """
    actual_max = max_steps_override if max_steps_override is not None else config.max_steps

    # ── 首先装配工具系统（系统提示需要）─────────────────────────────
    registry = ToolRegistry()
    executor = ToolExecutor(registry)
    permission_guard = PermissionGuard(
        bus, confirmation_timeout=config.confirmation_timeout
    )
    bash_fn = create_bash_tool(working_dir=config.tool_working_dir)
    registry.register(bash_fn)
    from loopai.tools.disk_tools import register_disk_tools
    register_disk_tools(registry, working_dir=config.tool_working_dir)
    from loopai.tools.prompt_builder import build_system_prompt
    system_prompt = build_system_prompt(registry, working_dir=config.tool_working_dir)

    # ── 注册子 Agent（Agent-as-Tool, Phase 6）─────────────────────
    from loopai.agents.disk_agents import disk_analyzer, disk_cleaner
    from loopai.agents.registry import AgentRegistry
    from loopai.agents.tool import AgentTool

    agent_registry = AgentRegistry()
    agent_registry.register(disk_analyzer.__agent_meta__)
    agent_registry.register(disk_cleaner.__agent_meta__)

    # 为每个子 Agent 创建 AgentTool 桥接，注册到主 ToolRegistry
    for meta in agent_registry.list_all():
        agent_tool = AgentTool(agent_meta=meta, config=config, bus=bus)
        registry.register_meta(agent_tool.__tool_meta__)

    # 在系统提示中追加子 Agent 说明
    sub_agent_lines = [
        "",
        "## 可用子 Agent",
        "你可以将子任务委托给以下子 Agent 执行，等待它们完成后继续：",
    ]
    for meta in agent_registry.list_all():
        sub_agent_lines.append(f"- **{meta.name}** — {meta.description}")
    system_prompt += "\n".join(sub_agent_lines)

    # ── 创建带有初始消息的会话 ────────────────────────────────────
    session = Session(config=config)
    session.add_message("system", content=system_prompt)
    session.add_message("user", content=prompt)

    # ── 装配 Agent 组件 ────────────────────────────────────────────
    client = LLMClient(config, bus)
    budget_guard = BudgetGuard(max_steps=actual_max)
    loop_detector = LoopDetector()
    message_validator = MessageValidator()

    # ── 装配上下文管理（Phase 3）───────────────────────────────────
    token_counter = TokenCounter()
    token_guard = TokenGuard(token_counter, window_size=config.context_window)
    compressor = ContextCompressor(token_counter, window_size=config.context_window)

    # ── 装配弹性组件（Phase 4）───────────────────────────────────────
    checkpoint_manager = CheckpointManager(session.session_id)
    circuit_breaker = CircuitBreaker()
    failure_registry = FailureRegistry(session.session_id)
    rate_limit_guard = RateLimitGuard()
    cost_guard = CostGuard()
    guard_pipeline = GuardPipeline([token_guard, cost_guard])

    fsm = ReActFSM(
        client, bus, budget_guard, loop_detector, message_validator,
        registry, executor, permission_guard,
        token_guard=token_guard,
        compressor=compressor,
        guard_pipeline=guard_pipeline,
        checkpoint_manager=checkpoint_manager,
        circuit_breaker=circuit_breaker,
        failure_registry=failure_registry,
        rate_limit_guard=rate_limit_guard,
    )

    # ── 创建日志记录器（未启动——调用方决定何时启动）─────────────
    logger = JSONLLogger(session.session_id)

    return {
        "session": session,
        "fsm": fsm,
        "logger": logger,
        "permission_guard": permission_guard,
        "registry": registry,
        "executor": executor,
        "checkpoint_manager": checkpoint_manager,
        "failure_registry": failure_registry,
        "bus": bus,
    }


async def run_session(
    prompt: str,
    config: AgentConfig,
    max_steps_override: int | None = None,
) -> Session:
    """编排一个完整的 Agent 会话，从创建到优雅关闭。

    生命周期：
    1. 创建 EventBus、带有 system + user 消息的 Session
    2. 装配 LLMClient、守卫、ReActFSM
    3. 启动 JSONLLogger 和 CLIAgentRenderer 消费者
    4. 执行 FSM 循环
    5. 关闭：发送 None 哨兵，清理消费者（5 秒超时），关闭日志记录器

    Args:
        prompt: 用户的问题或指令。
        config: 包含 API 密钥、模型和默认设置的 AgentConfig。
        max_steps_override: 如果提供，覆盖 BudgetGuard 的 config.max_steps。
                            这允许编程式调用者设置自定义预算
                            而无需修改配置对象。

    Returns:
        处于 FINISH 或 ERROR 状态的已完成 Session。
    """
    actual_max = max_steps_override if max_steps_override is not None else config.max_steps

    # ── 通过共享工厂创建核心组件 ────────────────────────────────
    bus = EventBus()
    components = create_agent_components(config, prompt, bus, max_steps_override)
    session = components["session"]
    fsm = components["fsm"]
    logger = components["logger"]
    permission_guard = components["permission_guard"]
    checkpoint_manager = components["checkpoint_manager"]
    failure_registry = components["failure_registry"]

    # ── 启动消费者 ────────────────────────────────────────────────
    renderer = CLIAgentRenderer(bus, permission_guard=permission_guard)

    logger_task = await logger.start(bus)
    renderer_task = asyncio.create_task(renderer.run(max_steps=actual_max))

    # ── 执行 Agent 循环 ──────────────────────────────────────────
    try:
        session = await fsm.run(session)
    except Exception as exc:
        print(f"\n[ERROR] Agent 执行失败: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
    finally:
        # 优雅关闭流程：
        # 1. 向所有订阅者队列发送 None 哨兵
        await bus.shutdown()

        # 2. 等待消费者清理完毕（带超时）
        done, pending = await asyncio.wait(
            [logger_task, renderer_task], timeout=10.0
        )
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

        # 3. 刷新并关闭日志记录器
        await logger.stop()

        # 4. 清理 Phase 4 资源
        await checkpoint_manager.close()
        await failure_registry.close()

    return session


def main_cli() -> None:
    """loopAI Agent 的命令行入口点。

    解析 CLI 参数，加载配置，运行会话。
    通过以下方式调用：python -m loopai.main "Your question here"

    参数：
        prompt          位置参数：用户提示（必需，除非使用 --prompt）
        --prompt        用户提示的命名替代选项
        --max-steps     最大步骤预算（默认：15，来自配置）
        --verbose       启用详细输出（API 密钥绝不打印）
        --api-key       OpenAI API 密钥（覆盖 OPENAI_API_KEY 环境变量）
        --base-url      OpenAI API 基础 URL（覆盖 OPENAI_BASE_URL 环境变量）
        --model         模型名称（覆盖 OPENAI_MODEL 环境变量）
    """
    parser = argparse.ArgumentParser(
        description="loopAI — ReAct Agent CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            '  python -m loopai.main "What is 17 * 23?"\n'
            '  python -m loopai.main "List files" --max-steps 5\n'
            '  python -m loopai.main "Hello" --model gpt-4o-mini'
        ),
    )

    # Prompt：位置参数或 --prompt 标志
    parser.add_argument(
        "prompt",
        nargs="?",
        help="用户提示（位置参数）",
    )
    parser.add_argument(
        "--prompt",
        dest="prompt_opt",
        default=None,
        help="用户提示（命名参数的替代选项）",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="启用详细模式（额外输出，API 密钥绝不打印）",
    )

    # 添加配置相关的 CLI 标志（--api-key、--base-url、--model、--max-steps）
    add_cli_args(parser)

    args = parser.parse_args()

    # 从位置参数或 --prompt 标志中提取 prompt
    prompt = args.prompt or args.prompt_opt
    if not prompt:
        parser.error(
            "A prompt is required.\n"
            "Usage: python -m loopai.main 'Your question here'\n"
            "   or: python -m loopai.main --prompt 'Your question here'"
        )

    # 加载配置（CLI 标志优先于环境变量）
    try:
        config = load_config(args)
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        print(
            "Set OPENAI_API_KEY environment variable or pass --api-key.",
            file=sys.stderr,
        )
        sys.exit(1)

    if args.verbose:
        print(f"Model: {config.model}")
        print(f"Base URL: {config.base_url}")
        print(f"Max steps: {config.max_steps}")
        # API 密钥绝不打印——SecretStr 防止意外暴露

    # 从 CLI 参数提取 max_steps 覆盖值（load_config 已应用，
    # 但传递 None 表示"使用配置值"）
    max_steps_override: int | None = None
    cli_max_steps = getattr(args, "max_steps", None)
    if cli_max_steps is not None:
        max_steps_override = int(cli_max_steps)

    # 运行会话
    try:
        session = asyncio.run(run_session(prompt, config, max_steps_override))
    except KeyboardInterrupt:
        print("\nInterrupted by user.", file=sys.stderr)
        sys.exit(130)

    # 最终状态
    if args.verbose:
        print(f"\nSession {session.session_id}")
        print(f"Final state: {session.state.value}")
        print(f"Total steps: {session.step_count}")


if __name__ == "__main__":
    main_cli()
