""":mod:`loopai.context.token_counter` — Token counting via tiktoken.

Provides :class:`TokenProtocol` as a provider-tokenizer interface (D-04)
and :class:`TokenCounter` as the concrete tiktoken-based implementation.

OpenAI 消息格式计数规范:
    - 基础消息开销: 3 tokens（role 标记）
    - content 文本: 对 content 字段做 tiktoken 编码
    - name 字段: 1 token 额外开销 + name 的 token 数
    - tool_calls: 3 tokens 基础 + 每条 call 的工具名称和 arguments 的 token 数
    - 消息列表末尾: 3 tokens（assistant 角色粘合开销）
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import tiktoken


@runtime_checkable
class TokenizerProtocol(Protocol):
    """Provider-tokenizer interface (D-04).

    Reserved for future provider-specific tokenizers
    (DeepSeek, Anthropic, etc.).  TokenCounter is the only implementation
    in Phase 3.
    """

    def count_text(self, text: str) -> int:
        """Count tokens in a plain text string."""
        ...

    def count_message(self, message: dict) -> int:
        """Count tokens in a single OpenAI-format message dict."""
        ...

    def count_messages(self, messages: list[dict]) -> int:
        """Count tokens across a list of messages."""
        ...


class TokenCounter:
    """Token counting using tiktoken with cl100k_base encoding.

    Implements :class:`TokenizerProtocol`.

    Args:
        encoding_name: The tiktoken encoding to use.  Defaults to
            ``"cl100k_base"`` which is suitable for GPT-4 and GPT-3.5
            models (D-03).
    """

    def __init__(self, encoding_name: str = "cl100k_base") -> None:
        self._encoding = tiktoken.get_encoding(encoding_name)

    # ── Public API ──────────────────────────────────────────────────

    def count_text(self, text: str) -> int:
        """Count tokens in a plain text string.

        Args:
            text: The input text to encode.

        Returns:
            Number of tokens.
        """
        return len(self._encoding.encode(text))

    def count_message(self, message: dict) -> int:
        """Count tokens in a single OpenAI-format message dict.

        The counting follows the OpenAI tiktoken cookbook specification:

        - Base overhead: 3 tokens per message (for ``role`` markers).
        - ``content`` (str): token count of the text.
        - ``name`` (optional): 1 extra token + token count of the name.
        - ``tool_calls`` (optional): 3 tokens base + per-call cost
          (tool name + arguments).

        Args:
            message: An OpenAI-format message dict (e.g.
                ``{"role": "user", "content": "Hello"}``).

        Returns:
            Number of tokens for this message.
        """
        tokens = 3  # Base overhead per message (role markers)

        content = message.get("content")
        if content:
            tokens += self.count_text(content)

        name = message.get("name")
        if name:
            tokens += 1 + self.count_text(name)

        tool_calls = message.get("tool_calls")
        if tool_calls:
            tokens += 3  # Base overhead for tool_calls
            for tc in tool_calls:
                # tool_calls can be a dict (raw API response) or an object
                if isinstance(tc, dict):
                    tc_data = tc
                else:
                    tc_data = tc.model_dump() if hasattr(tc, "model_dump") else {}

                function_info = tc_data.get("function", tc_data)
                if isinstance(function_info, dict):
                    tokens += self.count_text(
                        function_info.get("name", "") + function_info.get("arguments", "")
                    )
                else:
                    # If function is an object with name/arguments attrs
                    tokens += self.count_text(
                        getattr(function_info, "name", "")
                        + getattr(function_info, "arguments", "")
                    )

        return tokens

    def count_messages(self, messages: list[dict]) -> int:
        """Count tokens across a list of messages.

        Sums the token count of each message and adds 3 tokens at the end
        for the assistant-role glue overhead.

        Args:
            messages: A list of OpenAI-format message dicts.

        Returns:
            Total number of tokens for the message list.
        """
        total = sum(self.count_message(m) for m in messages)
        total += 3  # Assistant-role glue overhead
        return total
