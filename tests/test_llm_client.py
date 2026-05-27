"""Tests for LLMClient — OpenAI beta streaming API integration with EventBus.

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


def _make_text_stream_events():
    """Create mock events simulating a text-only LLM response."""
    from openai.lib.streaming.chat._events import ContentDeltaEvent, ContentDoneEvent

    return [
        ContentDeltaEvent(type="content.delta", delta="Hello", snapshot="Hello", parsed=None),
        ContentDeltaEvent(
            type="content.delta", delta=" world", snapshot="Hello world", parsed=None
        ),
        ContentDoneEvent(type="content.done", content="Hello world", parsed=None),
    ]


def _make_tool_call_stream_events():
    """Create mock events simulating a single tool call response.

    Uses mix of real event types and MagicMock for ChunkEvent to avoid
    needing to construct full ChatCompletionChunk Pydantic models.
    """
    from openai.lib.streaming.chat._events import (
        FunctionToolCallArgumentsDeltaEvent,
        FunctionToolCallArgumentsDoneEvent,
        ContentDoneEvent,
    )

    # Mock ChunkEvent - we use MagicMock because constructing a real
    # ChatCompletionChunk with all required fields is impractical in tests.
    chunk_event = MagicMock()
    chunk_event.type = "chunk"
    # Simulate a chunk with one tool call having id="call_test123"
    mock_tool_call_delta = MagicMock()
    mock_tool_call_delta.index = 0
    mock_tool_call_delta.id = "call_test123"
    mock_tool_call_delta.function = MagicMock()
    mock_tool_call_delta.function.name = "get_weather"

    mock_choice = MagicMock()
    mock_choice.delta = MagicMock()
    mock_choice.delta.tool_calls = [mock_tool_call_delta]

    mock_chunk = MagicMock()
    mock_chunk.choices = [mock_choice]

    chunk_event.chunk = mock_chunk

    return [
        chunk_event,
        FunctionToolCallArgumentsDeltaEvent(
            type="tool_calls.function.arguments.delta",
            name="get_weather",
            index=0,
            arguments='{"location":',
            parsed_arguments={"location": ""},
            arguments_delta='{"location":',
        ),
        FunctionToolCallArgumentsDeltaEvent(
            type="tool_calls.function.arguments.delta",
            name="get_weather",
            index=0,
            arguments='{"location": "London"}',
            parsed_arguments={"location": "London"},
            arguments_delta='"London"}',
        ),
        FunctionToolCallArgumentsDoneEvent(
            type="tool_calls.function.arguments.done",
            name="get_weather",
            index=0,
            arguments='{"location": "London"}',
            parsed_arguments={"location": "London"},
        ),
        ContentDoneEvent(type="content.done", content="", parsed=None),
    ]


def _make_multi_tool_call_stream_events():
    """Create mock events simulating two tool calls in one response."""
    from openai.lib.streaming.chat._events import (
        FunctionToolCallArgumentsDeltaEvent,
        FunctionToolCallArgumentsDoneEvent,
    )

    # Mock ChunkEvent with two tool calls
    chunk_event = MagicMock()
    chunk_event.type = "chunk"

    tc0 = MagicMock()
    tc0.index = 0
    tc0.id = "call_abc"
    tc0.function = MagicMock()
    tc0.function.name = "get_weather"

    tc1 = MagicMock()
    tc1.index = 1
    tc1.id = "call_def"
    tc1.function = MagicMock()
    tc1.function.name = "get_time"

    mock_choice = MagicMock()
    mock_choice.delta = MagicMock()
    mock_choice.delta.tool_calls = [tc0, tc1]

    mock_chunk = MagicMock()
    mock_chunk.choices = [mock_choice]

    chunk_event.chunk = mock_chunk

    return [
        chunk_event,
        FunctionToolCallArgumentsDeltaEvent(
            type="tool_calls.function.arguments.delta",
            name="get_weather",
            index=0,
            arguments='{"city": "NYC"}',
            parsed_arguments={"city": "NYC"},
            arguments_delta='{"city": "NYC"}',
        ),
        FunctionToolCallArgumentsDoneEvent(
            type="tool_calls.function.arguments.done",
            name="get_weather",
            index=0,
            arguments='{"city": "NYC"}',
            parsed_arguments={"city": "NYC"},
        ),
        FunctionToolCallArgumentsDeltaEvent(
            type="tool_calls.function.arguments.delta",
            name="get_time",
            index=1,
            arguments='{"timezone": "UTC"}',
            parsed_arguments={"timezone": "UTC"},
            arguments_delta='{"timezone": "UTC"}',
        ),
        FunctionToolCallArgumentsDoneEvent(
            type="tool_calls.function.arguments.done",
            name="get_time",
            index=1,
            arguments='{"timezone": "UTC"}',
            parsed_arguments={"timezone": "UTC"},
        ),
    ]


def _make_empty_tool_calls_stream_events():
    """Create mock events with no tool calls (empty list)."""
    from openai.lib.streaming.chat._events import ContentDeltaEvent, ContentDoneEvent

    return [
        ContentDeltaEvent(
            type="content.delta", delta="OK", snapshot="OK", parsed=None
        ),
        ContentDoneEvent(type="content.done", content="OK", parsed=None),
    ]


# ── Helpers for creating a mock stream context manager ─────────────────


class _MockStream:
    """Async context manager mock that iterates over provided events.

    Implements the same protocol as AsyncChatCompletionStream from the
    OpenAI SDK, but returns configurable events and a controllable
    get_final_completion() result.
    """

    def __init__(self, events, final_completion=None):
        self._events = list(events)
        self._final_completion = final_completion
        self._iter = None

    async def __aenter__(self):
        self._iter = self._aiter()
        return self

    async def __aexit__(self, *args):
        pass

    def __aiter__(self):
        return self._aiter()

    async def _aiter(self):
        for event in self._events:
            yield event

    async def get_final_completion(self):
        return self._final_completion


def _build_final_completion(content=None, tool_calls=None):
    """Build a mock final completion object.

    Uses MagicMock to simulate ParsedChatCompletion without needing to
    construct the full Pydantic model with all required fields.
    """
    mock_message = MagicMock()
    mock_message.role = "assistant"
    mock_message.content = content
    mock_message.parsed = None

    mock_tool_calls = None
    if tool_calls:
        mock_tool_calls = []
        for tc in tool_calls:
            mtc = MagicMock()
            mtc.id = tc["id"]
            mtc.type = "function"
            mtc.function = MagicMock()
            mtc.function.name = tc["name"]
            mtc.function.arguments = json.dumps(tc["arguments"])
            mtc.function.parsed_arguments = tc["arguments"]
            mock_tool_calls.append(mtc)

    mock_message.tool_calls = mock_tool_calls

    mock_choice = MagicMock()
    mock_choice.index = 0
    mock_choice.message = mock_message

    mock_completion = MagicMock()
    mock_completion.id = "test-id"
    mock_completion.choices = [mock_choice]
    mock_completion.model = "gpt-4o"
    mock_completion.object = "chat.completion"

    return mock_completion


# ── Test cases ─────────────────────────────────────────────────────────


class TestLLMClient:
    """Test suite for LLMClient covering client setup, streaming events,
    return values, error handling, and edge cases."""

    # ── Test 1: Client configuration ──────────────────────────────────

    @pytest.mark.asyncio
    async def test_client_configuration(self, config, bus):
        """Verify AsyncOpenAI is created with the correct parameters from AgentConfig."""
        with patch("openai.AsyncOpenAI", autospec=True) as mock_client_cls:
            from loopai.llm.client import LLMClient

            client = LLMClient(config=config, bus=bus)
            mock_client_cls.assert_called_once_with(
                api_key="test-key",
                base_url="https://api.openai.com/v1",
            )
            assert client.model == "gpt-4o"

    # ── Test 2: Text response publishes LLMToken and LLMContentDone ───

    @pytest.mark.asyncio
    async def test_text_response_publishes_events(self, config, bus):
        """Verify that a text-only response publishes LLMToken and LLMContentDone."""
        events = _make_text_stream_events()
        mock_stream = _MockStream(
            events, _build_final_completion(content="Hello world")
        )

        llm_token_q = await bus.subscribe("llm_token")
        llm_done_q = await bus.subscribe("llm_content_done")

        from loopai.llm.client import LLMClient

        with patch("openai.AsyncOpenAI", autospec=True) as mock_cls:
            mock_instance = mock_cls.return_value
            mock_instance.beta.chat.completions.stream.return_value = mock_stream

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
        assert len(tokens) == 2, f"Expected 2 LLMToken events, got: {tokens}"
        assert tokens[0]["content_delta"] == "Hello"
        assert tokens[1]["content_delta"] == " world"

        # Check LLMContentDone event
        done = llm_done_q.get_nowait()
        assert done["full_content"] == "Hello world"
        assert done["step_num"] == 1

        # Check return value
        assert result["content"] == "Hello world"
        assert result["role"] == "assistant"
        assert result["tool_calls"] == []

    # ── Test 3: Tool call response publishes ToolCallStart/Args/Done ───

    @pytest.mark.asyncio
    async def test_tool_call_response_publishes_events(self, config, bus):
        """Verify tool call streaming publishes ToolCallStart, Args, and Done events."""
        events = _make_tool_call_stream_events()
        mock_stream = _MockStream(
            events,
            _build_final_completion(
                tool_calls=[
                    {
                        "id": "call_test123",
                        "name": "get_weather",
                        "arguments": {"location": "London"},
                    }
                ]
            ),
        )

        tool_start_q = await bus.subscribe("tool_call_start")
        tool_args_q = await bus.subscribe("tool_call_args")
        tool_done_q = await bus.subscribe("tool_call_done")

        from loopai.llm.client import LLMClient

        with patch("openai.AsyncOpenAI", autospec=True) as mock_cls:
            mock_instance = mock_cls.return_value
            mock_instance.beta.chat.completions.stream.return_value = mock_stream

            client = LLMClient(config=config, bus=bus)
            result = await client.complete(
                messages=[{"role": "user", "content": "What's the weather?"}],
                session_id="test-session",
                step_num=2,
            )

        # ToolCallStart
        start_events = []
        while not tool_start_q.empty():
            start_events.append(tool_start_q.get_nowait())
        assert len(start_events) == 1
        assert start_events[0]["tool_name"] == "get_weather"
        assert start_events[0]["tool_call_id"] == "call_test123"
        assert start_events[0]["step_num"] == 2

        # ToolCallArgs (deltas) - 2 argument deltas
        args_events = []
        while not tool_args_q.empty():
            args_events.append(tool_args_q.get_nowait())
        assert len(args_events) == 2
        assert args_events[0]["args_delta"] == '{"location":'
        assert args_events[1]["args_delta"] == '"London"}'

        # ToolCallDone
        done_events = []
        while not tool_done_q.empty():
            done_events.append(tool_done_q.get_nowait())
        assert len(done_events) == 1
        assert done_events[0]["tool_name"] == "get_weather"
        assert done_events[0]["full_args"] == {"location": "London"}

        # Return value
        assert result["content"] is None
        assert len(result["tool_calls"]) == 1
        assert result["tool_calls"][0]["name"] == "get_weather"
        assert result["tool_calls"][0]["arguments"] == {"location": "London"}

    # ── Test 4: Stream returns structured message ──────────────────────

    @pytest.mark.asyncio
    async def test_stream_completion_returns_message(self, config, bus):
        """Verify complete() returns a properly structured assistant message dict."""
        events = _make_text_stream_events()
        mock_stream = _MockStream(
            events, _build_final_completion(content="Hello world")
        )

        from loopai.llm.client import LLMClient

        with patch("openai.AsyncOpenAI", autospec=True) as mock_cls:
            mock_instance = mock_cls.return_value
            mock_instance.beta.chat.completions.stream.return_value = mock_stream

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
        assert result["content"] == "Hello world"
        assert isinstance(result["tool_calls"], list)

    # ── Test 5: Error during stream publishes Error event ──────────────

    @pytest.mark.asyncio
    async def test_error_during_stream_publishes_error(self, config, bus):
        """Verify that an exception during streaming publishes an Error event."""
        # Create a stream that raises after producing one event
        events = _make_empty_tool_calls_stream_events()
        mock_stream = _MockStream(
            events, _build_final_completion(content="OK")
        )

        # Override _aiter to raise after yielding events
        original_events = list(events)

        async def _raising_aiter(self):
            for ev in original_events:
                yield ev
            raise RuntimeError("API connection failed")

        mock_stream._aiter = _raising_aiter.__get__(mock_stream, mock_stream.__class__)

        error_q = await bus.subscribe("error")

        from loopai.llm.client import LLMClient

        with patch("openai.AsyncOpenAI", autospec=True) as mock_cls:
            mock_instance = mock_cls.return_value
            mock_instance.beta.chat.completions.stream.return_value = mock_stream

            client = LLMClient(config=config, bus=bus)
            with pytest.raises(RuntimeError, match="API connection failed"):
                await client.complete(
                    messages=[{"role": "user", "content": "Hello"}],
                    session_id="s1",
                    step_num=1,
                )

        # Check Error event was published
        error_events = []
        while not error_q.empty():
            error_events.append(error_q.get_nowait())
        assert len(error_events) >= 1
        error_event = error_events[0]
        assert error_event["event_type"] == "error"
        assert error_event["error_type"] == "RuntimeError"
        assert error_event["message"] == "API connection failed"

    # ── Test 6: No tool calls gracefully handled ───────────────────────

    @pytest.mark.asyncio
    async def test_no_tool_calls_empty_list(self, config, bus):
        """Verify that a response with no tool calls returns an empty tool_calls list."""
        events = _make_empty_tool_calls_stream_events()
        mock_stream = _MockStream(
            events, _build_final_completion(content="OK")
        )

        from loopai.llm.client import LLMClient

        with patch("openai.AsyncOpenAI", autospec=True) as mock_cls:
            mock_instance = mock_cls.return_value
            mock_instance.beta.chat.completions.stream.return_value = mock_stream

            client = LLMClient(config=config, bus=bus)
            result = await client.complete(
                messages=[{"role": "user", "content": "Is it working?"}],
                session_id="s1",
                step_num=1,
            )

        assert result["tool_calls"] == []
        assert result["content"] == "OK"
        assert result["role"] == "assistant"

    # ── Test 7: Multiple tool calls with correct indexing ──────────────

    @pytest.mark.asyncio
    async def test_multiple_tool_calls_in_one_response(self, config, bus):
        """Verify multiple tool calls in one response get independent events."""
        events = _make_multi_tool_call_stream_events()
        mock_stream = _MockStream(
            events,
            _build_final_completion(
                tool_calls=[
                    {
                        "id": "call_abc",
                        "name": "get_weather",
                        "arguments": {"city": "NYC"},
                    },
                    {
                        "id": "call_def",
                        "name": "get_time",
                        "arguments": {"timezone": "UTC"},
                    },
                ]
            ),
        )

        tool_start_q = await bus.subscribe("tool_call_start")
        tool_done_q = await bus.subscribe("tool_call_done")

        from loopai.llm.client import LLMClient

        with patch("openai.AsyncOpenAI", autospec=True) as mock_cls:
            mock_instance = mock_cls.return_value
            mock_instance.beta.chat.completions.stream.return_value = mock_stream

            client = LLMClient(config=config, bus=bus)
            result = await client.complete(
                messages=[{"role": "user", "content": "Weather and time?"}],
                session_id="test-session",
                step_num=1,
            )

        # Two ToolCallStart events
        starts = []
        while not tool_start_q.empty():
            starts.append(tool_start_q.get_nowait())
        assert len(starts) == 2, f"Expected 2 ToolCallStart, got: {starts}"
        names = [s["tool_name"] for s in starts]
        ids = [s["tool_call_id"] for s in starts]
        assert "get_weather" in names
        assert "get_time" in names
        assert "call_abc" in ids
        assert "call_def" in ids

        # Two ToolCallDone events
        dones = []
        while not tool_done_q.empty():
            dones.append(tool_done_q.get_nowait())
        assert len(dones) == 2
        args = {(d["tool_name"], tuple(sorted(d["full_args"].items()))) for d in dones}
        assert ("get_weather", (("city", "NYC"),)) in args
        assert ("get_time", (("timezone", "UTC"),)) in args

        # Return value
        assert len(result["tool_calls"]) == 2
        assert result["tool_calls"][0]["name"] == "get_weather"
        assert result["tool_calls"][1]["name"] == "get_time"
