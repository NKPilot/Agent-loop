""":mod:`loopai.context.token_counter` — 基于 tiktoken 的 Token 计数。

提供 :class:`TokenizerProtocol` 作为提供商-分词器接口（D-04），
以及 :class:`TokenCounter` 作为基于 tiktoken 的具体实现。

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
    """提供商-分词器接口（D-04）。

    保留供将来提供商特定的分词器使用
    （DeepSeek、Anthropic 等）。TokenCounter 是 Phase 3 中唯一的实现。
    """

    def count_text(self, text: str) -> int:
        """统计纯文本字符串中的 token 数。"""
        ...

    def count_message(self, message: dict) -> int:
        """统计单条 OpenAI 格式消息字典中的 token 数。"""
        ...

    def count_messages(self, messages: list[dict]) -> int:
        """统计消息列表中的 token 总数。"""
        ...


class TokenCounter:
    """使用 tiktoken 和 cl100k_base 编码进行 token 计数。

    实现 :class:`TokenizerProtocol`。

    Args:
        encoding_name: 要使用的 tiktoken 编码。默认为
            ``"cl100k_base"``，适用于 GPT-4 和 GPT-3.5
            模型（D-03）。
    """

    def __init__(self, encoding_name: str = "cl100k_base") -> None:
        self._encoding = tiktoken.get_encoding(encoding_name)

    # ── 公共 API ──────────────────────────────────────────────────

    def count_text(self, text: str) -> int:
        """统计纯文本字符串中的 token 数。

        Args:
            text: 要编码的输入文本。

        Returns:
            Token 数量。
        """
        return len(self._encoding.encode(text))

    def count_message(self, message: dict) -> int:
        """统计单条 OpenAI 格式消息字典中的 token 数。

        计数遵循 OpenAI tiktoken cookbook 规范：

        - 基础开销：每条消息 3 tokens（用于 ``role`` 标记）。
        - ``content``（str）：文本的 token 数。
        - ``name``（可选）：1 个额外 token + name 的 token 数。
        - ``tool_calls``（可选）：3 tokens 基础 + 每条调用的成本
          （工具名称 + arguments）。

        Args:
            message: OpenAI 格式的消息字典（例如
                ``{"role": "user", "content": "Hello"}``）。

        Returns:
            此消息的 token 数。
        """
        tokens = 3  # 每条消息的基础开销（角色标记）

        content = message.get("content")
        if content:
            tokens += self.count_text(content)

        name = message.get("name")
        if name:
            tokens += 1 + self.count_text(name)

        tool_calls = message.get("tool_calls")
        if tool_calls:
            tokens += 3  # tool_calls 的基础开销
            for tc in tool_calls:
                # tool_calls 可以是字典（原始 API 响应）或对象
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
                    # 如果 function 是带有 name/arguments 属性的对象
                    tokens += self.count_text(
                        getattr(function_info, "name", "")
                        + getattr(function_info, "arguments", "")
                    )

        return tokens

    def count_messages(self, messages: list[dict]) -> int:
        """统计消息列表中的 token 总数。

        将每条消息的 token 数相加，并在末尾加上 3 tokens
        用于 assistant 角色粘合开销。

        Args:
            messages: OpenAI 格式的消息字典列表。

        Returns:
            消息列表的 token 总数。
        """
        total = sum(self.count_message(m) for m in messages)
        total += 3  # Assistant 角色粘合开销
        return total
