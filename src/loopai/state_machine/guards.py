"""Agent 循环守卫模块。

提供三个安全网守卫类，保护 agent 循环免受常见故障模式影响：
- BudgetGuard: 步数预算执行，防止失控会话
- LoopDetector: 循环检测，捕获无限工具调用循环
- MessageValidator: 消息验证，防止格式错误的 API 调用
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time as _time
from collections import deque
from datetime import datetime, timezone
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from loopai.context.token_counter import TokenCounter
    from loopai.events.bus import EventBus
    from loopai.tools.types import PermissionLevel as PermissionLevelType


class ValidationError(ValueError):
    """消息验证失败时抛出的异常。

    包含导致验证失败的 tool_call_id，用于调试和错误报告。
    """

    def __init__(self, message: str, tool_call_id: str | None = None) -> None:
        super().__init__(message)
        self.tool_call_id = tool_call_id


class LoopClassification(StrEnum):
    """Loop classification types for the enhanced loop detector (Phase 4)."""

    LOOP_EXACT_SAME = "exact_same"
    LOOP_SAME_TOOL = "same_tool"
    LOOP_STUCK = "stuck"


class LoopDetector:
    """检测重复工具调用的循环检测器。

    使用滑动窗口记录最近 N 次工具调用，通过确定性哈希签名比较
    来识别重复模式。三级升级机制：
    - 允许 (allow): 正常操作
    - 警告 (warn): 连续 3 次相同调用时注入系统警告
    - 阻止 (block): 连续 5 次相同调用时拒绝执行
    - 强制退出 (force_exit): 阻止后模式仍然持续

    Phase 4: check() returns a triple (should_proceed, action, classification).

    Attributes:
        window_size: 滑动窗口大小，默认 20。
        warn_threshold: 警告阈值，默认 3 次。
        block_threshold: 阻止阈值，默认 5 次。
    """

    def __init__(
        self,
        window_size: int = 20,
        warn_threshold: int = 3,
        block_threshold: int = 5,
    ) -> None:
        self._window: deque[tuple[str, str]] = deque(maxlen=window_size)
        self._warn_threshold = warn_threshold
        self._block_threshold = block_threshold
        self._consecutive_count = 0
        self._last_signature: str | None = None

    @staticmethod
    def _signature(tool_name: str, arguments: dict) -> str:
        """为工具调用生成确定性哈希签名。

        使用 sha256 对规范化的 (tool_name, sorted_args_json) 对进行哈希，
        取前 16 个十六进制字符。相同参数始终产生相同签名。

        Args:
            tool_name: 工具名称。
            arguments: 工具参数字典。

        Returns:
            16 字符的十六进制签名字符串。
        """
        args_json = json.dumps(arguments, sort_keys=True, ensure_ascii=True)
        raw = f"{tool_name}:{args_json}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def check(self, tool_name: str, arguments: dict) -> tuple[bool, str, LoopClassification | None]:
        """检查此工具调用是否构成循环。

        Args:
            tool_name: 被调用的工具名称。
            arguments: 工具参数字典。

        Returns:
            (should_proceed, action, classification) 三元组。
            should_proceed 为 True 时允许调用继续，False 时拒绝。
            action 为 "allow"、"warn"、"block" 或 "force_exit" 之一。
            classification 为 LoopClassification 枚举值或 None。
        """
        sig = self._signature(tool_name, arguments)

        if sig == self._last_signature:
            self._consecutive_count += 1
        else:
            self._consecutive_count = 1
            self._last_signature = sig

        self._window.append((tool_name, sig))

        classification = LoopClassification.LOOP_EXACT_SAME if sig == self._last_signature else None

        if self._consecutive_count > self._block_threshold:
            return (False, "force_exit", classification)
        elif self._consecutive_count >= self._block_threshold:
            return (False, "block", classification)
        elif self._consecutive_count >= self._warn_threshold:
            return (True, "warn", classification)
        return (True, "allow", None)

    def reset(self) -> None:
        """重置检测器状态。

        清除滑动窗口、连续计数和最后签名。
        当新的工具调用打破了重复模式时使用。
        """
        self._consecutive_count = 0
        self._last_signature = None
        self._window.clear()


class MessageValidator:
    """验证 OpenAI API 消息列表的结构完整性。

    核心规则：每条包含 tool_calls 的 assistant 消息，必须后跟
    对应数量的 tool-role 消息，每条 tool 消息的 tool_call_id
    必须匹配某个之前声明的 tool_call.id。

    这是严格验证——违规会立即抛出 ValidationError，
    而不是尝试自动修复。
    """

    @staticmethod
    def validate(messages: list[dict]) -> None:
        """验证消息列表结构。

        遍历消息列表，追踪待处理的 tool_call_ids。
        每条 assistant 消息添加新的待处理 ID，每条 tool 消息
        消费对应的待处理 ID。遍历完成后，检查是否有未匹配的 ID。

        Args:
            messages: 要验证的消息字典列表。

        Raises:
            ValidationError: 如果发现孤立的 tool_call 或 tool_result，
                             错误消息中包含具体的 tool_call_id。
        """
        pending_ids: set[str] = set()

        for msg in messages:
            role = msg.get("role", "")

            if role == "assistant":
                tool_calls = msg.get("tool_calls")
                if tool_calls:
                    for tc in tool_calls:
                        tc_id = tc.get("id", "") or tc.get("tool_call_id", "")
                        if tc_id:
                            pending_ids.add(tc_id)

            elif role == "tool":
                tc_id = msg.get("tool_call_id", "")
                if tc_id and tc_id in pending_ids:
                    pending_ids.remove(tc_id)
                else:
                    raise ValidationError(
                        f"Orphan tool result: tool_call_id '{tc_id}' "
                        f"has no matching assistant tool_call",
                        tool_call_id=tc_id,
                    )

        # 检查是否有未匹配的 tool_call
        if pending_ids:
            orphan = next(iter(pending_ids))
            raise ValidationError(
                f"Orphan tool call: tool_call_id '{orphan}' "
                f"has no matching tool result",
                tool_call_id=orphan,
            )


class BudgetGuard:
    """步数预算守卫，防止 Agent 会话失控。

    在 OBSERVE→REASON 转换时运行。
    - 在 80% 预算时注入系统警告消息，提醒 LLM 优先给出结论。
    - 在 100% 预算时注入最终摘要提示，要求 LLM 基于已有信息给出答案。
    - 通过 check_unreachable() 方法检测连续失败，发出不可达信号。

    Attributes:
        max_steps: 最大步骤预算，默认 15。
        warn_pct: 警告阈值百分比，默认 0.80 (80%)。
    """

    def __init__(self, max_steps: int = 15, warn_pct: float = 0.80) -> None:
        self.max_steps = max_steps
        self.warn_threshold = int(max_steps * warn_pct)
        self._consecutive_failures = 0

    def check(
        self, step_count: int, messages: list[dict]
    ) -> tuple[bool, list[dict], str | None]:
        """根据当前步数检查预算状态。

        注入的系统消息永远不会修改原始消息 —— 总是返回一个副本。

        Args:
            step_count: 当前步数。
            messages: 当前消息列表。

        Returns:
            (should_continue, modified_messages, action) 元组。
            - should_continue: 始终为 True（预算耗尽时仍给一次最终回答机会）。
            - modified_messages: 消息列表副本，可能附加了系统消息。
            - action: None（正常）、"warn"（预算警告）或 "final"（预算耗尽）。
        """
        # 始终返回副本，不修改输入
        msgs = list(messages)

        if step_count >= self.max_steps:
            final_msg = {
                "role": "system",
                "content": (
                    "Your step budget has been exhausted. "
                    "Based on the information you have gathered so far, "
                    "provide your best final answer. Do not call any tools."
                ),
            }
            msgs = msgs + [final_msg]
            return (True, msgs, "final")

        if step_count >= self.warn_threshold:
            pct = int(step_count / self.max_steps * 100)
            remaining = self.max_steps - step_count
            warn_msg = {
                "role": "system",
                "content": (
                    f"Step budget at {pct}%. "
                    f"{remaining} steps remaining. "
                    f"Prioritize reaching a conclusion."
                ),
            }
            msgs = msgs + [warn_msg]
            return (True, msgs, "warn")

        return (True, msgs, None)

    def check_unreachable(self, is_failure: bool) -> str | None:
        """检测目标是否不可达成。

        追踪连续失败次数。当连续失败 >= 3 次时发出 "unreachable" 信号。

        Args:
            is_failure: 当前步骤是否为失败。

        Returns:
            "unreachable" 如果连续失败 >= 3 次，否则 None。
        """
        if is_failure:
            self._consecutive_failures += 1
        else:
            self._consecutive_failures = 0

        if self._consecutive_failures >= 3:
            return "unreachable"
        return None


# ═══════════════════════════════════════════════════════════════════════════
# PermissionGuard — dangerous command confirmation via EventBus (D-08, D-09)
# ═══════════════════════════════════════════════════════════════════════════


class PermissionGuard:
    """Permission guard — checks tool permission level before execution.

    SAFE and MODERATE commands are allowed immediately.  DANGEROUS commands
    trigger a ``confirmation_required`` event on the :class:`EventBus` and
    block until the user responds (via :meth:`respond`) or the confirmation
    timeout expires.

    Decision references:
        D-08: Whitelist/blacklist classification with dangerous escalation
        D-09: Event-driven confirmation pause (EventBus + CLI/frontend consumer)

    Attributes:
        confirmation_timeout: Seconds to wait for user response (default 120 s).

    Example::

        from loopai.events.bus import EventBus
        from loopai.state_machine.guards import PermissionGuard
        from loopai.tools.types import PermissionLevel

        bus = EventBus()
        guard = PermissionGuard(bus, confirmation_timeout=120.0)

        # In the agent loop (async context):
        should_proceed, action = await guard.check(
            tool_name="bash.rm",
            tool_args={"path": "/tmp/file"},
            permission_level=PermissionLevel.DANGEROUS,
            session_id="sess-1",
            step_num=3,
        )

        # In the CLI consumer (sync context):
        guard.respond("sess-1_bash.rm_3", approved=True)
    """

    def __init__(
        self,
        bus: EventBus,
        confirmation_timeout: float = 120.0,
    ) -> None:
        self._bus: EventBus = bus
        self.confirmation_timeout = confirmation_timeout

        #: Map confirmation_id -> asyncio.Event for blocking wait.
        self._pending: dict[str, asyncio.Event] = {}

        #: Map confirmation_id -> bool (user's approve/deny decision).
        self._results: dict[str, bool] = {}

    # ── Public API ──────────────────────────────────────────────────────

    async def check(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        permission_level: PermissionLevelType,
        session_id: str,
        step_num: int,
    ) -> tuple[bool, str]:
        """Check whether this tool call should proceed.

        Args:
            tool_name: The tool's registered name (e.g. ``"bash.rm"``).
            tool_args: The tool's argument dict.
            permission_level: Pre-classified :class:`PermissionLevel`.
            session_id: The current agent session identifier.
            step_num: The current agent step number.

        Returns:
            A ``(should_proceed, action)`` tuple:
                - ``(True, "allow")`` — SAFE or MODERATE, or DANGEROUS with user approval.
                - ``(False, "confirm_required")`` — DANGEROUS, event published, awaiting response.
                - ``(False, "user_denied")`` — User explicitly denied the operation.
                - ``(False, "timeout")`` — No response received within timeout.
        """
        from loopai.tools.types import PermissionLevel

        # SAFE and MODERATE commands pass through immediately.
        if permission_level in (PermissionLevel.SAFE, PermissionLevel.MODERATE):
            return (True, "allow")

        # DANGEROUS — require user confirmation.
        confirmation_id = f"{session_id}_{tool_name}_{step_num}"

        # Publish confirmation_required event for CLI/frontend consumers.
        await self._bus.publish(
            "confirmation_required",
            {
                "event_type": "confirmation_required",
                "session_id": session_id,
                "step_num": step_num,
                "confirmation_id": confirmation_id,
                "tool_name": tool_name,
                "tool_args": tool_args,
                "permission_level": permission_level.value,
                "reason": f"危险命令 {tool_name} 需要用户确认",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

        # Create a blocking event and wait for respond() or timeout.
        event = asyncio.Event()
        self._pending[confirmation_id] = event

        try:
            await asyncio.wait_for(
                event.wait(), timeout=self.confirmation_timeout
            )
        except asyncio.TimeoutError:
            # Clean up and publish timeout event.
            self._pending.pop(confirmation_id, None)
            self._results.pop(confirmation_id, None)

            await self._bus.publish(
                "confirmation_timeout",
                {
                    "event_type": "confirmation_timeout",
                    "session_id": session_id,
                    "step_num": step_num,
                    "confirmation_id": confirmation_id,
                    "tool_name": tool_name,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )
            return (False, "timeout")

        # Retrieve and clean up the user's decision.
        approved = self._results.pop(confirmation_id, False)
        self._pending.pop(confirmation_id, None)

        # Publish the response event for audit trail.
        await self._bus.publish(
            "confirmation_response",
            {
                "event_type": "confirmation_response",
                "session_id": session_id,
                "step_num": step_num,
                "confirmation_id": confirmation_id,
                "tool_name": tool_name,
                "approved": approved,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

        if approved:
            return (True, "allow")
        return (False, "user_denied")

    def respond(self, confirmation_id: str, approved: bool) -> None:
        """Respond to a pending confirmation request.

        Called by the CLI consumer (or any external agent) to approve or
        deny a DANGEROUS command.  This is a synchronous method — it stores
        the result and signals the waiting coroutine.

        Args:
            confirmation_id: The confirmation ID from the event payload.
            approved: ``True`` to allow execution, ``False`` to deny.
        """
        self._results[confirmation_id] = approved
        if confirmation_id in self._pending:
            self._pending[confirmation_id].set()


# ═══════════════════════════════════════════════════════════════════════════
# TokenGuard — token-budget guard (D-01, D-03)
# ═══════════════════════════════════════════════════════════════════════════


class TokenGuard:
    """Token budget guard — detects when context usage reaches threshold.

    Checks the current message list against a configurable context-window
    threshold.  Returns a signal that the caller (typically the FSM) can
    use to decide whether to trigger :class:`ContextCompressor`.

    This guard follows the same pattern as :class:`BudgetGuard`:
    ``check()`` returns a status signal without directly modifying the
    message list.

    Decision references:
        D-01: Sliding-window + summary compression at 75 % threshold.
        D-03: tiktoken cl100k_base for approximate counting.

    Args:
        token_counter: A :class:`~loopai.context.token_counter.TokenCounter`
            instance.
        window_size: Token budget for the context window (default 128000).
        threshold: Fraction of *window_size* that triggers a ``"compress"``
            signal (default 0.75).
    """

    def __init__(
        self,
        token_counter: TokenCounter,
        window_size: int = 128000,
        threshold: float = 0.75,
    ) -> None:
        self._counter = token_counter
        self._window_size = window_size
        self._threshold = threshold

    def check(self, messages: list[dict]) -> tuple[str, int, int]:
        """Check whether the message list exceeds the token threshold.

        Args:
            messages: The current message list.

        Returns:
            ``(action, token_count, threshold_tokens)``.
            - ``action``: ``"ok"`` if the token count is below the threshold,
              ``"compress"`` if it meets or exceeds the threshold.
            - ``token_count``: Current token count of the messages.
            - ``threshold_tokens``: The threshold value
              (``window_size * threshold``, rounded).
        """
        token_count = self._counter.count_messages(messages)
        threshold_tokens = int(self._window_size * self._threshold)

        if token_count >= threshold_tokens:
            return ("compress", token_count, threshold_tokens)
        return ("ok", token_count, threshold_tokens)


# ═══════════════════════════════════════════════════════════════════════════
# Phase 4: GuardPipeline + CostGuard + RateLimitGuard (RES-04)
# ═══════════════════════════════════════════════════════════════════════════


class GuardResult:
    """Standardized result from a guard check.

    Attributes:
        action: The guard's recommendation ("ok", "compress", "blocked", "warn").
        guard_name: The name of the guard (e.g. "TokenGuard", "CostGuard").
        detail: Human-readable detail about the guard decision.
    """

    def __init__(self, action: str = "ok", guard_name: str | None = None,
                 detail: str | None = None) -> None:
        self.action = action
        self.guard_name = guard_name
        self.detail = detail


class GuardPipeline:
    """Sequential guard execution pipeline (RES-04).

    Executes each registered guard's ``check()`` method in order.
    The first guard that returns a non-ok action stops the pipeline.

    The pipeline is configured with message-level guards (TokenGuard,
    CostGuard). Tool-level guards (RateLimitGuard) are wired separately
    by the FSM in ``_handle_act``.

    Args:
        guards: Ordered list of guard instances, each with a ``check()`` method.
    """

    def __init__(self, guards: list) -> None:
        self._guards = guards

    def check(self, messages: list[dict]) -> GuardResult:
        """Run each guard's check in sequence.

        Args:
            messages: The current message list to pass to each guard.

        Returns:
            A GuardResult from the first guard that triggers a non-ok action,
            or a default "ok" result if all guards pass.
        """
        for guard in self._guards:
            result = guard.check(messages)
            # Each guard may return GuardResult or a tuple; normalize.
            if isinstance(result, GuardResult):
                if result.action != "ok":
                    return result
            elif isinstance(result, tuple):
                # TokenGuard returns (action, token_count, threshold)
                action = result[0]
                if action != "ok":
                    return GuardResult(
                        action=action,
                        guard_name=type(guard).__name__,
                        detail=f"{type(guard).__name__} returned action={action}",
                    )
            else:
                if result and getattr(result, "action", "ok") != "ok":
                    return GuardResult(
                        action=getattr(result, "action", "blocked"),
                        guard_name=type(guard).__name__,
                    )
        return GuardResult(action="ok")


class CostGuard:
    """Cost-based guard — estimates LLM call cost and blocks if too expensive.

    Estimates token usage from message content length and model pricing.
    Blocks calls that exceed ``max_cost_per_call``.

    Args:
        max_cost_per_call: Maximum cost allowed per LLM call in USD.
        price_per_1k_tokens: Approximate cost per 1000 tokens for the model.
    """

    def __init__(self, max_cost_per_call: float = 0.05,
                 price_per_1k_tokens: float = 0.01) -> None:
        self.max_cost_per_call = max_cost_per_call
        self.price_per_1k_tokens = price_per_1k_tokens

    def check(self, messages: list[dict], token_count: int | None = None,
              model_name: str = "gpt-4o") -> GuardResult:
        """Estimate cost and check against max_cost_per_call.

        Args:
            messages: The message list (used for token estimation if
                      token_count is not provided).
            token_count: Explicit token count, or None to estimate from messages.
            model_name: Model name (for logging only).

        Returns:
            GuardResult with action="blocked" if cost exceeds threshold,
            or action="ok" if within budget.
        """
        if token_count is None:
            # Rough estimate: ~4 chars/token for English text
            total_chars = sum(
                len(str(m.get("content", ""))) for m in messages
            )
            token_count = max(1, total_chars // 4)

        estimated_cost = (token_count / 1000.0) * self.price_per_1k_tokens

        if estimated_cost > self.max_cost_per_call:
            return GuardResult(
                action="blocked",
                guard_name="CostGuard",
                detail=(
                    f"Estimated call cost ${estimated_cost:.4f} exceeds "
                    f"limit ${self.max_cost_per_call:.2f}"
                ),
            )
        return GuardResult(action="ok")


class RateLimitGuard:
    """Rate-limit guard — enforces max calls per time window.

    Prevents the agent from making too many tool calls in a short period.
    Used in ``_handle_act`` to record each tool call and can be checked
    before execution.

    Args:
        max_calls: Maximum number of calls allowed in the window.
        window_seconds: The sliding window duration in seconds.
    """

    def __init__(self, max_calls: int = 10, window_seconds: float = 60.0) -> None:
        self._max_calls = max_calls
        self._window_seconds = window_seconds
        self._call_times: dict[str, list[float]] = {}

    def check(self, tool_name: str) -> GuardResult:
        """Check if the rate limit has been exceeded for this tool.

        Args:
            tool_name: The tool being called (currently all tools share one
                       rate limit bucket).

        Returns:
            GuardResult with action="blocked" if rate limited, or "ok".
        """
        now = _time.monotonic()
        key = tool_name if tool_name else "__global__"

        if key not in self._call_times:
            self._call_times[key] = []

        # Prune old entries outside the window
        cutoff = now - self._window_seconds
        self._call_times[key] = [
            t for t in self._call_times[key] if t > cutoff
        ]

        if len(self._call_times[key]) >= self._max_calls:
            return GuardResult(
                action="blocked",
                guard_name="RateLimitGuard",
                detail=(
                    f"Rate limit exceeded: {len(self._call_times[key])} calls "
                    f"in {self._window_seconds}s (max {self._max_calls})"
                ),
            )
        return GuardResult(action="ok")

    def record_call(self, tool_name: str) -> None:
        """Record a tool call in the rate limit window.

        Args:
            tool_name: The tool that was called.
        """
        key = tool_name if tool_name else "__global__"
        if key not in self._call_times:
            self._call_times[key] = []
        self._call_times[key].append(_time.monotonic())
