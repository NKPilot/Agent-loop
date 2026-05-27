"""守卫测试 —— LoopDetector、MessageValidator、BudgetGuard。"""

from __future__ import annotations

import pytest

from loopai.state_machine.guards import (
    LoopDetector,
    MessageValidator,
    ValidationError,
)


# =============================================================================
# LoopDetector 测试 (测试 1-7)
# =============================================================================


class TestLoopDetector:
    """LoopDetector 循环检测测试 —— 7 个用例。"""

    def test_first_tool_call_allowed(self) -> None:
        """第一次工具调用应该被允许。"""
        detector = LoopDetector(window_size=20, warn_threshold=3, block_threshold=5)
        should_proceed, action = detector.check("get_weather", {"city": "Tokyo"})

        assert should_proceed is True
        assert action == "allow"

    def test_three_consecutive_warns(self) -> None:
        """连续 3 次相同工具调用应返回 warn。"""
        detector = LoopDetector(window_size=20, warn_threshold=3, block_threshold=5)

        # 第一次和第二次: allow
        detector.check("get_weather", {"city": "Tokyo"})
        should_proceed, action = detector.check("get_weather", {"city": "Tokyo"})

        assert should_proceed is True
        assert action == "allow"

        # 第三次: warn
        should_proceed, action = detector.check("get_weather", {"city": "Tokyo"})

        assert should_proceed is True
        assert action == "warn"

    def test_five_consecutive_blocks(self) -> None:
        """连续 5 次相同工具调用应返回 block。"""
        detector = LoopDetector(window_size=20, warn_threshold=3, block_threshold=5)

        # 第 1-4 次
        for _ in range(4):
            detector.check("get_weather", {"city": "Tokyo"})

        # 第 5 次: block
        should_proceed, action = detector.check("get_weather", {"city": "Tokyo"})

        assert should_proceed is False
        assert action == "block"

    def test_different_tool_resets_count(self) -> None:
        """调用不同工具应重置连续计数。"""
        detector = LoopDetector(window_size=20, warn_threshold=3, block_threshold=5)

        # 两次相同调用
        detector.check("get_weather", {"city": "Tokyo"})
        detector.check("get_weather", {"city": "Tokyo"})

        # 不同工具: 计数重置
        should_proceed, action = detector.check("get_time", {"timezone": "UTC"})

        assert should_proceed is True
        assert action == "allow"

        # 再次回到 get_weather — 从 1 重新开始
        should_proceed, action = detector.check("get_weather", {"city": "Tokyo"})
        assert should_proceed is True
        assert action == "allow"

    def test_same_name_different_args_different_signature(self) -> None:
        """相同工具名但不同参数应产生不同的签名，计数不累计。"""
        detector = LoopDetector(window_size=20, warn_threshold=3, block_threshold=5)

        # 两次 Tokyo
        detector.check("get_weather", {"city": "Tokyo"})
        detector.check("get_weather", {"city": "Tokyo"})

        # 不同 city: 签名不同，计数重置
        should_proceed, action = detector.check("get_weather", {"city": "London"})

        assert should_proceed is True
        assert action == "allow"

    def test_pattern_persists_force_exit(self) -> None:
        """block 后如果模式仍然持续，应返回 force_exit。"""
        detector = LoopDetector(window_size=20, warn_threshold=3, block_threshold=5)

        # 触发 block（第 5 次）
        for _ in range(5):
            detector.check("get_weather", {"city": "Tokyo"})

        # 第 6 次: 模式持续 -> force_exit
        should_proceed, action = detector.check("get_weather", {"city": "Tokyo"})

        assert should_proceed is False
        assert action == "force_exit"

    def test_reset_clears_state(self) -> None:
        """reset() 应清除连续计数和最后签名。"""
        detector = LoopDetector(window_size=20, warn_threshold=3, block_threshold=5)

        # 积累一些历史
        detector.check("get_weather", {"city": "Tokyo"})
        detector.check("get_weather", {"city": "Tokyo"})

        # 重置
        detector.reset()

        # 重置后第一次调用应为 allow
        should_proceed, action = detector.check("get_weather", {"city": "Tokyo"})
        assert should_proceed is True
        assert action == "allow"


# =============================================================================
# MessageValidator 测试 (测试 8-13)
# =============================================================================


class TestMessageValidator:
    """MessageValidator 消息验证测试 —— 6 个用例。"""

    def test_valid_alternating_messages(self) -> None:
        """合法的交替 user/assistant 消息应通过验证。"""
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]

        # 不应抛出异常
        MessageValidator.validate(messages)

    def test_assistant_with_tool_calls_followed_by_tool_role(self) -> None:
        """assistant 的 tool_calls 后跟对应 tool 角色消息应通过验证。"""
        messages = [
            {"role": "user", "content": "What's the weather?"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_abc123",
                        "type": "function",
                        "function": {
                            "name": "get_weather",
                            "arguments": '{"city": "Tokyo"}',
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_abc123",
                "content": "Sunny, 22C",
            },
        ]

        # 不应抛出异常
        MessageValidator.validate(messages)

    def test_orphan_tool_call_rejected(self) -> None:
        """孤立的 tool_call（无对应 tool 消息）应被拒绝。"""
        messages = [
            {"role": "user", "content": "What's the weather?"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_abc123",
                        "type": "function",
                        "function": {
                            "name": "get_weather",
                            "arguments": '{"city": "Tokyo"}',
                        },
                    }
                ],
            },
            # 缺少 tool 角色消息！直接跳到 user
            {"role": "user", "content": "Thanks"},
        ]

        with pytest.raises(ValidationError, match="call_abc123"):
            MessageValidator.validate(messages)

    def test_tool_role_without_preceding_assistant_rejected(self) -> None:
        """孤立的 tool_result（无前置 assistant tool_call）应被拒绝。"""
        messages = [
            {"role": "user", "content": "Hello"},
            {
                "role": "tool",
                "tool_call_id": "call_orphan_999",
                "content": "Some result",
            },
        ]

        with pytest.raises(ValidationError, match="call_orphan_999"):
            MessageValidator.validate(messages)

    def test_multiple_tool_calls_all_matched(self) -> None:
        """多个 tool_call 全部有效匹配时应通过验证。"""
        messages = [
            {"role": "user", "content": "Weather and time?"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_001",
                        "type": "function",
                        "function": {
                            "name": "get_weather",
                            "arguments": '{"city": "Tokyo"}',
                        },
                    },
                    {
                        "id": "call_002",
                        "type": "function",
                        "function": {
                            "name": "get_time",
                            "arguments": '{"timezone": "UTC"}',
                        },
                    },
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_001",
                "content": "Sunny",
            },
            {
                "role": "tool",
                "tool_call_id": "call_002",
                "content": "14:30 UTC",
            },
        ]

        # 不应抛出异常
        MessageValidator.validate(messages)

    def test_multiple_tool_calls_one_orphan_mentioned_in_error(self) -> None:
        """多个 tool_call 中有一个孤立时，错误消息应包含具体的 tool_call_id。"""
        messages = [
            {"role": "user", "content": "Weather and time?"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_001",
                        "type": "function",
                        "function": {
                            "name": "get_weather",
                            "arguments": '{"city": "Tokyo"}',
                        },
                    },
                    {
                        "id": "call_orphan_002",
                        "type": "function",
                        "function": {
                            "name": "get_time",
                            "arguments": '{"timezone": "UTC"}',
                        },
                    },
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_001",
                "content": "Sunny",
            },
            # call_orphan_002 缺少对应的 tool 消息
        ]

        with pytest.raises(ValidationError, match="call_orphan_002"):
            MessageValidator.validate(messages)
