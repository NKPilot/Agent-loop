"""ReActFSM: ReAct loop state machine with guard integration.

Drives the agent through the REASON -> ACT -> OBSERVE cycle defined in D-02.
Integrates BudgetGuard, LoopDetector, MessageValidator, and (Phase 2)
ToolRegistry, ToolExecutor, and PermissionGuard at their specified
intervention points. Publishes StepStart/StepEnd/SessionEnd events for
observability.
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
    from loopai.session.context import Session
    from loopai.state_machine.guards import (
        BudgetGuard,
        LoopDetector,
        MessageValidator,
        PermissionGuard,
        TokenGuard,
    )
    from loopai.tools.executor import ToolExecutor
    from loopai.tools.registry import ToolRegistry


class ReActFSM:
    """ReAct loop finite state machine driving the agent cycle.

    Integrates LLMClient for reasoning, guards for safety, and EventBus
    for observability. Each iteration through the main loop dispatches to
    a handler based on the current AgentState.

    Phase 2 additions: ToolRegistry for tool lookup, ToolExecutor for
    actual tool execution, PermissionGuard for dangerous command confirmation.

    Attributes:
        client: LLMClient for API calls with streaming.
        bus: EventBus for publishing observability events.
        budget_guard: BudgetGuard for step budget enforcement.
        loop_detector: LoopDetector for tool call loop detection.
        message_validator: MessageValidator for message structure validation.
        registry: ToolRegistry for tool metadata lookup and schema export.
        executor: ToolExecutor for actual tool execution.
        permission_guard: PermissionGuard for dangerous command confirmation.
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
        token_guard: TokenGuard | None = None,
        compressor: ContextCompressor | None = None,
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
        self._exit_reason = "completed"
        self._last_act_failed = False

    async def run(self, session: Session) -> Session:
        """Execute the ReAct loop until FINISH or ERROR state.

        The main loop dispatches to _handle_reason, _handle_act, or
        _handle_observe based on session.state. Always publishes
        SessionEnd before returning.

        Args:
            session: The Session object with initial messages and state=REASON.

        Returns:
            The same Session object, now in FINISH or ERROR state.
        """
        while session.state not in (AgentState.FINISH, AgentState.ERROR):
            if session.state == AgentState.REASON:
                await self._handle_reason(session)
            elif session.state == AgentState.ACT:
                await self._handle_act(session)
            elif session.state == AgentState.OBSERVE:
                await self._handle_observe(session)
            else:
                session.state = AgentState.ERROR
                self._exit_reason = "unknown_state"

        # Always publish SessionEnd before returning
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

    # ── State handlers ──────────────────────────────────────────────────

    async def _handle_reason(self, session: Session) -> None:
        """Handle the REASON state: validate messages, check budget, call LLM.

        Transitions:
        - content + no tool_calls -> FINISH (D-01)
        - tool_calls -> ACT
        - ValidationError -> ERROR
        - Exception -> ERROR
        - budget "final" action -> FINISH after LLM response
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

        try:
            # Guard: validate message structure before LLM call
            self.message_validator.validate(session.messages)

            # TokenGuard: check token budget before LLM call (Phase 3)
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
                        # Replace session messages with compressed version (append-only by reference)
                        session.messages.clear()
                        session.messages.extend(compressed)

                        # Publish context_compacted event
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

            # Guard: budget check (may inject system messages)
            should_continue, messages, action = self.budget_guard.check(
                session.step_count, session.messages
            )

            # Increment step count now (before LLM call) so SessionEnd reports correctly
            session.increment_step()

            # LLM call with (possibly modified) messages and registered tools
            tool_schemas = self.registry.get_schemas() if self.registry else None
            response = await self.client.complete(
                messages,
                tools=tool_schemas,
                session_id=session.session_id,
                step_num=step_num,
            )

            content = response.get("content", "")
            tool_calls: list[dict[str, Any]] = response.get("tool_calls", []) or []

            # Build assistant message
            add_kwargs: dict[str, Any] = {"role": "assistant"}
            if content:
                add_kwargs["content"] = content
            if tool_calls:
                add_kwargs["tool_calls"] = tool_calls
            reasoning = response.get("reasoning_content")
            if reasoning:
                add_kwargs["reasoning_content"] = reasoning
            session.messages.append(add_kwargs)

            # Determine next state
            if action == "final":
                # Budget exhausted: allow this final response, then force FINISH
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

            # Handle budget warning
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

        # Publish StepEnd
        await self.bus.publish(
            "step_end",
            {
                "event_type": "step_end",
                "session_id": session.session_id,
                "step_num": step_num,
                "state_transition": transition,
                "token_usage": None,
            },
        )

    async def _handle_act(self, session: Session) -> None:
        """Handle the ACT state: loop-detect, permission-check, execute tools.

        Phase 2 implementation — replaces the Phase 1 synthetic stub with
        a full tool pipeline:
        1. LoopGuard check (detect infinite loops)
        2. Registry lookup (find tool metadata)
        3. PermissionGuard check (confirm dangerous commands)
        4. ToolExecutor.execute() (run the tool)
        5. Publish tool_result event + inject result into session

        Transitions:
        - tool(s) processed -> OBSERVE
        - force_exit from LoopDetector -> FINISH
        """
        tool_calls_data = session.messages[-1].get("tool_calls", [])
        step_num = session.step_count
        any_blocked = False

        for tc in tool_calls_data:
            func = tc.get("function", {})
            tool_name = func.get("name", tc.get("name", "unknown"))
            tool_call_id = tc.get("id", "") or tc.get("tool_call_id", "")

            # Resolve arguments: function.arguments is a JSON string per OpenAI spec
            raw_args = func.get("arguments", tc.get("arguments", {}))
            if isinstance(raw_args, str):
                try:
                    raw_args = _json.loads(raw_args)
                except _json.JSONDecodeError:
                    raw_args = {}

            # Guard: loop detection (Phase 1 — unchanged)
            should_proceed, loop_action = self.loop_detector.check(
                tool_name, raw_args
            )

            # Publish loop_detected warning event
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

                # block: inject system message, treat as failure
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

            # ── Phase 2: Real tool pipeline ──────────────────────────

            # Step 1: Look up tool in registry
            metadata = self.registry.get(tool_name)
            if metadata is None:
                session.add_message(
                    "tool",
                    content=f"[SYSTEM] 工具 '{tool_name}' 未注册，无法执行。请尝试其他方法。",
                    tool_call_id=tool_call_id,
                )
                any_blocked = True
                continue

            # Step 2: Permission check (D-09)
            perm_result, perm_action = await self.permission_guard.check(
                tool_name,
                raw_args,
                metadata.permission_level,
                session.session_id,
                step_num,
            )

            if not perm_result:
                # User denied or confirmation timed out
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

            # Step 3: Execute the tool via ToolExecutor
            result = await self.executor.execute(tool_name, raw_args)

            # Step 4: Publish ToolResult event
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

            # Step 5: Inject tool_result into session messages with overflow support (Phase 3, D-05)
            if result.overflow_file and result.data is not None:
                # Calculate size for the reference
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

            # Publish overflow_written event
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

        # Track whether any tool failed (for unreachable detection)
        self._last_act_failed = any_blocked
        session.state = AgentState.OBSERVE

    async def _handle_observe(self, session: Session) -> None:
        """Handle the OBSERVE state: increment step, check unreachable.

        Transitions:
        - step_count < max and not unreachable -> REASON
        - unreachable detected (3+ consecutive failures) -> FINISH
        """
        # Check unreachable detection via BudgetGuard
        unreachable = self.budget_guard.check_unreachable(self._last_act_failed)
        self._last_act_failed = False  # Reset for next cycle

        if unreachable == "unreachable":
            session.state = AgentState.FINISH
            self._exit_reason = "unreachable"
        else:
            session.state = AgentState.REASON
