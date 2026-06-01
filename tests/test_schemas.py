"""Tests for event pydantic schemas."""

import json

import pytest
from pydantic import TypeAdapter

from loopai.events.schemas import (
    BudgetExhausted,
    BudgetWarning,
    CheckpointSaved,
    CircuitClosed,
    CircuitOpened,
    ConfirmationRequired,
    ConfirmationResponse,
    ContextCompacted,
    Error,
    EscalationRequired,
    Event,
    FailureRegistered,
    LLMContentDone,
    LLMToken,
    LoopDetected,
    SessionEnd,
    StepEnd,
    StepStart,
    TokenWarning,
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

    def test_context_compacted_in_union(self):
        event = ContextCompacted(
            session_id="s1",
            step_num=5,
            tokens_before=12000,
            tokens_after=6000,
            tokens_saved=6000,
            rounds_preserved=3,
            summary_message_count=10,
        )
        data = event.model_dump()
        ta = TypeAdapter(Event)
        parsed = ta.validate_python(data)
        assert isinstance(parsed, ContextCompacted)
        assert parsed.step_num == 5
        assert parsed.tokens_saved == 6000


class TestAllEventsUniqueType:
    """Verify all 22 event_type values are unique."""

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
            ConfirmationRequired,
            ConfirmationResponse,
            ContextCompacted,
            TokenWarning,
            CheckpointSaved,
            CircuitOpened,
            CircuitClosed,
            FailureRegistered,
            EscalationRequired,
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
            if cls is ConfirmationRequired:
                kwargs["confirmation_id"] = "c1"
                kwargs["tool_name"] = "test"
                kwargs["tool_args"] = {}
                kwargs["permission_level"] = "dangerous"
                kwargs["reason"] = "test"
            if cls is ConfirmationResponse:
                kwargs["confirmation_id"] = "c1"
                kwargs["approved"] = True
            if cls is ContextCompacted:
                kwargs["tokens_before"] = 10000
                kwargs["tokens_after"] = 5000
                kwargs["tokens_saved"] = 5000
                kwargs["rounds_preserved"] = 3
                kwargs["summary_message_count"] = 10
            if cls is TokenWarning:
                kwargs["token_count"] = 96000
                kwargs["max_tokens"] = 128000
                kwargs["used_pct"] = 0.75
                kwargs["action"] = "compress"
            if cls is CheckpointSaved:
                del kwargs["step_num"]
                kwargs["step_count"] = 1
                kwargs["file_path"] = "/tmp/test.ckpt.jsonl"
                kwargs["state"] = "reason"
            if cls is CircuitOpened:
                del kwargs["step_num"]
                kwargs["tool_name"] = "test"
                kwargs["failure_rate"] = 0.6
                kwargs["window_size"] = 10
                kwargs["previous_state"] = "closed"
                kwargs["new_state"] = "open"
            if cls is CircuitClosed:
                del kwargs["step_num"]
                kwargs["tool_name"] = "test"
                kwargs["previous_state"] = "half_open"
                kwargs["new_state"] = "closed"
            if cls is FailureRegistered:
                del kwargs["step_num"]
                kwargs["tool_name"] = "test"
                kwargs["signature"] = "abc123def4567890"
                kwargs["error_message"] = "test error"
            if cls is EscalationRequired:
                del kwargs["step_num"]
                kwargs["tool_name"] = "test"
                kwargs["layer"] = 4
                kwargs["attempt_count"] = 5
                kwargs["error_message"] = "max retries exceeded"

            event = cls(**kwargs)
            event_types.add(event.event_type)

        assert len(event_types) == 22, f"Expected 22 unique event types, got {len(event_types)}: {event_types}"


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
            ContextCompacted(
                session_id="sess-1",
                step_num=5,
                tokens_before=12000,
                tokens_after=6000,
                tokens_saved=6000,
                rounds_preserved=3,
                summary_message_count=10,
            ),
            TokenWarning(
                session_id="sess-1",
                step_num=3,
                token_count=96000,
                max_tokens=128000,
                used_pct=0.75,
                action="compress",
            ),
        ]

        for event in events:
            json_str = event.model_dump_json()
            parsed = json.loads(json_str)
            assert isinstance(parsed, dict)
            assert parsed["event_type"] == event.event_type


class TestConfirmationRequiredCreation:
    """Verify ConfirmationRequired construction and field values."""

    def test_confirmation_required_creation(self):
        event = ConfirmationRequired(
            session_id="s1",
            step_num=3,
            confirmation_id="c1",
            tool_name="rm",
            tool_args={"path": "/tmp/x"},
            permission_level="dangerous",
            reason="命中黑名单",
        )
        assert event.event_type == "confirmation_required"
        assert event.session_id == "s1"
        assert event.step_num == 3
        assert event.confirmation_id == "c1"
        assert event.tool_name == "rm"
        assert event.tool_args == {"path": "/tmp/x"}
        assert event.permission_level == "dangerous"
        assert event.reason == "命中黑名单"

    def test_confirmation_required_default_event_type(self):
        event = ConfirmationRequired(
            session_id="s1",
            step_num=1,
            confirmation_id="c1",
            tool_name="bash",
            tool_args={},
            permission_level="dangerous",
            reason="test",
        )
        assert event.event_type == "confirmation_required"


class TestConfirmationResponseCreation:
    """Verify ConfirmationResponse construction and field values."""

    def test_confirmation_response_approved_true(self):
        event = ConfirmationResponse(
            session_id="s1",
            step_num=3,
            confirmation_id="c1",
            approved=True,
        )
        assert event.event_type == "confirmation_response"
        assert event.session_id == "s1"
        assert event.step_num == 3
        assert event.confirmation_id == "c1"
        assert event.approved is True

    def test_confirmation_response_approved_false(self):
        event = ConfirmationResponse(
            session_id="s1",
            step_num=3,
            confirmation_id="c1",
            approved=False,
        )
        assert event.approved is False

    def test_confirmation_response_default_event_type(self):
        event = ConfirmationResponse(
            session_id="s1",
            step_num=1,
            confirmation_id="c1",
            approved=True,
        )
        assert event.event_type == "confirmation_response"


class TestContextCompactedCreation:
    """Verify ContextCompacted construction and round-trip."""

    def test_context_compacted_creation(self):
        event = ContextCompacted(
            session_id="s1",
            step_num=5,
            tokens_before=12000,
            tokens_after=6000,
            tokens_saved=6000,
            rounds_preserved=3,
            summary_message_count=10,
        )
        assert event.event_type == "context_compacted"
        assert event.session_id == "s1"
        assert event.step_num == 5
        assert event.tokens_before == 12000
        assert event.tokens_after == 6000
        assert event.tokens_saved == 6000
        assert event.rounds_preserved == 3
        assert event.summary_message_count == 10
        assert isinstance(event.timestamp, str)
        assert "T" in event.timestamp

    def test_context_compacted_round_trip(self):
        event = ContextCompacted(
            session_id="s2",
            step_num=10,
            tokens_before=20000,
            tokens_after=8000,
            tokens_saved=12000,
            rounds_preserved=5,
            summary_message_count=15,
        )
        data = event.model_dump()
        ta = TypeAdapter(Event)
        parsed = ta.validate_python(data)
        assert isinstance(parsed, ContextCompacted)
        assert parsed.tokens_before == 20000
        assert parsed.tokens_saved == 12000
        assert parsed.rounds_preserved == 5


class TestTokenWarningCreation:
    """Verify TokenWarning construction and round-trip."""

    def test_token_warning_creation(self):
        event = TokenWarning(
            session_id="s1",
            step_num=3,
            token_count=96000,
            max_tokens=128000,
            used_pct=0.75,
            action="compress",
        )
        assert event.event_type == "token_warning"
        assert event.session_id == "s1"
        assert event.step_num == 3
        assert event.token_count == 96000
        assert event.max_tokens == 128000
        assert event.used_pct == 0.75
        assert event.action == "compress"
        assert isinstance(event.timestamp, str)

    def test_token_warning_round_trip(self):
        event = TokenWarning(
            session_id="s2",
            step_num=7,
            token_count=50000,
            max_tokens=100000,
            used_pct=0.50,
            action="ok",
        )
        data = event.model_dump()
        ta = TypeAdapter(Event)
        parsed = ta.validate_python(data)
        assert isinstance(parsed, TokenWarning)
        assert parsed.token_count == 50000
        assert parsed.max_tokens == 100000
        assert parsed.action == "ok"


class TestNewEventsDiscriminatedUnion:
    """Verify new events can be deserialized via the Event TypeAdapter."""

    def test_confirmation_required_via_union(self):
        event = ConfirmationRequired(
            session_id="s1",
            step_num=3,
            confirmation_id="c1",
            tool_name="rm",
            tool_args={},
            permission_level="dangerous",
            reason="命中黑名单",
        )
        data = event.model_dump()
        ta = TypeAdapter(Event)
        parsed = ta.validate_python(data)
        assert isinstance(parsed, ConfirmationRequired)
        assert parsed.confirmation_id == "c1"

    def test_confirmation_response_via_union(self):
        event = ConfirmationResponse(
            session_id="s1",
            step_num=3,
            confirmation_id="c1",
            approved=True,
        )
        data = event.model_dump()
        ta = TypeAdapter(Event)
        parsed = ta.validate_python(data)
        assert isinstance(parsed, ConfirmationResponse)
        assert parsed.approved is True


class TestUpdatedEventTypeCount:
    """Verify all event_type values are unique (now 22 events)."""

    def test_all_events_have_unique_type_22(self):
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
            ConfirmationRequired,
            ConfirmationResponse,
            ContextCompacted,
            TokenWarning,
            CheckpointSaved,
            CircuitOpened,
            CircuitClosed,
            FailureRegistered,
            EscalationRequired,
        ]
        event_types = set()
        for cls in event_classes:
            kwargs = {"session_id": "sess-1", "step_num": 1}
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
            if cls is ConfirmationRequired:
                kwargs["confirmation_id"] = "c1"
                kwargs["tool_name"] = "test"
                kwargs["tool_args"] = {}
                kwargs["permission_level"] = "dangerous"
                kwargs["reason"] = "test"
            if cls is ConfirmationResponse:
                kwargs["confirmation_id"] = "c1"
                kwargs["approved"] = True
            if cls is ContextCompacted:
                kwargs["tokens_before"] = 10000
                kwargs["tokens_after"] = 5000
                kwargs["tokens_saved"] = 5000
                kwargs["rounds_preserved"] = 3
                kwargs["summary_message_count"] = 10
            if cls is TokenWarning:
                kwargs["token_count"] = 96000
                kwargs["max_tokens"] = 128000
                kwargs["used_pct"] = 0.75
                kwargs["action"] = "compress"
            if cls is CheckpointSaved:
                del kwargs["step_num"]
                kwargs["step_count"] = 1
                kwargs["file_path"] = "/tmp/test.ckpt.jsonl"
                kwargs["state"] = "reason"
            if cls is CircuitOpened:
                del kwargs["step_num"]
                kwargs["tool_name"] = "test"
                kwargs["failure_rate"] = 0.6
                kwargs["window_size"] = 10
                kwargs["previous_state"] = "closed"
                kwargs["new_state"] = "open"
            if cls is CircuitClosed:
                del kwargs["step_num"]
                kwargs["tool_name"] = "test"
                kwargs["previous_state"] = "half_open"
                kwargs["new_state"] = "closed"
            if cls is FailureRegistered:
                del kwargs["step_num"]
                kwargs["tool_name"] = "test"
                kwargs["signature"] = "abc123def4567890"
                kwargs["error_message"] = "test error"
            if cls is EscalationRequired:
                del kwargs["step_num"]
                kwargs["tool_name"] = "test"
                kwargs["layer"] = 4
                kwargs["attempt_count"] = 5
                kwargs["error_message"] = "max retries exceeded"

            event = cls(**kwargs)
            event_types.add(event.event_type)

        assert len(event_types) == 22, f"Expected 22 unique event types, got {len(event_types)}: {event_types}"
