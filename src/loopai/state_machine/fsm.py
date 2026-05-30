"""ReActFSM：集成守卫的 ReAct 循环状态机。

驱动 Agent 通过 D-02 中定义的 REASON → ACT → OBSERVE 循环。
在指定的干预点集成 BudgetGuard、LoopDetector、MessageValidator 以及
（Phase 2）ToolRegistry、ToolExecutor 和 PermissionGuard。
发布 StepStart/StepEnd/SessionEnd 事件用于可观测性。
"""

from __future__ import annotations

import json as _json
import traceback
from typing import TYPE_CHECKING, Any

from loopai.session.context import AgentState
from loopai.state_machine.guards import ValidationError

if TYPE_CHECKING:
    from loopai.context.compressor import ContextCompressor
    from loopai.events.bus import EventBus
    from loopai.llm.client import LLMClient
    from loopai.resilience.checkpoint import CheckpointManager
    from loopai.resilience.circuit_breaker import CircuitBreaker, CircuitState
    from loopai.resilience.failure_registry import FailureRegistry
    from loopai.session.context import Session
    from loopai.state_machine.guards import (
        BudgetGuard,
        GuardPipeline,
        LoopDetector,
        MessageValidator,
        PermissionGuard,
        RateLimitGuard,
        TokenGuard,
    )
    from loopai.tools.executor import ToolExecutor
    from loopai.tools.registry import ToolRegistry


class ReActFSM:
    """驱动 Agent 循环的 ReAct 有限状态机。

    集成 LLMClient 用于推理、守卫用于安全、EventBus 用于可观测性。
    主循环的每次迭代根据当前 AgentState 分发到相应处理程序。

    Phase 2 新增：ToolRegistry 用于工具查找、ToolExecutor 用于
    实际工具执行、PermissionGuard 用于危险命令确认。

    Attributes:
        client: 用于流式 API 调用的 LLMClient。
        bus: 用于发布可观测性事件的 EventBus。
        budget_guard: 用于步骤预算执行的 BudgetGuard。
        loop_detector: 用于工具调用循环检测的 LoopDetector。
        message_validator: 用于消息结构验证的 MessageValidator。
        registry: 用于工具元数据查找和模式导出的 ToolRegistry。
        executor: 用于实际工具执行的 ToolExecutor。
        permission_guard: 用于危险命令确认的 PermissionGuard。
    """

    def __init__(
        self,
        client: LLMClient,
        bus: EventBus,
        budget_guard: BudgetGuard,
        loop_detector: LoopDetector,
        message_validator: MessageValidator,
        registry: ToolRegistry,
        executor: ToolExecutor,
        permission_guard: PermissionGuard,
        *,
        # 第 3 阶段
        token_guard: TokenGuard | None = None,
        compressor: ContextCompressor | None = None,
        # Phase 4（新增）
        guard_pipeline: GuardPipeline | None = None,
        checkpoint_manager: CheckpointManager | None = None,
        circuit_breaker: CircuitBreaker | None = None,
        failure_registry: FailureRegistry | None = None,
        rate_limit_guard: RateLimitGuard | None = None,
    ) -> None:
        self.client = client
        self.bus = bus
        self.budget_guard = budget_guard
        self.loop_detector = loop_detector
        self.message_validator = message_validator
        self.registry = registry
        self.executor = executor
        self.permission_guard = permission_guard
        self.token_guard = token_guard
        self.compressor = compressor
        self.guard_pipeline = guard_pipeline
        self.checkpoint_manager = checkpoint_manager
        self.circuit_breaker = circuit_breaker
        self.failure_registry = failure_registry
        self.rate_limit_guard = rate_limit_guard
        self._exit_reason = "completed"
        self._last_act_failed = False

        # 跟踪第 2 层恢复（上下文内重试）
        self._layer2_retry_count: dict[str, int] = {}  # tool_call_id -> 尝试次数
        self._layer2_max_attempts = 2

    async def run(self, session: Session) -> Session:
        """执行 ReAct 循环直到 FINISH 或 ERROR 状态。

        主循环根据 session.state 分发到 _handle_reason、
        _handle_act 或 _handle_observe。总是在返回前
        发布 SessionEnd。

        Args:
            session: 带有初始消息和 state=REASON 的 Session 对象。

        Returns:
            相同的 Session 对象，现在处于 FINISH 或 ERROR 状态。
        """
        while session.state not in (AgentState.FINISH, AgentState.ERROR):
            prev_state = session.state
            if session.state == AgentState.REASON:
                await self._handle_reason(session)
            elif session.state == AgentState.ACT:
                await self._handle_act(session)
            elif session.state == AgentState.OBSERVE:
                await self._handle_observe(session)
            else:
                session.state = AgentState.ERROR
                self._exit_reason = "unknown_state"

            # 每次状态转换后创建检查点（RES-01）
            if self.checkpoint_manager is not None:
                self.checkpoint_manager.save(session)

        # 返回前始终发布 SessionEnd
        await self.bus.publish(
            "session_end",
            {
                "event_type": "session_end",
                "session_id": session.session_id,
                "final_state": session.state.value,
                "total_steps": session.step_count,
                "exit_reason": self._exit_reason,
            },
        )

        return session

    # ── 状态处理程序 ──────────────────────────────────────────────────

    async def _handle_reason(self, session: Session) -> None:
        """处理 REASON 状态：验证消息、检查预算、调用 LLM。

        转换：
        - 有内容 + 无 tool_calls → FINISH（D-01）
        - 有 tool_calls → ACT
        - ValidationError → ERROR
        - Exception → ERROR
        - 预算"final"操作 → LLM 响应后转 FINISH
        """
        step_num = session.step_count + 1

        await self.bus.publish(
            "step_start",
            {
                "event_type": "step_start",
                "session_id": session.session_id,
                "step_num": step_num,
            },
        )

        transition = "REASON_to_FINISH"
        step_token_usage = None

        try:
            # 守卫：LLM 调用前验证消息结构
            self.message_validator.validate(session.messages)

            # Phase 4：GuardPipeline——顺序守卫检查（RES-04）
            if self.guard_pipeline is not None:
                pipeline_result = self.guard_pipeline.check(session.messages)
                if pipeline_result.action == "blocked":
                    # 将会话中注入守卫违规反馈
                    session.add_message(
                        "system",
                        content=(
                            f"[{pipeline_result.guard_name}] {pipeline_result.detail}. "
                            "请调整策略后重试。"
                        ),
                    )
                    # 发布守卫违规事件
                    await self.bus.publish(
                        "guard_violation",
                        {
                            "event_type": "guard_violation",
                            "session_id": session.session_id,
                            "step_num": step_num,
                            "guard_name": pipeline_result.guard_name or "",
                            "detail": pipeline_result.detail or "",
                        },
                    )
                    # 保持 REASON 状态，但注入的系统消息约束了 LLM
                elif pipeline_result.action == "compress" and self.compressor is not None:
                    pass  # TokenGuard 将在 Phase 3 代码块中触发压缩

            # TokenGuard：LLM 调用前检查 token 预算（Phase 3）
            if self.token_guard is not None:
                tg_action, token_count, threshold_tokens = self.token_guard.check(session.messages)
                if tg_action == "compress" and self.compressor is not None:

                    async def _summary_fn(old_msgs: list[dict]) -> str:
                        summary_prompt = self.compressor._build_summary_prompt(old_msgs)
                        summary_response = await self.client.complete(
                            [{"role": "system", "content": summary_prompt}],
                            tools=None,
                            session_id=session.session_id,
                            step_num=step_num,
                        )
                        return summary_response.get("content", "")

                    compressed, was_compressed, meta = await self.compressor.check_and_compress(
                        session.messages, _summary_fn
                    )
                    if was_compressed:
                        # 用压缩版本替换会话消息（通过引用进行追加式替换）
                        session.messages.clear()
                        session.messages.extend(compressed)

                        # 发布 context_compacted 事件
                        await self.bus.publish(
                            "context_compacted",
                            {
                                "event_type": "context_compacted",
                                "session_id": session.session_id,
                                "step_num": step_num,
                                "tokens_before": meta["tokens_before"],
                                "tokens_after": meta["tokens_after"],
                                "tokens_saved": meta["tokens_saved"],
                                "rounds_preserved": meta.get("rounds_preserved", 0),
                                "summary_message_count": meta.get("summary_message_count", 0),
                            },
                        )

            # 守卫：预算检查（可能注入系统消息）
            should_continue, messages, action = self.budget_guard.check(
                session.step_count, session.messages
            )

            # 在 LLM 调用前增加步骤计数（确保 SessionEnd 正确报告）
            session.increment_step()

            # LLM 调用，传入（可能已被修改的）消息和已注册的工具
            # Phase 4：熔断器过滤——从 LLM 模式中排除 OPEN 状态工具
            open_tools: set[str] | None = None
            if self.circuit_breaker is not None:
                open_tools = self.circuit_breaker.get_open_tools()
            tool_schemas = self.registry.get_schemas(exclude_open=open_tools) if self.registry else None
            response = await self.client.complete(
                messages,
                tools=tool_schemas,
                session_id=session.session_id,
                step_num=step_num,
            )

            content = response.get("content", "")
            tool_calls: list[dict[str, Any]] = response.get("tool_calls", []) or []
            step_token_usage = response.get("token_usage")  # 从 LLM 流中捕获

            # 构建 assistant 消息
            add_kwargs: dict[str, Any] = {"role": "assistant"}
            if content:
                add_kwargs["content"] = content
            if tool_calls:
                add_kwargs["tool_calls"] = tool_calls
            reasoning = response.get("reasoning_content")
            if reasoning:
                add_kwargs["reasoning_content"] = reasoning
            session.messages.append(add_kwargs)

            # 确定下一个状态
            if action == "final":
                # 预算耗尽：允许这次最终响应，然后强制 FINISH
                session.state = AgentState.FINISH
                transition = "REASON_to_FINISH"
                self._exit_reason = "budget_exhausted"
                await self.bus.publish(
                    "budget_exhausted",
                    {
                        "event_type": "budget_exhausted",
                        "session_id": session.session_id,
                        "step_num": step_num,
                    },
                )
            elif tool_calls:
                session.state = AgentState.ACT
                transition = "REASON_to_ACT"
            else:
                session.state = AgentState.FINISH
                transition = "REASON_to_FINISH"

            # 处理预算警告
            if action == "warn":
                await self.bus.publish(
                    "budget_warning",
                    {
                        "event_type": "budget_warning",
                        "session_id": session.session_id,
                        "step_num": step_num,
                        "used_pct": (session.step_count / self.budget_guard.max_steps) * 100,
                        "max_steps": self.budget_guard.max_steps,
                    },
                )

        except ValidationError:
            session.state = AgentState.ERROR
            transition = "REASON_to_ERROR"
            self._exit_reason = "validation_error"
        except Exception:
            session.state = AgentState.ERROR
            transition = "REASON_to_ERROR"
            self._exit_reason = "error"

        # 发布 StepEnd，附带 LLM 响应的 token 使用量
        await self.bus.publish(
            "step_end",
            {
                "event_type": "step_end",
                "session_id": session.session_id,
                "step_num": step_num,
                "state_transition": transition,
                "token_usage": step_token_usage,
            },
        )

    async def _handle_act(self, session: Session) -> None:
        """处理 ACT 状态：循环检测、权限检查、执行工具。

        Phase 2 实现——用完整的工具管道替换 Phase 1 的综合桩：
        1. LoopGuard 检查（检测无限循环）
        2. Registry 查找（查找工具元数据）
        3. PermissionGuard 检查（确认危险命令）
        4. ToolExecutor.execute()（运行工具）
        5. 发布 tool_result 事件 + 将结果注入会话

        转换：
        - 工具处理完成 → OBSERVE
        - LoopDetector 的 force_exit → FINISH
        """
        tool_calls_data = session.messages[-1].get("tool_calls", [])
        step_num = session.step_count
        any_blocked = False

        for tc in tool_calls_data:
            func = tc.get("function", {})
            tool_name = func.get("name", tc.get("name", "unknown"))
            tool_call_id = tc.get("id", "") or tc.get("tool_call_id", "")

            # 解析参数：function.arguments 按 OpenAI 规范是 JSON 字符串
            raw_args = func.get("arguments", tc.get("arguments", {}))
            if isinstance(raw_args, str):
                try:
                    raw_args = _json.loads(raw_args)
                except _json.JSONDecodeError:
                    raw_args = {}

            # 守卫：循环检测（Phase 4——增强的 3 元组返回）
            should_proceed, loop_action, _loop_class = self.loop_detector.check(
                tool_name, raw_args
            )

            # 发布 loop_detected 警告事件
            if loop_action == "warn":
                await self.bus.publish(
                    "loop_detected",
                    {
                        "event_type": "loop_detected",
                        "session_id": session.session_id,
                        "step_num": step_num,
                        "tool_name": tool_name,
                        "consecutive_count": self.loop_detector._consecutive_count,
                    },
                )

            if not should_proceed:
                if loop_action == "force_exit":
                    session.state = AgentState.FINISH
                    self._exit_reason = "loop_detected"
                    return

                # block：注入系统消息，视为失败
                session.add_message(
                    "tool",
                    content=(
                        f"[SYSTEM] Tool call to '{tool_name}' has been blocked "
                        f"due to repeated identical calls. "
                        f"Please try a different approach or provide your answer directly."
                    ),
                    tool_call_id=tool_call_id,
                )
                any_blocked = True
                continue

            # ── Phase 2：真实工具管道 ──────────────────────────────

            # Phase 4：FailureRegistry 检查（RES-03）
            if self.failure_registry is not None:
                sig = self.loop_detector._signature(
                    tool_name, raw_args if isinstance(raw_args, dict) else {}
                )
                if self.failure_registry.should_skip(tool_name, sig):
                    session.add_message(
                        "tool",
                        content=(
                            f"[SYSTEM] 操作 '{tool_name}(...)' 之前已失败并被注册。"
                            "请尝试不同的方法或参数。"
                        ),
                        tool_call_id=tool_call_id,
                    )
                    any_blocked = True
                    continue

            # Phase 4：CircuitBreaker 检查（RES-06）
            if self.circuit_breaker is not None:
                allowed, cb_state = self.circuit_breaker.check(tool_name)
                if not allowed:
                    session.add_message(
                        "tool",
                        content=(
                            f"[SYSTEM] 工具 '{tool_name}' 当前不可用 "
                            f"(熔断器状态: {cb_state.value})。请尝试其他方法。"
                        ),
                        tool_call_id=tool_call_id,
                    )
                    any_blocked = True
                    continue

            # 第 1 步：在注册表中查找工具
            metadata = self.registry.get(tool_name)
            if metadata is None:
                session.add_message(
                    "tool",
                    content=f"[SYSTEM] 工具 '{tool_name}' 未注册，无法执行。请尝试其他方法。",
                    tool_call_id=tool_call_id,
                )
                any_blocked = True
                continue

            # 第 2 步：权限检查（D-09）
            perm_result, perm_action = await self.permission_guard.check(
                tool_name,
                raw_args,
                metadata.permission_level,
                session.session_id,
                step_num,
                tool_call_id=tool_call_id,
            )

            if not perm_result:
                # 用户拒绝或确认超时
                if perm_action == "user_denied":
                    session.add_message(
                        "tool",
                        content=f"[SYSTEM] 操作被用户拒绝：{tool_name}",
                        tool_call_id=tool_call_id,
                    )
                elif perm_action == "timeout":
                    session.add_message(
                        "tool",
                        content=f"[SYSTEM] 操作确认超时：{tool_name}",
                        tool_call_id=tool_call_id,
                    )
                else:
                    session.add_message(
                        "tool",
                        content=f"[SYSTEM] 操作被阻止：{tool_name}",
                        tool_call_id=tool_call_id,
                    )
                any_blocked = True
                continue

            # 第 3 步：通过 ToolExecutor 执行工具
            result = await self.executor.execute(tool_name, raw_args)

            # Phase 4：CircuitBreaker 记录（RES-06）
            if self.circuit_breaker is not None:
                await self.circuit_breaker.record_with_session(
                    tool_name, success=not result.is_error,
                    session_id=session.session_id, bus=self.bus,
                )

            # Phase 4：FailureRegistry 记录非瞬态错误（RES-03）
            if self.failure_registry is not None and result.is_error:
                sig = self.loop_detector._signature(
                    tool_name, raw_args if isinstance(raw_args, dict) else {}
                )
                self.failure_registry.record(
                    tool_name, sig,
                    result.error_message or "Unknown error",
                )

            # Phase 4：RateLimitGuard 记录（RES-04）
            if self.rate_limit_guard is not None and not result.is_error:
                self.rate_limit_guard.record_call(tool_name)

            # 第 4 步：发布 ToolResult 事件
            await self.bus.publish(
                "tool_result",
                {
                    "event_type": "tool_result",
                    "session_id": session.session_id,
                    "step_num": step_num,
                    "tool_name": tool_name,
                    "tool_call_id": tool_call_id,
                    "result": str(result.data) if result.data else "",
                    "is_error": result.is_error,
                    "duration_ms": result.duration_ms,
                },
            )

            # 第 5 步：将 tool_result 注入会话消息，支持溢出文件（Phase 3, D-05）
            if result.overflow_file and result.data is not None:
                # 计算引用的大小
                data_str = str(result.data)
                size_kb = len(data_str.encode("utf-8")) // 1024
                tool_content = (
                    f"[工具输出已保存至: {result.overflow_file} ({size_kb}KB)]\n"
                    f"如需查看完整内容，请使用 Bash 工具读取该文件。\n"
                    f"--- 预览 (前 500 字符) ---\n"
                    f"{data_str[:500]}"
                )
            else:
                tool_content = (
                    str(result.data) if result.data is not None
                    else (result.error_message or "")
                )
            session.add_message(
                "tool",
                content=tool_content,
                tool_call_id=tool_call_id,
            )

            # 发布 overflow_written 事件
            if result.overflow_file:
                data_str = str(result.data) if result.data else ""
                size_kb = len(data_str.encode("utf-8")) // 1024
                await self.bus.publish(
                    "overflow_written",
                    {
                        "event_type": "overflow_written",
                        "session_id": session.session_id,
                        "step_num": step_num,
                        "tool_name": tool_name,
                        "tool_call_id": tool_call_id,
                        "file_path": result.overflow_file,
                        "size_kb": size_kb,
                    },
                )

            if result.is_error:
                any_blocked = True

        # 追踪是否有工具失败（用于不可达检测）
        self._last_act_failed = any_blocked
        session.state = AgentState.OBSERVE

    async def _handle_observe(self, session: Session) -> None:
        """处理 OBSERVE 状态：增加步数，检查不可达。

        转换：
        - step_count < max 且非不可达 → REASON
        - 检测到不可达（连续 3+ 次失败）→ FINISH
        """
        # 通过 BudgetGuard 检查不可达检测
        unreachable = self.budget_guard.check_unreachable(self._last_act_failed)
        self._last_act_failed = False  # 为下一个循环重置

        if unreachable == "unreachable":
            session.state = AgentState.FINISH
            self._exit_reason = "unreachable"
        else:
            session.state = AgentState.REASON
