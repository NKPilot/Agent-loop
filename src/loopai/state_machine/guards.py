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
    """检测到的循环模式分类，用于元认知提示（RES-02）。

    LOOP_EXACT_SAME: 同一工具用相同参数反复调用。
    LOOP_SAME_TOOL: 同一工具反复调用但参数不同。
    LOOP_STUCK: 调用了不同工具但无实质进展（启发式）。
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

        # 基于窗口分析确定分类（始终执行）
        classification: LoopClassification | None = None
        recent = list(self._window)[-min(5, len(self._window)):]

        if recent and self._consecutive_count >= self._warn_threshold:
            # 主路径：连续相同签名调用触发分类
            if all(t == tool_name and s == sig for t, s in recent):
                classification = LoopClassification.LOOP_EXACT_SAME
            elif all(t == tool_name for t, _ in recent):
                classification = LoopClassification.LOOP_SAME_TOOL
            else:
                classification = LoopClassification.LOOP_STUCK
        elif recent and len(recent) >= self._warn_threshold:
            # 辅助路径：窗口有足够条目但签名不同
            # 在不要求连续相同签名的情况下分析模式
            tools = {t for t, _ in recent}
            if len(tools) == 1:
                # 所有条目都是同一工具（但参数不同）
                classification = LoopClassification.LOOP_SAME_TOOL
            elif len(tools) >= self._warn_threshold:
                # 全部不同工具——卡住模式
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
        """生成元认知提示，解释为何检测到循环。

        Args:
            tool_name: 被调用的工具。
            classification: 循环分类类型。
            consecutive_count: 连续相同调用的次数。

        Returns:
            作为系统消息注入的中文元认知提示字符串。
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
# PermissionGuard — 通过 EventBus 实现危险命令确认（D-08, D-09）
# ═══════════════════════════════════════════════════════════════════════════


class PermissionGuard:
    """权限守卫——在执行前检查工具权限级别。

    SAFE 和 MODERATE 命令立即放行。DANGEROUS 命令在
    :class:`EventBus` 上触发 ``confirmation_required`` 事件，
    并阻塞直到用户响应（通过 :meth:`respond`）或确认超时到期。

    决策引用:
        D-08: 白名单/黑名单分类搭配危险升级
        D-09: 事件驱动的确认暂停（EventBus + CLI/前端消费者）

    Attributes:
        confirmation_timeout: 等待用户响应的秒数（默认 120 秒）。

    Example::

        from loopai.events.bus import EventBus
        from loopai.state_machine.guards import PermissionGuard
        from loopai.tools.types import PermissionLevel

        bus = EventBus()
        guard = PermissionGuard(bus, confirmation_timeout=120.0)

        # 在 Agent 循环中（异步上下文）：
        should_proceed, action = await guard.check(
            tool_name="bash.rm",
            tool_args={"path": "/tmp/file"},
            permission_level=PermissionLevel.DANGEROUS,
            session_id="sess-1",
            step_num=3,
        )

        # 在 CLI 消费者中（同步上下文）：
        guard.respond("sess-1_bash.rm_3", approved=True)
    """

    def __init__(
        self,
        bus: EventBus,
        confirmation_timeout: float = 120.0,
    ) -> None:
        self._bus: EventBus = bus
        self.confirmation_timeout = confirmation_timeout

        #: Map confirmation_id -> asyncio.Event 用于阻塞等待。
        self._pending: dict[str, asyncio.Event] = {}

        #: Map confirmation_id -> bool（用户的批准/拒绝决定）。
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
        """检查此次工具调用是否应继续执行。

        Args:
            tool_name: 工具注册名称（例如 ``"bash.rm"``）。
            tool_args: 工具参数字典。
            permission_level: 预分类的 :class:`PermissionLevel`。
            session_id: 当前 Agent 会话标识符。
            step_num: 当前 Agent 步骤编号。

        Returns:
            ``(should_proceed, action)`` 元组：
                - ``(True, "allow")``——SAFE 或 MODERATE，或 DANGEROUS 但用户已批准。
                - ``(False, "confirm_required")``——DANGEROUS，已发布事件，等待响应。
                - ``(False, "user_denied")``——用户明确拒绝了该操作。
                - ``(False, "timeout")``——超时内未收到响应。
        """
        from loopai.tools.types import PermissionLevel

        # SAFE 和 MODERATE 命令立即放行。
        if permission_level in (PermissionLevel.SAFE, PermissionLevel.MODERATE):
            return (True, "allow")

        # DANGEROUS——需要用户确认。
        # 包含 tool_call_id 确保每个工具调用获得唯一确认
        confirmation_id = f"{session_id}_{tool_name}_{step_num}"
        if tool_call_id:
            confirmation_id += f"_{tool_call_id}"

        # 发布 confirmation_required 事件供 CLI/前端消费者处理。
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

        # 创建阻塞事件，等待 respond() 或超时。
        event = asyncio.Event()
        self._pending[confirmation_id] = event

        try:
            await asyncio.wait_for(
                event.wait(), timeout=self.confirmation_timeout
            )
        except asyncio.TimeoutError:
            # 清理并发布超时事件。
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

        # 检索并清理用户的决定。
        approved = self._results.pop(confirmation_id, False)
        self._pending.pop(confirmation_id, None)

        # 发布响应事件用于审计追踪。
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
        """响应待处理的确认请求。

        由 CLI 消费者（或任何外部 Agent）调用，用于批准或
        拒绝 DANGEROUS 命令。这是一个同步方法——它存储
        结果并通知等待中的协程。

        Args:
            confirmation_id: 来自事件负载的确认 ID。
            approved: ``True`` 允许执行，``False`` 拒绝。
        """
        self._results[confirmation_id] = approved
        if confirmation_id in self._pending:
            self._pending[confirmation_id].set()


# ═══════════════════════════════════════════════════════════════════════════
# TokenGuard — token 预算守卫（D-01, D-03）
# ═══════════════════════════════════════════════════════════════════════════


class TokenGuard:
    """Token 预算守卫——检测上下文使用量何时达到阈值。

    根据可配置的上下文窗口阈值检查当前消息列表。
    返回一个信号，调用者（通常是 FSM）可据此决定
    是否触发 :class:`ContextCompressor`。

    此守卫遵循与 :class:`BudgetGuard` 相同的模式：
    ``check()`` 返回状态信号而不直接修改消息列表。

    决策引用:
        D-01: 滑动窗口 + 在 75% 阈值时摘要压缩。
        D-03: tiktoken cl100k_base 用于近似计数。

    Args:
        token_counter: :class:`~loopai.context.token_counter.TokenCounter` 实例。
        window_size: 上下文窗口的 token 预算（默认 128000）。
        threshold: 触发 ``"compress"`` 信号的 *window_size* 比例
            （默认 0.75）。
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
        """检查消息列表是否超过 token 阈值。

        Args:
            messages: 当前消息列表。

        Returns:
            ``(action, token_count, threshold_tokens)``。
            - ``action``: ``"ok"`` 如果 token 计数低于阈值，
              ``"compress"`` 如果达到或超过阈值。
            - ``token_count``: 当前消息的 token 计数。
            - ``threshold_tokens``: 阈值
              （``window_size * threshold``，已取整）。
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
    """守卫管道中一次守卫检查的结果。

    Attributes:
        action: "ok"（全部通过）、"compress"（TokenGuard 需要压缩）、
                "blocked"（守卫违规）、"warn"（接近限制）。
        guard_name: 产生此结果的守卫类名称。
        detail: 面向用户的阻止守卫详细消息。
    """

    action: str
    guard_name: str | None = None
    detail: str | None = None


# ═══════════════════════════════════════════════════════════════════════════
# CostGuard — 成本估算守卫
# ═══════════════════════════════════════════════════════════════════════════


class CostGuard:
    """成本估算守卫——根据 token 计数估算 LLM 调用成本。

    使用硬编码的模型定价表。当估算成本超过单次调用预算时返回信号。

    Attributes:
        model_cost_per_1k: 模型前缀到 (input_cost_per_1k, output_cost_per_1k) 的映射。
        max_cost_per_call: 单次 LLM 调用的最大允许成本（美元，默认 0.05）。
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
        """估算单次 LLM 调用的成本。

        使用模型前缀匹配（例如 "gpt-4o-2024-08-06" 匹配 "gpt-4o"）。
        如果在定价表中找不到模型，则使用 gpt-4o 定价作为回退。

        返回以美元为单位的估算成本（四舍五入到 6 位小数）。
        """
        input_cost, output_cost = self._get_rates(model_name)
        # 保守估计：假设输出约为总 token 的 30%
        input_tokens = int(token_count * 0.7)
        output_tokens = token_count - input_tokens
        cost = (input_tokens / 1000) * input_cost + (output_tokens / 1000) * output_cost
        return round(cost, 6)

    def _get_rates(self, model_name: str) -> tuple[float, float]:
        """通过前缀匹配查找模型名称的定价费率。"""
        for prefix, rates in self._pricing.items():
            if model_name.startswith(prefix):
                return rates
        return self._pricing.get("gpt-4o", (0.0025, 0.01))

    def check(self, messages: list[dict], token_count: int | None = None,
              model_name: str = "gpt-4o") -> GuardResult:
        """检查估算成本是否在预算内。

        Args:
            messages: 消息列表（token_count 未提供时使用——此版本未使用）。
            token_count: 预计算的 token 计数。如果为 None，使用 len(messages) * 500 作为粗略估算。
            model_name: 用于定价查找的模型名称。

        Returns:
            如果成本在预算内，返回 action="ok" 的 GuardResult；超出预算则返回 "blocked"。
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
    """速率限制守卫——在时间窗口内限制工具调用频率。

    为每工具使用滑动时间窗口（非滑动计数）。
    追踪调用时间戳，如果窗口内调用超过限制则阻止。

    Attributes:
        max_calls: 时间窗口内允许的最大调用次数（默认 10）。
        window_seconds: 时间窗口秒数（默认 60.0）。
    """

    def __init__(self, max_calls: int = 10, window_seconds: float = 60.0) -> None:
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        self._call_times: dict[str, list[float]] = {}  # tool_name -> [timestamps]

    def check(self, tool_name: str) -> GuardResult:
        """检查工具是否超出速率限制。

        Args:
            tool_name: 要检查速率限制的工具。

        Returns:
            如果在限制内，返回 action="ok" 的 GuardResult；超出则返回 "blocked"。
        """
        now = time.monotonic()
        timestamps = self._call_times.get(tool_name, [])

        # 修剪窗口外的时间戳
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
        """为速率限制记录一次工具调用。

        必须在工具执行后调用，以更新速率计数器。
        """
        if tool_name not in self._call_times:
            self._call_times[tool_name] = []
        self._call_times[tool_name].append(time.monotonic())


# ═══════════════════════════════════════════════════════════════════════════
# GuardPipeline — 顺序守卫管道，短路由机制
# ═══════════════════════════════════════════════════════════════════════════


class GuardPipeline:
    """顺序守卫管道，遇到第一个非 ok 结果时短路。

    按顺序运行每个守卫的 check()。如果任何守卫返回 action != "ok"，
    管道立即短路并返回该守卫的结果。

    守卫以可调用对象方式注入。管道规范化不同的返回类型：
    GuardResult 对象（CostGuard、RateLimitGuard）和
    元组（TokenGuard 返回 (action, count, threshold)）。
    """

    def __init__(self, guards: list[Any]) -> None:
        self._guards = guards

    def check(self, messages: list[dict]) -> GuardResult:
        """顺序运行每个守卫。遇到第一个非 ok 结果时短路。

        Args:
            messages: 当前消息列表（传递给每个守卫）。

        Returns:
            首个阻止型守卫的 GuardResult，或所有守卫通过时返回
            GuardResult(action="ok")。
        """
        for guard in self._guards:
            raw = guard.check(messages)

            # 规范化：处理 GuardResult 对象和元组两种返回类型
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
