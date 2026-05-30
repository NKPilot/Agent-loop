"""基于滑动窗口 + LLM 摘要的上下文压缩。

提供 :class:`ContextCompressor`，当上下文窗口超过可配置阈值时，
检测并将旧消息压缩为 LLM 生成的摘要，保留最近的对话轮次。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from loopai.context.token_counter import TokenCounter


class ContextCompressor:
    """滑动窗口 + 摘要的上下文压缩器。

    根据可配置的上下文窗口监控 token 使用量。当 token 计数达到
    *threshold*（例如 *window_size* 的 75%）时，通过异步 *summary_fn*
    将旧对话轮次进行摘要，并替换为标记了 ``[Compressed Summary]`` 的
    单条 system 消息。

    Args:
        token_counter: 用于 token 计数的 :class:`TokenCounter` 实例。
        window_size: 上下文窗口的 token 预算（GPT-4o 默认 128000）。
        threshold: *window_size* 中触发压缩的比例（0.75）。
        target: 压缩后的目标比例（0.50）——保留供将来使用。
        preserve_rounds: 保持完整的最新对话轮次数（默认 3）。
    """

    def __init__(
        self,
        token_counter: TokenCounter,
        window_size: int = 128000,
        threshold: float = 0.75,
        target: float = 0.50,
        preserve_rounds: int = 3,
    ) -> None:
        self._counter = token_counter
        self._window_size = window_size
        self._threshold = threshold
        self._target = target
        self._preserve_rounds = preserve_rounds

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------

    async def check_and_compress(
        self,
        messages: list[dict],
        summary_fn: Callable[[list[dict]], Awaitable[str]],
    ) -> tuple[list[dict], bool, dict]:
        """检查 token 使用量，如果超过阈值则压缩。

        Args:
            messages: 当前消息列表（OpenAI 兼容格式）。
            summary_fn: 一个异步可调用对象，接收要摘要的旧消息块
                并返回摘要字符串。

        Returns:
            ``(compressed_messages, was_compressed, metadata)``。
            *metadata* 键：
            - ``tokens_before``: 压缩前的 token 计数。
            - ``tokens_after``: 压缩后的 token 计数。
            - ``tokens_saved``: 差值（跳过量时可能为 0）。
            - ``rounds_preserved``: 保持完整的轮次数。
            - ``summary_message_count``: 添加的摘要消息数量。
            - ``action``: ``"skipped"`` 或 ``"compressed"``。
        """
        tokens_before = self._counter.count_messages(messages)
        threshold_tokens = int(self._window_size * self._threshold)

        # ── 低于阈值 → 跳过 ───────────────────────────────────
        if tokens_before < threshold_tokens:
            return (
                messages,
                False,
                {
                    "tokens_before": tokens_before,
                    "tokens_after": tokens_before,
                    "action": "skipped",
                },
            )

        # ── 高于阈值 → 查找分割点 ──────────────────────────────
        cutoff_idx = self._find_round_cutoff(messages)

        if cutoff_idx == 0:
            # 轮次不够无法安全压缩——跳过。
            return (
                messages,
                False,
                {
                    "tokens_before": tokens_before,
                    "tokens_after": tokens_before,
                    "action": "skipped",
                },
            )

        old_block = messages[:cutoff_idx]
        preserved = messages[cutoff_idx:]

        summary = await summary_fn(old_block)

        summary_msg: dict = {
            "role": "system",
            "content": f"[Compressed Summary] {summary}",
        }

        new_messages = [summary_msg] + preserved
        tokens_after = self._counter.count_messages(new_messages)

        return (
            new_messages,
            True,
            {
                "tokens_before": tokens_before,
                "tokens_after": tokens_after,
                "tokens_saved": tokens_before - tokens_after,
                "rounds_preserved": self._preserve_rounds,
                "summary_message_count": 1,
            },
        )

    # ------------------------------------------------------------------
    # 轮次分割点逻辑
    # ------------------------------------------------------------------

    def _find_round_cutoff(
        self,
        messages: list[dict],
        preserve_rounds: int | None = None,
    ) -> int:
        """查找用于摘要的分割索引。

        从消息列表末尾向后遍历，计数"对话轮次"。一个**轮次**定义
        为一条带有 ``tool_calls`` 的 assistant 消息加上紧随其后的
        tool 消息。最近 *preserve_rounds* 个完整轮次保持完整；
        最老的保留轮次之前的消息作为分割索引返回。

        第一个 assistant 回复之前的 system 和 user 消息
        从不属于任何轮次——它们始终是摘要的候选。

        Args:
            messages: 完整消息列表。
            preserve_rounds: 保留的轮次数。默认为实例的
                ``_preserve_rounds``。

        Returns:
            分割索引，使得 ``preserved = messages[cutoff_idx:]``。
            当轮次少于 *preserve_rounds* 时返回 0（无需分割）。
        """
        preserve_rounds = (
            preserve_rounds if preserve_rounds is not None else self._preserve_rounds
        )

        rounds_found = 0
        i = len(messages) - 1

        while i >= 0 and rounds_found < preserve_rounds:
            msg = messages[i]
            role = msg.get("role", "")

            if role == "assistant" and msg.get("tool_calls"):
                rounds_found += 1

            i -= 1

        if rounds_found < preserve_rounds:
            return 0

        # *i* 现在指向最老保留轮次开始位置的前一个位置。
        # 因此分割点是 *i + 1*。
        return i + 1

    # ------------------------------------------------------------------
    # 摘要提示构建器
    # ------------------------------------------------------------------

    def _build_summary_prompt(self, messages: list[dict]) -> str:
        """构建一个提示，指示 LLM 对给定消息进行摘要。

        提示使用中文编写，要求 LLM 提取：
        1. 用户的原始请求和关键要求。
        2. 所有被调用的工具及其结果。
        3. 重要的发现和数据。
        4. 任务的当前状态。

        Args:
            messages: 要摘要的旧消息块。

        Returns:
            适合传递给 LLM ``summary_fn`` 的提示字符串。
        """
        lines: list[str] = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content") or ""
            snippet = content[:200] + "..." if len(content) > 200 else content
            lines.append(f"[{role}]: {snippet}")

        messages_text = "\n".join(lines)

        return (
            "你是一个 AI Agent 的上下文摘要器。简洁地摘要以下对话历史，保留：\n"
            "1. 用户的原始请求和关键要求\n"
            "2. 所有被调用的工具及其结果\n"
            "3. 重要的发现和数据\n"
            "4. 任务的当前状态\n"
            "\n"
            "原始消息：\n"
            f"{messages_text}\n"
            "\n"
            "摘要："
        )
