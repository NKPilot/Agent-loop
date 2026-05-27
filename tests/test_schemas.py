"""Tests for event pydantic schemas."""

import json

import pytest
from pydantic import TypeAdapter

from loopai.events.schemas import (
    BudgetExhausted,
    BudgetWarning,
    Error,
    Event,
    LLMContentDone,
    LLMToken,
    LoopDetected,
    SessionEnd,
    StepEnd,
    StepStart,
    ToolCallArgs,
    ToolCallDone,
    ToolCallStart,
    ToolResult,
)


class TestStepStartCreation:
    """Verify StepStart construction and field values."""

    def test_step_start_creation(self):
        event = StepStart(session_id="sess-1", step_num=1)
        assert event.event_type == "step_start"
        assert event.session_id == "sess-1"
        assert event.step_num == 1
        # timestamp should be an ISO 8601 string
        assert isinstance(event.timestamp, str)
        assert "T" in event.timestamp


class TestLLMTokenCreation:
    """Verify LLMToken construction."""

    def test_llm_token_creation(self):
        event = LLMToken(session_id="sess-1", step_num=1, content_delta="Hello")
        assert event.event_type == "llm_token"
        assert event.content_delta == "Hello"


class TestToolCallDoneFullArgs:
    """Verify ToolCallDone accepts dict and serializes correctly."""

    def test_tool_call_done_full_args_type(self):
        args = {"city": "Tokyo", "units": "metric"}
        event = ToolCallDone(
            session_id="sess-1",
            step_num=1,
            tool_name="get_weather",
            tool_call_id="call_123",
            full_args=args,
        )
        dumped = event.model_dump()
        assert dumped["full_args"] == args
        # Verify JSON serialization works
        json_str = event.model_dump_json()
        parsed = json.loads(json_str)
        assert parsed["full_args"] == args


class TestEventDiscriminatedUnion:
    """Verify discriminated union deserialization via TypeAdapter."""

    def test_event_discriminated_union(self):
        start = StepStart(session_id="sess-1", step_num=1)
        data = start.model_dump()
        ta = TypeAdapter(Event)
        parsed = ta.validate_python(data)
        assert isinstance(parsed, StepStart)
        assert parsed.event_type == "step_start"
        assert parsed.session_id == "sess-1"


class TestAllEventsUniqueType:
    """Verify all 13 event_type values are unique."""

    def test_all_events_have_unique_type(self):
        event_classes = [
            StepStart,
            StepEnd,
            SessionEnd,
            LLMToken,
            LLMContentDone,
            ToolCallStart,
            ToolCallArgs,
            ToolCallDone,
            ToolResult,
            BudgetWarning,
            BudgetExhausted,
            LoopDetected,
            Error,
        ]
        # Instantiate each with minimal required fields to get event_type
        event_types = set()
        for cls in event_classes:
            kwargs = {"session_id": "sess-1", "step_num": 1}
            # Add fields specific to each class
            if cls is StepEnd:
                kwargs["state_transition"] = "REASON->FINISH"
            if cls is SessionEnd:
                kwargs["final_state"] = "FINISH"
                kwargs["total_steps"] = 1
                kwargs["exit_reason"] = "completed"
            if cls is LLMToken:
                kwargs["content_delta"] = "x"
            if cls is LLMContentDone:
                kwargs["full_content"] = "done"
            if cls is ToolCallStart:
                kwargs["tool_name"] = "test"
                kwargs["tool_call_id"] = "c1"
            if cls is ToolCallArgs:
                kwargs["tool_name"] = "test"
                kwargs["args_delta"] = '{"x":'
            if cls is ToolCallDone:
                kwargs["tool_name"] = "test"
                kwargs["tool_call_id"] = "c1"
                kwargs["full_args"] = {}
            if cls is ToolResult:
                kwargs["tool_name"] = "test"
                kwargs["tool_call_id"] = "c1"
                kwargs["result"] = "ok"
                kwargs["duration_ms"] = 1.0
            if cls is BudgetWarning:
                kwargs["used_pct"] = 80.0
                kwargs["max_steps"] = 15
            if cls is LoopDetected:
                kwargs["tool_name"] = "test"
                kwargs["consecutive_count"] = 3
            if cls is Error:
                kwargs["error_type"] = "RuntimeError"
                kwargs["message"] = "test error"

            event = cls(**kwargs)
            event_types.add(event.event_type)

        assert len(event_types) == 13, f"Expected 13 unique event types, got {len(event_types)}: {event_types}"


class TestJsonSerialization:
    """Verify all event types produce valid JSON."""

    def test_json_serialization(self):
        events = [
            StepStart(session_id="sess-1", step_num=1),
            StepEnd(session_id="sess-1", step_num=1, state_transition="REASON->ACT"),
            SessionEnd(
                session_id="sess-1",
                final_state="FINISH",
                total_steps=5,
                exit_reason="completed",
            ),
            LLMToken(session_id="sess-1", step_num=1, content_delta="Hello"),
            LLMContentDone(session_id="sess-1", step_num=1, full_content="Hello World"),
            ToolCallStart(
                session_id="sess-1", step_num=1, tool_name="bash", tool_call_id="c1"
            ),
            ToolCallArgs(
                session_id="sess-1", step_num=1, tool_name="bash", args_delta='{"cmd'
            ),
            ToolCallDone(
                session_id="sess-1",
                step_num=1,
                tool_name="bash",
                tool_call_id="c1",
                full_args={"cmd": "ls"},
            ),
            ToolResult(
                session_id="sess-1",
                step_num=1,
                tool_name="bash",
                tool_call_id="c1",
                result="file1.txt",
                duration_ms=150.0,
            ),
            BudgetWarning(session_id="sess-1", step_num=1, used_pct=80.0, max_steps=15),
            BudgetExhausted(session_id="sess-1", step_num=1),
            LoopDetected(
                session_id="sess-1", step_num=1, tool_name="bash", consecutive_count=3
            ),
            Error(
                session_id="sess-1",
                step_num=1,
                error_type="ValueError",
                message="test error",
            ),
        ]

        for event in events:
            json_str = event.model_dump_json()
            parsed = json.loads(json_str)
            assert isinstance(parsed, dict)
            assert parsed["event_type"] == event.event_type
