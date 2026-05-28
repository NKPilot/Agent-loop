"""Tests for LLMClient — standard OpenAI streaming API integration with EventBus.

Covers: client configuration, text response events, tool call events,
stream return value, error handling, edge cases.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import SecretStr

from loopai.config import AgentConfig
from loopai.events.bus import EventBus


@pytest.fixture
def config():
    """Return a test AgentConfig with a fake API key."""
    return AgentConfig(
        api_key=SecretStr("test-key"),
        base_url="https://api.openai.com/v1",
        model="gpt-4o",
        max_steps=15,
    )


@pytest.fixture
def bus():
    """Return a fresh EventBus for each test."""
    return EventBus()


# ── Mock helpers ──────────────────────────────────────────────────────


def _make_text_chunks():
    """Create mock chunks simulating a text-only LLM response (stream=True)."""
    c1 = MagicMock()
    c1.choices = []
    c1.choices.append(MagicMock())
    c1.choices[0].delta = MagicMock()
    c1.choices[0].delta.content = "Hello"
    c1.choices[0].delta.tool_calls = None

    c2 = MagicMock()
    c2.choices = []
    c2.choices.append(MagicMock())
    c2.choices[0].delta = MagicMock()
    c2.choices[0].delta.content = " world"
    c2.choices[0].delta.tool_calls = None

    return [c1, c2]


def _make_tool_call_chunks():
    """Create mock chunks simulating a single tool call response."""
    chunks = []

    # Chunk 1: tool call name + first args
    tc_delta = MagicMock()
    tc_delta.index = 0
    tc_delta.id = "call_test123"
    tc_delta.function = MagicMock()
    tc_delta.function.name = "get_weather"
    tc_delta.function.arguments = '{"location":'

    c1 = MagicMock()
    c1.choices = [MagicMock()]
    c1.choices[0].delta = MagicMock()
    c1.choices[0].delta.content = None
    c1.choices[0].delta.tool_calls = [tc_delta]
    chunks.append(c1)

    # Chunk 2: more args
    tc_delta2 = MagicMock()
    tc_delta2.index = 0
    tc_delta2.id = None
    tc_delta2.function = MagicMock()
    tc_delta2.function.name = None
    tc_delta2.function.arguments = '"London"}'

    c2 = MagicMock()
    c2.choices = [MagicMock()]
    c2.choices[0].delta = MagicMock()
    c2.choices[0].delta.content = None
    c2.choices[0].delta.tool_calls = [tc_delta2]
    chunks.append(c2)

    return chunks


def _make_multi_tool_call_chunks():
    """Create mock chunks simulating two tool calls in one response."""
    chunks = []

    # First chunk: both tool calls get their ids and names
    tc_a = MagicMock()
    tc_a.index = 0
    tc_a.id = "call_abc"
    tc_a.function = MagicMock()
    tc_a.function.name = "get_weather"
    tc_a.function.arguments = '{"city": "NYC"}'

    tc_b = MagicMock()
    tc_b.index = 1
    tc_b.id = "call_def"
    tc_b.function = MagicMock()
    tc_b.function.name = "get_time"
    tc_b.function.arguments = '{"timezone": "UTC"}'

    c1 = MagicMock()
    c1.choices = [MagicMock()]
    c1.choices[0].delta = MagicMock()
    c1.choices[0].delta.content = None
    c1.choices[0].delta.tool_calls = [tc_a, tc_b]
    chunks.append(c1)

    return chunks


def _make_empty_chunks():
    """Create mock chunk with simple text response."""
    c1 = MagicMock()
    c1.choices = [MagicMock()]
    c1.choices[0].delta = MagicMock()
    c1.choices[0].delta.content = "OK"
    c1.choices[0].delta.tool_calls = None
    return [c1]


# ── Async iterable mock for stream ────────────────────────────────────


class _AsyncChunkIter:
    """Async iterable that yields mock chunks."""

    def __init__(self, chunks):
        self._chunks = list(chunks)
        self._idx = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._idx >= len(self._chunks):
            raise StopAsyncIteration
        chunk = self._chunks[self._idx]
        self._idx += 1
        return chunk


# ── Test cases ─────────────────────────────────────────────────────────


class TestLLMClient:
    """Test suite for LLMClient."""

    @pytest.mark.asyncio
    async def test_client_configuration(self, config, bus):
        """Verify AsyncOpenAI is created with the correct parameters."""
        with patch("loopai.llm.client.AsyncOpenAI") as mock_cls:
            from loopai.llm.client import LLMClient

            client = LLMClient(config=config, bus=bus)
            mock_cls.assert_called_once_with(
                api_key="test-key",
                base_url="https://api.openai.com/v1",
            )
            assert client.model == "gpt-4o"

    @pytest.mark.asyncio
    async def test_text_response_publishes_events(self, config, bus):
        """Verify a text-only response publishes LLMToken and LLMContentDone."""
        chunks = _make_text_chunks()
        mock_stream = _AsyncChunkIter(chunks)

        llm_token_q = await bus.subscribe("llm_token")
        llm_done_q = await bus.subscribe("llm_content_done")

        from loopai.llm.client import LLMClient

        with patch("loopai.llm.client.AsyncOpenAI") as mock_cls:
            mock_instance = MagicMock()
            mock_instance.chat.completions.create = AsyncMock(return_value=mock_stream)
            mock_cls.return_value = mock_instance

            client = LLMClient(config=config, bus=bus)
            result = await client.complete(
                messages=[{"role": "user", "content": "Hello"}],
                session_id="test-session",
                step_num=1,
            )

        # Check LLMToken events
        tokens = []
        while not llm_token_q.empty():
            tokens.append(llm_token_q.get_nowait())
        assert len(tokens) == 2
        assert tokens[0]["content_delta"] == "Hello"
        assert tokens[1]["content_delta"] == " world"

        # Check LLMContentDone
        done = llm_done_q.get_nowait()
        assert done["full_content"] == "Hello world"

        # Check return
        assert result["content"] == "Hello world"
        assert result["role"] == "assistant"
        assert result["tool_calls"] == []

    @pytest.mark.asyncio
    async def test_tool_call_response_publishes_events(self, config, bus):
        """Verify tool call streaming publishes ToolCallStart events."""
        chunks = _make_tool_call_chunks()
        mock_stream = _AsyncChunkIter(chunks)

        tool_start_q = await bus.subscribe("tool_call_start")

        from loopai.llm.client import LLMClient

        with patch("loopai.llm.client.AsyncOpenAI") as mock_cls:
            mock_instance = MagicMock()
            mock_instance.chat.completions.create = AsyncMock(return_value=mock_stream)
            mock_cls.return_value = mock_instance

            client = LLMClient(config=config, bus=bus)
            result = await client.complete(
                messages=[{"role": "user", "content": "Weather?"}],
                session_id="test-session",
                step_num=2,
            )

        # ToolCallStart
        starts = []
        while not tool_start_q.empty():
            starts.append(tool_start_q.get_nowait())
        assert len(starts) == 1
        assert starts[0]["tool_name"] == "get_weather"
        assert starts[0]["tool_call_id"] == "call_test123"
        assert starts[0]["step_num"] == 2

        # Return value
        assert len(result["tool_calls"]) == 1
        assert result["tool_calls"][0]["name"] == "get_weather"

    @pytest.mark.asyncio
    async def test_stream_completion_returns_message(self, config, bus):
        """Verify complete() returns a properly structured dict."""
        chunks = _make_text_chunks()
        mock_stream = _AsyncChunkIter(chunks)

        from loopai.llm.client import LLMClient

        with patch("loopai.llm.client.AsyncOpenAI") as mock_cls:
            mock_instance = MagicMock()
            mock_instance.chat.completions.create = AsyncMock(return_value=mock_stream)
            mock_cls.return_value = mock_instance

            client = LLMClient(config=config, bus=bus)
            result = await client.complete(
                messages=[{"role": "user", "content": "Hello"}],
                session_id="s1",
                step_num=1,
            )

        assert isinstance(result, dict)
        assert "content" in result
        assert "tool_calls" in result
        assert "role" in result
        assert result["role"] == "assistant"

    @pytest.mark.asyncio
    async def test_error_during_stream_publishes_error(self, config, bus):
        """Verify exceptions during streaming publish Error events."""
        # Create a mock stream that raises on first iteration
        class _RaisingStream:
            def __aiter__(self):
                return self

            async def __anext__(self):
                raise RuntimeError("API connection failed")

        mock_stream = _RaisingStream()
        error_q = await bus.subscribe("error")

        from loopai.llm.client import LLMClient

        with patch("loopai.llm.client.AsyncOpenAI") as mock_cls:
            mock_instance = MagicMock()
            mock_instance.chat.completions.create = AsyncMock(return_value=mock_stream)
            mock_cls.return_value = mock_instance

            client = LLMClient(config=config, bus=bus)
            with pytest.raises(RuntimeError, match="API connection failed"):
                await client.complete(
                    messages=[{"role": "user", "content": "Hello"}],
                    session_id="s1",
                    step_num=1,
                )

        error_events = []
        while not error_q.empty():
            error_events.append(error_q.get_nowait())
        assert len(error_events) >= 1
        assert error_events[0]["error_type"] == "RuntimeError"

    @pytest.mark.asyncio
    async def test_no_tool_calls_empty_list(self, config, bus):
        """Verify no tool_calls returns empty list."""
        chunks = _make_empty_chunks()
        mock_stream = _AsyncChunkIter(chunks)

        from loopai.llm.client import LLMClient

        with patch("loopai.llm.client.AsyncOpenAI") as mock_cls:
            mock_instance = MagicMock()
            mock_instance.chat.completions.create = AsyncMock(return_value=mock_stream)
            mock_cls.return_value = mock_instance

            client = LLMClient(config=config, bus=bus)
            result = await client.complete(
                messages=[{"role": "user", "content": "Is it working?"}],
                session_id="s1",
                step_num=1,
            )

        assert result["tool_calls"] == []
        assert result["content"] == "OK"
        assert result["role"] == "assistant"

    @pytest.mark.asyncio
    async def test_multiple_tool_calls_in_one_response(self, config, bus):
        """Verify multiple tool calls get independent events."""
        chunks = _make_multi_tool_call_chunks()
        mock_stream = _AsyncChunkIter(chunks)

        tool_start_q = await bus.subscribe("tool_call_start")

        from loopai.llm.client import LLMClient

        with patch("loopai.llm.client.AsyncOpenAI") as mock_cls:
            mock_instance = MagicMock()
            mock_instance.chat.completions.create = AsyncMock(return_value=mock_stream)
            mock_cls.return_value = mock_instance

            client = LLMClient(config=config, bus=bus)
            result = await client.complete(
                messages=[{"role": "user", "content": "Weather and time?"}],
                session_id="test-session",
                step_num=1,
            )

        starts = []
        while not tool_start_q.empty():
            starts.append(tool_start_q.get_nowait())
        assert len(starts) == 2
        names = [s["tool_name"] for s in starts]
        assert "get_weather" in names
        assert "get_time" in names

        assert len(result["tool_calls"]) == 2
