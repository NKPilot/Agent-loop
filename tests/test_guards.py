"""守卫测试 —— LoopDetector、MessageValidator、BudgetGuard。"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from loopai.state_machine.guards import (
    BudgetGuard,
    LoopDetector,
    MessageValidator,
    TokenGuard,
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

    def test_empty_message_list_passes(self) -> None:
        """空消息列表应通过验证。"""
        # 不应抛出异常
        MessageValidator.validate([])


class TestLoopDetectorEdgeCases:
    """LoopDetector 边界条件测试。"""

    def test_deque_used_instead_of_list(self) -> None:
        """确认使用 deque (maxlen) 而非 list。"""
        detector = LoopDetector(window_size=3)

        # 添加超过窗口大小的项
        for i in range(5):
            detector.check(f"tool_{i}", {"arg": i})

        # deque 自动丢弃旧项，_window 大小不超过 3
        assert len(detector._window) == 3

    def test_empty_args_gets_unique_signature(self) -> None:
        """空参数列表应产生有效签名。"""
        sig = LoopDetector._signature("empty_tool", {})
        assert len(sig) == 16
        assert all(c in "0123456789abcdef" for c in sig)


# =============================================================================
# BudgetGuard 测试 (测试 14-21)
# =============================================================================


class TestBudgetGuard:
    """BudgetGuard 步数预算测试 —— 6 个用例。"""

    def test_step_at_33_percent_no_warning(self) -> None:
        """步骤在 33% 预算时不触发警告。"""
        guard = BudgetGuard(max_steps=15, warn_pct=0.80)
        messages = [{"role": "user", "content": "Hello"}]

        should_continue, modified, action = guard.check(5, messages)

        assert should_continue is True
        assert action is None
        # 消息不应被修改（未注入任何系统消息）
        assert len(modified) == len(messages)

    def test_step_at_80_percent_warn_with_message(self) -> None:
        """步骤达到 80% 预算时触发警告并注入系统消息。"""
        guard = BudgetGuard(max_steps=15, warn_pct=0.80)
        messages = [{"role": "user", "content": "Hello"}]

        should_continue, modified, action = guard.check(12, messages)

        assert should_continue is True
        assert action == "warn"
        # 注入了警告消息
        assert len(modified) == len(messages) + 1
        assert modified[-1]["role"] == "system"
        assert "80%" in modified[-1]["content"] or "budget" in modified[-1]["content"].lower()

    def test_step_at_93_percent_still_warn(self) -> None:
        """步骤在 93% 预算时仍处于警告区域（未达到最终摘要）。"""
        guard = BudgetGuard(max_steps=15, warn_pct=0.80)
        messages = [{"role": "user", "content": "Hello"}]

        should_continue, modified, action = guard.check(14, messages)

        assert should_continue is True
        assert action == "warn"
        assert len(modified) == len(messages) + 1
        assert modified[-1]["role"] == "system"

    def test_step_equal_max_final_summary(self) -> None:
        """步骤恰好等于 max_steps 时触发最终摘要。"""
        guard = BudgetGuard(max_steps=15, warn_pct=0.80)
        messages = [{"role": "user", "content": "Hello"}]

        should_continue, modified, action = guard.check(15, messages)

        assert should_continue is True
        assert action == "final"
        # 注入了最终摘要提示
        assert len(modified) == len(messages) + 1
        assert modified[-1]["role"] == "system"
        assert "exhausted" in modified[-1]["content"].lower() or "final" in modified[-1]["content"].lower()

    def test_step_exceeds_max_final(self) -> None:
        """步骤超过 max_steps 时仍然触发最终摘要。"""
        guard = BudgetGuard(max_steps=15, warn_pct=0.80)
        messages = [{"role": "user", "content": "Hello"}]

        should_continue, modified, action = guard.check(16, messages)

        assert should_continue is True
        assert action == "final"
        assert len(modified) == len(messages) + 1

    def test_custom_warn_threshold(self) -> None:
        """自定义 warn_pct 阈值按预期工作。"""
        guard = BudgetGuard(max_steps=10, warn_pct=0.50)
        messages = [{"role": "user", "content": "Hello"}]

        # 在 50% 阈值以下不触发
        should_continue, modified, action = guard.check(4, messages)
        assert should_continue is True
        assert action is None

        # 在 50% 阈值触发警告
        should_continue, modified, action = guard.check(5, messages)
        assert should_continue is True
        assert action == "warn"
        assert len(modified) == len(messages) + 1

    def test_input_messages_not_mutated(self) -> None:
        """check() 不原地修改输入消息列表。"""
        guard = BudgetGuard(max_steps=15, warn_pct=0.80)
        messages = [{"role": "user", "content": "Hello"}]
        original_len = len(messages)

        _, modified, _ = guard.check(12, messages)

        # 输入列表未被修改
        assert len(messages) == original_len
        # 返回的是新列表
        assert modified is not messages
        assert len(modified) == original_len + 1


class TestBudgetGuardUnreachable:
    """BudgetGuard 不可达检测测试 —— 2 个用例。"""

    def test_unreachable_three_failures(self) -> None:
        """连续 3 次失败触发不可达信号。"""
        guard = BudgetGuard(max_steps=15)

        # 2 次失败不触发
        assert guard.check_unreachable(True) is None
        assert guard.check_unreachable(True) is None

        # 第 3 次失败触发
        assert guard.check_unreachable(True) == "unreachable"

    def test_unreachable_below_threshold(self) -> None:
        """连续失败少于 3 次不触发不可达信号。"""
        guard = BudgetGuard(max_steps=15)

        assert guard.check_unreachable(True) is None
        assert guard.check_unreachable(True) is None

        # 成功重置计数
        assert guard.check_unreachable(False) is None
        # 重新计数
        assert guard.check_unreachable(True) is None


# =============================================================================
# TokenGuard 测试
# =============================================================================


class TestTokenGuard:
    """TokenGuard Token 预算守卫测试 —— 3 个用例。"""

    def test_ok_below_threshold(self) -> None:
        """未达 75% 阈值时返回 ("ok", token_count, threshold_tokens)。"""
        counter = MagicMock()
        counter.count_messages.return_value = 50000
        guard = TokenGuard(counter, window_size=128000, threshold=0.75)

        action, token_count, threshold_tokens = guard.check([])

        assert action == "ok"
        assert token_count == 50000
        assert threshold_tokens == 96000

    def test_compress_at_threshold(self) -> None:
        """达到 75% 阈值时返回 ("compress", token_count, threshold_tokens)。"""
        counter = MagicMock()
        counter.count_messages.return_value = 96000  # 128000 * 0.75
        guard = TokenGuard(counter, window_size=128000, threshold=0.75)

        action, token_count, threshold_tokens = guard.check([])

        assert action == "compress"
        assert token_count == 96000
        assert threshold_tokens == 96000

    def test_compress_above_threshold(self) -> None:
        """超过 75% 阈值时返回 ("compress", token_count, threshold_tokens)。"""
        counter = MagicMock()
        counter.count_messages.return_value = 100000
        guard = TokenGuard(counter, window_size=128000, threshold=0.75)

        action, token_count, threshold_tokens = guard.check([])

        assert action == "compress"
        assert token_count == 100000
        assert threshold_tokens == 96000

    def test_different_window_size(self) -> None:
        """自定义 window_size 正常生效。"""
        counter = MagicMock()
        counter.count_messages.return_value = 40000
        guard = TokenGuard(counter, window_size=64000, threshold=0.50)

        action, token_count, threshold_tokens = guard.check([])

        assert action == "compress"  # 40000 >= 64000*0.5=32000
        assert token_count == 40000
        assert threshold_tokens == 32000

    def test_input_not_mutated(self) -> None:
        """check() 不修改原始消息列表。"""
        counter = MagicMock()
        counter.count_messages.return_value = 50000
        guard = TokenGuard(counter)

        messages = [{"role": "user", "content": "Hello"}]
        original_len = len(messages)

        guard.check(messages)

        assert len(messages) == original_len
