"""ContextCompressor 测试 —— 滑动窗口 + LLM 摘要压缩。

测试覆盖：
- 低于阈值时不压缩
- 达到阈值时触发压缩并生成摘要消息
- _find_round_cutoff 正确识别对话轮
- 保留轮次的消息内容在压缩后保持完整
- 消息轮数不足时返回 0 不过滤
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from loopai.context.compressor import ContextCompressor
from loopai.context.token_counter import TokenCounter


class TestContextCompressor:
    """ContextCompressor 核心行为测试。"""

    async def test_no_compression_below_threshold(self) -> None:
        """消息 token 数 < 75% 窗口时，返回 (messages, False, _)。"""
        counter = MagicMock(spec=TokenCounter)
        counter.count_messages.return_value = 50000
        compressor = ContextCompressor(
            counter, window_size=128000, threshold=0.75, preserve_rounds=3
        )
        messages = [{"role": "user", "content": "Hello"}]

        result, was_compressed, metadata = await compressor.check_and_compress(
            messages, summary_fn=AsyncMock()
        )

        assert was_compressed is False
        assert result is messages
        assert metadata["tokens_before"] == 50000
        assert metadata["tokens_after"] == 50000
        assert metadata["action"] == "skipped"

    async def test_compression_above_threshold(self) -> None:
        """消息 token 数 >= 75% 窗口时，触发压缩并生成 [Compressed Summary] 消息。"""
        counter = MagicMock(spec=TokenCounter)
        # First call (tokens_before) returns high value; second (tokens_after) lower
        counter.count_messages.side_effect = [100000, 30000]
        compressor = ContextCompressor(
            counter, window_size=128000, threshold=0.75, preserve_rounds=2
        )

        messages = [
            # 将被摘要的旧消息 (0-1)
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Old irrelevant question"},
            # 第 2 轮 (preserve, _find_round_cutoff 返回 2)
            {"role": "assistant", "tool_calls": [{"id": "c1", "function": {"name": "get_weather", "arguments": "{}"}}], "content": None},
            {"role": "tool", "content": "22C", "tool_call_id": "c1"},
            {"role": "assistant", "content": "Tokyo is 22C"},
            {"role": "user", "content": "Weather in London?"},
            # 第 1 轮 (preserve, 最新)
            {"role": "assistant", "tool_calls": [{"id": "c2", "function": {"name": "get_weather", "arguments": "{}"}}], "content": None},
            {"role": "tool", "content": "15C", "tool_call_id": "c2"},
            {"role": "assistant", "content": "London is 15C"},
        ]

        summary_fn = AsyncMock(return_value="Test summary")

        result, was_compressed, metadata = await compressor.check_and_compress(
            messages, summary_fn=summary_fn
        )

        assert was_compressed is True
        # 第一条消息应该是系统角色的摘要消息
        assert result[0]["role"] == "system"
        assert "[Compressed Summary]" in result[0]["content"]
        assert result[0]["content"] == "[Compressed Summary] Test summary"

        # 验证 metadata
        assert metadata["tokens_before"] == 100000
        assert metadata["tokens_after"] == 30000
        assert metadata["tokens_saved"] == 70000
        assert metadata["rounds_preserved"] == 2
        assert metadata["summary_message_count"] == 1

        # 验证保留轮次内容完整
        # cutoff_idx for preserve_rounds=2:
        #   i=8 assistant(no tc) → i=7 tool → i=6 assistant(tc) round=1 → i=5 user
        #   → i=4 assistant(no tc) → i=3 tool → i=2 assistant(tc) round=2 → i=1
        #   cutoff = 1+1 = 2
        assert result[1:] == messages[2:]  # all from index 2 onward preserved

    async def test_preserved_rounds_content(self) -> None:
        """保留轮次的对话消息在压缩后保持完整。"""
        counter = MagicMock(spec=TokenCounter)
        counter.count_messages.side_effect = [100000, 40000]
        compressor = ContextCompressor(
            counter, window_size=128000, threshold=0.75, preserve_rounds=2
        )

        messages = [
            # 将被摘要的旧消息
            {"role": "user", "content": "Old Q"},
            # 第 2 轮 (preserved)
            {"role": "assistant", "tool_calls": [{"id": "c1"}], "content": None},
            {"role": "tool", "content": "R1", "tool_call_id": "c1"},
            {"role": "user", "content": "Mid Q"},
            # 第 1 轮 (preserved, 最新)
            {"role": "assistant", "tool_calls": [{"id": "c2"}], "content": None},
            {"role": "tool", "content": "R2", "tool_call_id": "c2"},
            {"role": "assistant", "content": "Final reply"},
        ]

        result, was_compressed, metadata = await compressor.check_and_compress(
            messages, summary_fn=AsyncMock(return_value="Summary")
        )

        assert was_compressed is True

        # cutoff_idx for preserve_rounds=2:
        #   i=6 assistant(no tc) → i=5 tool → i=4 assistant(tc) round=1 → i=3 user
        #   → i=2 tool → i=1 assistant(tc) round=2 → i=0
        #   cutoff = 0+1 = 1
        preserved_count = len(messages) - 1  # cutoff_idx=1 → preserved[1:]
        assert len(result) == 1 + preserved_count  # 1 summary + preserved

        # 保留的消息内容不变
        assert result[1] == messages[1]
        assert result[-1] == messages[-1]

    def test_find_round_cutoff(self) -> None:
        """_find_round_cutoff 正确保留最后 N 轮。"""
        counter = MagicMock(spec=TokenCounter)
        compressor = ContextCompressor(
            counter, window_size=128000, threshold=0.75, preserve_rounds=2
        )

        messages = [
            {"role": "user", "content": "Q1"},
            {"role": "assistant", "tool_calls": [{"id": "c1"}], "content": None},
            {"role": "tool", "content": "R1", "tool_call_id": "c1"},
            {"role": "user", "content": "Q2"},
            {"role": "assistant", "tool_calls": [{"id": "c2"}], "content": None},
            {"role": "tool", "content": "R2", "tool_call_id": "c2"},
            {"role": "user", "content": "Q3"},
            {"role": "assistant", "tool_calls": [{"id": "c3"}], "content": None},
            {"role": "tool", "content": "R3", "tool_call_id": "c3"},
        ]

        cutoff = compressor._find_round_cutoff(messages)

        # preserve_rounds=2:
        #   i=8 tool → i=7 assistant(tc) round=1 → i=6 user → i=5 tool
        #   → i=4 assistant(tc) round=2 → i=3
        #   cutoff = 3+1 = 4
        assert cutoff == 4

    def test_insufficient_rounds_no_cutoff(self) -> None:
        """消息轮数 < preserve_rounds 时返回索引 0。"""
        counter = MagicMock(spec=TokenCounter)
        compressor = ContextCompressor(
            counter, window_size=128000, threshold=0.75, preserve_rounds=3
        )

        messages = [
            {"role": "user", "content": "Q1"},
            {"role": "assistant", "tool_calls": [{"id": "c1"}], "content": None},
            {"role": "tool", "content": "R1", "tool_call_id": "c1"},
        ]

        cutoff = compressor._find_round_cutoff(messages)

        # 只有 1 轮但 preserve_rounds=3，返回 0
        assert cutoff == 0

    async def test_insufficient_rounds_returns_zero_cutoff(self) -> None:
        """不足 preserve_rounds 轮的边缘情况 — 压缩时跳过。"""
        counter = MagicMock(spec=TokenCounter)
        counter.count_messages.return_value = 100000  # 超过阈值
        compressor = ContextCompressor(
            counter, window_size=128000, threshold=0.75, preserve_rounds=5
        )

        messages = [
            {"role": "user", "content": "Q1"},
            {"role": "assistant", "tool_calls": [{"id": "c1"}], "content": None},
            {"role": "tool", "content": "R1", "tool_call_id": "c1"},
        ]

        result, was_compressed, metadata = await compressor.check_and_compress(
            messages, summary_fn=AsyncMock()
        )

        assert was_compressed is False
        assert metadata["action"] == "skipped"

    def test_build_summary_prompt(self) -> None:
        """_build_summary_prompt 生成包含消息内容的 prompt。"""
        counter = MagicMock(spec=TokenCounter)
        compressor = ContextCompressor(counter)

        messages = [
            {"role": "user", "content": "What's the weather?"},
            {"role": "assistant", "content": "Sunny 22C"},
        ]

        prompt = compressor._build_summary_prompt(messages)

        assert "摘要" in prompt
        assert "[user]: What's the weather?" in prompt
        assert "[assistant]: Sunny 22C" in prompt
