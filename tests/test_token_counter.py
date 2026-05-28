"""Tests for loopai.context.token_counter module.

Covers TokenCounter count_text, count_message, count_messages,
and TokenizerProtocol conformance.
"""

import pytest

from loopai.context.token_counter import TokenCounter, TokenizerProtocol


class TestCountText:
    """Verify count_text handles different text types."""

    def test_count_text_ascii(self):
        """Pure ASCII text returns a positive token count."""
        counter = TokenCounter()
        text = "Hello, world!"
        count = counter.count_text(text)
        assert isinstance(count, int)
        assert count > 0
        # "Hello, world!" is typically 4 tokens in cl100k_base
        assert count == 4

    def test_count_text_chinese(self):
        """Mixed Chinese and English text is counted correctly."""
        counter = TokenCounter()
        text = "你好，世界！Hello"
        count = counter.count_text(text)
        assert isinstance(count, int)
        assert count > 0
        # Chinese characters typically take more tokens than ASCII
        # The exact number depends on tiktoken but must be positive


class TestCountMessage:
    """Verify count_message handles various message formats."""

    def test_count_message_with_content(self):
        """A user message with content is counted correctly."""
        counter = TokenCounter()
        message = {"role": "user", "content": "Hello, world!"}
        count = counter.count_message(message)
        assert isinstance(count, int)
        assert count > 0
        # 3 base + 4 content = 7 tokens
        assert count == 7

    def test_count_message_with_tool_calls(self):
        """An assistant message with tool_calls is counted correctly."""
        counter = TokenCounter()
        message = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "arguments": '{"city": "Tokyo"}',
                    },
                }
            ],
        }
        count = counter.count_message(message)
        assert isinstance(count, int)
        assert count > 0
        # 3 base + 3 tool_calls base + count_text("get_weather{"city": "Tokyo"}") = 3 + 3 + 9 = 15
        assert count == 15

    def test_count_message_tool_calls_as_object(self):
        """tool_calls where function is a top-level dict (some API formats)."""
        counter = TokenCounter()
        message = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"name": "bash", "arguments": "ls -la"},
            ],
        }
        count = counter.count_message(message)
        assert isinstance(count, int)
        assert count > 0


class TestCountMessages:
    """Verify count_messages aggregates across multiple messages."""

    def test_count_messages_full_list(self):
        """A list of 3 messages (user + assistant + tool) returns correct aggregate."""
        counter = TokenCounter()
        messages = [
            {"role": "user", "content": "What is the weather in Tokyo?"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "get_weather",
                            "arguments": '{"city": "Tokyo"}',
                        },
                    }
                ],
            },
            {"role": "tool", "content": '{"temp": 22, "condition": "sunny"}', "tool_call_id": "call_1"},
        ]
        count = counter.count_messages(messages)
        assert isinstance(count, int)
        assert count > 0

        # Individual counts:
        # msg1: 3 base + count_text("What is the weather in Tokyo?") = 3 + 7 = 10
        # msg2: 3 base + 3 tool_calls base + count_text("get_weather{"city": "Tokyo"}") = 3 + 3 + 9 = 15
        # msg3: 3 base + count_text('{"temp": 22, "condition": "sunny"}') = 3 + 13 = 16
        # Sum: 10 + 15 + 16 = 41
        # Final +3 glue: 44
        assert count == 44


class TestTokenizerProtocol:
    """Verify TokenCounter conforms to TokenizerProtocol."""

    def test_token_counter_protocol(self):
        """TokenCounter is an instance of TokenizerProtocol."""
        counter = TokenCounter()
        assert isinstance(counter, TokenizerProtocol)
        assert hasattr(counter, "count_text")
        assert hasattr(counter, "count_message")
        assert hasattr(counter, "count_messages")
