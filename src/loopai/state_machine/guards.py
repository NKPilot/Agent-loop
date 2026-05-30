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
import math
import time
from collections import deque
from dataclasses import dataclass
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
    """Classification of detected loop patterns for metacognitive prompting (RES-02).

    LOOP_EXACT_SAME: Same tool called with the same arguments repeatedly.
    LOOP_SAME_TOOL: Same tool called repeatedly but with different arguments.
    LOOP_STUCK: Different tools called but no meaningful progress (heuristic).
    """

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

    def check(
        self, tool_name: str, arguments: dict
    ) -> tuple[bool, str, LoopClassification | None]:
        """检查此工具调用是否构成循环。

        Args:
            tool_name: 被调用的工具名称。
            arguments: 工具参数字典。

        Returns:
            (should_proceed, action, classification) 三元组。
            classification 为 None 表示无循环，否则为循环分类类型。
        """
        sig = self._signature(tool_name, arguments)

        if sig == self._last_signature:
            self._consecutive_count += 1
        else:
            self._consecutive_count = 1
            self._last_signature = sig

        self._window.append((tool_name, sig))

        # Determine classification based on window analysis (always run)
        classification: LoopClassification | None = None
        recent = list(self._window)[-min(5, len(self._window)):]

        if recent and self._consecutive_count >= self._warn_threshold:
            # Primary path: consecutive same-signature calls trigger classification
            if all(t == tool_name and s == sig for t, s in recent):
                classification = LoopClassification.LOOP_EXACT_SAME
            elif all(t == tool_name for t, _ in recent):
                classification = LoopClassification.LOOP_SAME_TOOL
            else:
                classification = LoopClassification.LOOP_STUCK
        elif recent and len(recent) >= self._warn_threshold:
            # Secondary path: window has enough entries but different signatures
            # Analyze pattern without consecutive same-signature requirement
            tools = {t for t, _ in recent}
            if len(tools) == 1:
                # All entries are the same tool (but different args)
                classification = LoopClassification.LOOP_SAME_TOOL
            elif len(tools) >= self._warn_threshold:
                # All different tools — stuck pattern
                classification = LoopClassification.LOOP_STUCK

        if self._consecutive_count > self._block_threshold:
            return (False, "force_exit", classification)
        elif self._consecutive_count >= self._block_threshold:
            return (False, "block", classification)
        elif self._consecutive_count >= self._warn_threshold:
            return (True, "warn", classification)
        return (True, "allow", classification)

    @staticmethod
    def get_meta_prompt(
        tool_name: str,
        classification: LoopClassification | None,
        consecutive_count: int,
    ) -> str:
        """Generate a metacognitive prompt explaining why the loop was detected.

        Args:
            tool_name: The tool being called.
            classification: The loop classification type.
            consecutive_count: Number of consecutive identical calls.

        Returns:
            A Chinese metacognitive prompt string to inject as system message.
        """
        if classification == LoopClassification.LOOP_EXACT_SAME:
            return (
                f"[元认知提示] 你已经连续 {consecutive_count} 次使用完全相同参数调用 "
                f"'{tool_name}'，每次都得到相同结果。继续重复不会改变结果。"
                f"请尝试以下策略之一：\n"
                f"1. 换个思路，使用不同的工具或参数\n"
                f"2. 检查已有信息是否能直接回答问题\n"
                f"3. 如果无法完成，直接告知用户并解释原因"
            )
        elif classification == LoopClassification.LOOP_SAME_TOOL:
            return (
                f"[元认知提示] 你反复使用 '{tool_name}' 工具（{consecutive_count} 次），"
                f"虽然参数不同但未取得实质进展。请考虑：\n"
                f"1. 是否需要换一个工具？\n"
                f"2. 已有信息是否足够回答用户？\n"
                f"3. 尝试不同的方法解决问题"
            )
        elif classification == LoopClassification.LOOP_STUCK:
            return (
                f"[元认知提示] 检测到你可能在执行中卡住了 — "
                f"最近 {consecutive_count} 步你尝试了不同的工具但没有取得进展。"
                f"请暂停并重新评估：\n"
                f"1. 当前目标是什么？\n"
                f"2. 哪些操作真正有助于达成目标？\n"
                f"3. 是否需要向用户请求更多信息？"
            )
        return (
            f"[元认知提示] 检测到重复调用模式（{consecutive_count} 次）。"
            f"请尝试不同的方法或直接给出你的结论。"
        )

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
        *,
        tool_call_id: str = "",
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
        # Include tool_call_id so each tool call gets a unique confirmation
        confirmation_id = f"{session_id}_{tool_name}_{step_num}"
        if tool_call_id:
            confirmation_id += f"_{tool_call_id}"

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
# GuardResult — 守卫管道结果数据类
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class GuardResult:
    """Result of a guard check in the pipeline.

    Attributes:
        action: "ok" (all clear), "compress" (compression needed from TokenGuard),
                "blocked" (guard violation), "warn" (approaching limit).
        guard_name: Name of the guard class that produced this result.
        detail: Human-readable detail message for the blocking guard.
    """

    action: str
    guard_name: str | None = None
    detail: str | None = None


# ═══════════════════════════════════════════════════════════════════════════
# CostGuard — 成本估算守卫
# ═══════════════════════════════════════════════════════════════════════════


class CostGuard:
    """Cost estimation guard — estimates LLM call cost from token count.

    Uses a hardcoded model pricing table. Returns a signal when estimated
    cost exceeds the per-call budget.

    Attributes:
        model_cost_per_1k: Dict mapping model prefix to (input_cost_per_1k, output_cost_per_1k).
        max_cost_per_call: Maximum allowed cost per LLM call in USD (default 0.05).
    """

    _DEFAULT_PRICING: dict[str, tuple[float, float]] = {
        "gpt-4o": (0.0025, 0.01),
        "gpt-4o-mini": (0.00015, 0.0006),
        "gpt-4": (0.03, 0.06),
        "gpt-4-turbo": (0.01, 0.03),
        "gpt-3.5-turbo": (0.0005, 0.0015),
    }

    def __init__(
        self,
        max_cost_per_call: float = 0.05,
        pricing: dict[str, tuple[float, float]] | None = None,
    ) -> None:
        self.max_cost_per_call = max_cost_per_call
        self._pricing = pricing or dict(self._DEFAULT_PRICING)

    def estimate_cost(self, token_count: int, model_name: str = "gpt-4o") -> float:
        """Estimate cost for a single LLM call.

        Uses model prefix matching (e.g., "gpt-4o-2024-08-06" matches "gpt-4o").
        If model not found in pricing table, uses gpt-4o pricing as fallback.

        Returns estimated cost in USD (rounded to 6 decimal places).
        """
        input_cost, output_cost = self._get_rates(model_name)
        # Conservative estimate: assume output is ~30% of total tokens
        input_tokens = int(token_count * 0.7)
        output_tokens = token_count - input_tokens
        cost = (input_tokens / 1000) * input_cost + (output_tokens / 1000) * output_cost
        return round(cost, 6)

    def _get_rates(self, model_name: str) -> tuple[float, float]:
        """Look up pricing rates for a model name with prefix matching."""
        for prefix, rates in self._pricing.items():
            if model_name.startswith(prefix):
                return rates
        return self._pricing.get("gpt-4o", (0.0025, 0.01))

    def check(self, messages: list[dict], token_count: int | None = None,
              model_name: str = "gpt-4o") -> GuardResult:
        """Check if estimated cost is within budget.

        Args:
            messages: Message list (used if token_count not provided — unused in this version).
            token_count: Pre-computed token count. If None, uses len(messages) * 500 as rough estimate.
            model_name: Model name for pricing lookup.

        Returns:
            GuardResult with action="ok" if cost within budget, or "blocked" if over budget.
        """
        if token_count is None:
            token_count = max(len(messages) * 500, 1000)  # Rough estimate fallback

        cost = self.estimate_cost(token_count, model_name)
        if cost > self.max_cost_per_call:
            return GuardResult(
                action="blocked",
                guard_name="CostGuard",
                detail=(
                    f"Estimated cost ${cost:.6f} exceeds limit "
                    f"${self.max_cost_per_call:.4f}"
                ),
            )
        return GuardResult(action="ok", guard_name="CostGuard")


# ═══════════════════════════════════════════════════════════════════════════
# RateLimitGuard — 工具调用频率限制
# ═══════════════════════════════════════════════════════════════════════════


class RateLimitGuard:
    """Rate limit guard — limits tool call frequency within a time window.

    Uses a sliding time window (not sliding count) per tool.
    Tracks call timestamps and blocks if calls exceed the limit within the window.

    Attributes:
        max_calls: Maximum allowed calls within the time window (default 10).
        window_seconds: Time window in seconds (default 60.0).
    """

    def __init__(self, max_calls: int = 10, window_seconds: float = 60.0) -> None:
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        self._call_times: dict[str, list[float]] = {}  # tool_name -> [timestamps]

    def check(self, tool_name: str) -> GuardResult:
        """Check if tool has exceeded its rate limit.

        Args:
            tool_name: The tool to check rate limit for.

        Returns:
            GuardResult with action="ok" if within limit, "blocked" if exceeded.
        """
        now = time.monotonic()
        timestamps = self._call_times.get(tool_name, [])

        # Prune timestamps outside the window
        cutoff = now - self.window_seconds
        active = [t for t in timestamps if t >= cutoff]
        self._call_times[tool_name] = active

        if len(active) >= self.max_calls:
            oldest = active[0] if active else now
            retry_after = round(self.window_seconds - (now - oldest), 1)
            return GuardResult(
                action="blocked",
                guard_name="RateLimitGuard",
                detail=(
                    f"Tool '{tool_name}' rate limit exceeded: "
                    f"{len(active)} calls in {self.window_seconds}s window. "
                    f"Retry after {retry_after}s."
                ),
            )
        return GuardResult(action="ok", guard_name="RateLimitGuard")

    def record_call(self, tool_name: str) -> None:
        """Record a tool call for rate limiting.

        Must be called after the tool executes to update the rate counter.
        """
        if tool_name not in self._call_times:
            self._call_times[tool_name] = []
        self._call_times[tool_name].append(time.monotonic())


# ═══════════════════════════════════════════════════════════════════════════
# GuardPipeline — 顺序守卫管道，短路由机制
# ═══════════════════════════════════════════════════════════════════════════


class GuardPipeline:
    """Sequential guard pipeline with short-circuit on first non-ok result.

    Runs each guard's check() in order. If any guard returns action != "ok",
    the pipeline short-circuits and returns that guard's result immediately.

    Guards are injected as callables. The pipeline normalizes different
    return types: GuardResult objects (CostGuard, RateLimitGuard) and
    tuples (TokenGuard returning (action, count, threshold)).
    """

    def __init__(self, guards: list[Any]) -> None:
        self._guards = guards

    def check(self, messages: list[dict]) -> GuardResult:
        """Run each guard sequentially. Short-circuit on first non-ok result.

        Args:
            messages: The current message list (passed to each guard).

        Returns:
            GuardResult from the first blocking guard, or GuardResult(action="ok")
            if all guards pass.
        """
        for guard in self._guards:
            raw = guard.check(messages)

            # Normalize: handle both GuardResult objects and tuple returns
            if isinstance(raw, GuardResult):
                result = raw
            elif isinstance(raw, tuple):
                action = raw[0]
                name = guard.__class__.__name__
                if action == "ok":
                    result = GuardResult(action="ok", guard_name=name)
                elif action == "compress":
                    result = GuardResult(
                        action="compress",
                        guard_name=name,
                        detail=f"Token count {raw[1]} >= threshold {raw[2]}",
                    )
                else:
                    result = GuardResult(
                        action="blocked",
                        guard_name=name,
                        detail=f"Guard returned action={action}",
                    )
            else:
                result = GuardResult(action="ok", guard_name=guard.__class__.__name__)

            if result.action != "ok":
                return result

        return GuardResult(action="ok")
