"""Context compression via sliding window + LLM summarization.

Provides :class:`ContextCompressor` which detects when the context window
exceeds a configurable threshold and compresses older messages into an
LLM-generated summary, preserving the most recent conversation rounds.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from loopai.context.token_counter import TokenCounter


class ContextCompressor:
    """Sliding-window + summary context compressor.

    Monitors token usage against a configurable context window.  When the
    token count reaches *threshold* (e.g. 75% of *window_size*), old
    conversation rounds are summarised via an async *summary_fn* and
    replaced with a single system message tagged ``[Compressed Summary]``.

    Args:
        token_counter: A :class:`TokenCounter` instance for token counting.
        window_size: Token budget for the context window (default 128000
            for GPT-4o).
        threshold: Fraction of *window_size* that triggers compression (0.75).
        target: Target fraction after compression (0.50) — reserved for
            future use.
        preserve_rounds: Number of most-recent conversation rounds to keep
            intact (default 3).
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
    # Public API
    # ------------------------------------------------------------------

    async def check_and_compress(
        self,
        messages: list[dict],
        summary_fn: Callable[[list[dict]], Awaitable[str]],
    ) -> tuple[list[dict], bool, dict]:
        """Check token usage and compress if above threshold.

        Args:
            messages: The current message list (OpenAI-compatible format).
            summary_fn: An async callable that receives the old message
                block to summarise and returns a summary string.

        Returns:
            ``(compressed_messages, was_compressed, metadata)``.
            *metadata* keys:
            - ``tokens_before``: token count before compression.
            - ``tokens_after``: token count after compression.
            - ``tokens_saved``: difference (may be 0 when skipped).
            - ``rounds_preserved``: number of rounds kept intact.
            - ``summary_message_count``: number of summary messages added.
            - ``action``: ``"skipped"`` or ``"compressed"``.
        """
        tokens_before = self._counter.count_messages(messages)
        threshold_tokens = int(self._window_size * self._threshold)

        # ── Below threshold → skip ─────────────────────────────────
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

        # ── Above threshold → find cutoff ──────────────────────────
        cutoff_idx = self._find_round_cutoff(messages)

        if cutoff_idx == 0:
            # Not enough rounds to safely compress — skip.
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
    # Round-cutoff logic
    # ------------------------------------------------------------------

    def _find_round_cutoff(
        self,
        messages: list[dict],
        preserve_rounds: int | None = None,
    ) -> int:
        """Find the split index for summarisation.

        Walks backwards from the end of the message list, counting
        "conversation rounds".  A **round** is defined as an assistant
        message with ``tool_calls`` plus any immediately-following tool
        messages.  The *preserve_rounds* most-recent full rounds are kept
        intact; messages before the oldest preserved round are returned
        as the cutoff index.

        System and user messages that precede the first assistant reply
        are never part of a round — they are always candidates for
        summarisation.

        Args:
            messages: The full message list.
            preserve_rounds: Number of rounds to preserve.  Defaults to
                the instance's ``_preserve_rounds``.

        Returns:
            Index at which to split so that
            ``preserved = messages[cutoff_idx:]``.  Returns 0 when
            there are fewer rounds than *preserve_rounds* (nothing to
            cut).
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

        # *i* now points one position before the start of the oldest
        # preserved round.  The cutoff is therefore *i + 1*.
        return i + 1

    # ------------------------------------------------------------------
    # Summary-prompt builder
    # ------------------------------------------------------------------

    def _build_summary_prompt(self, messages: list[dict]) -> str:
        """Build a prompt instructing an LLM to summarise the given messages.

        The prompt is written in English and asks the LLM to extract:
        1. The user's original request and key requirements.
        2. All tools that were called and their results.
        3. Important findings and data discovered.
        4. The current state of the task.

        Args:
            messages: The old message block to summarise.

        Returns:
            A prompt string suitable for passing to an LLM ``summary_fn``.
        """
        lines: list[str] = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content") or ""
            snippet = content[:200] + "..." if len(content) > 200 else content
            lines.append(f"[{role}]: {snippet}")

        messages_text = "\n".join(lines)

        return (
            "You are an AI agent's context summariser. Summarise the following "
            "conversation history concisely, preserving:\n"
            "1. The user's original request and key requirements\n"
            "2. All tools that were called and their results\n"
            "3. Important findings and data discovered\n"
            "4. The current state of the task\n"
            "\n"
            "Original messages:\n"
            f"{messages_text}\n"
            "\n"
            "Summary:"
        )
