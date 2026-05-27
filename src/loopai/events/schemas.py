"""Event schemas for the loopAI Event Bus.

Defines 13 pydantic models (1 base + 12 concrete) for all event types
in the ReAct agent loop. Uses discriminated unions for type-safe
deserialization and routing.
"""

from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, Field


class EventBase(BaseModel):
    """Base event with shared fields for all event types."""

    event_type: Literal[str]
    session_id: str
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# ── Top-level lifecycle events ──────────────────────────────────────


class StepStart(EventBase):
    """Emitted at the start of each agent loop step."""

    event_type: Literal["step_start"] = "step_start"
    step_num: int


class StepEnd(EventBase):
    """Emitted when a step completes, with state transition info."""

    event_type: Literal["step_end"] = "step_end"
    step_num: int
    state_transition: str
    token_usage: dict | None = None


class SessionEnd(EventBase):
    """Emitted when the agent session terminates."""

    event_type: Literal["session_end"] = "session_end"
    final_state: str
    total_steps: int
    exit_reason: str


# ── Inner streaming events ──────────────────────────────────────────


class LLMToken(EventBase):
    """Emitted for each token delta during LLM streaming."""

    event_type: Literal["llm_token"] = "llm_token"
    step_num: int
    content_delta: str


class LLMContentDone(EventBase):
    """Emitted when the LLM finishes generating content for a step."""

    event_type: Literal["llm_content_done"] = "llm_content_done"
    step_num: int
    full_content: str


class ToolCallStart(EventBase):
    """Emitted when the LLM initiates a tool call."""

    event_type: Literal["tool_call_start"] = "tool_call_start"
    step_num: int
    tool_name: str
    tool_call_id: str


class ToolCallArgs(EventBase):
    """Emitted for each args delta during streaming tool argument generation."""

    event_type: Literal["tool_call_args"] = "tool_call_args"
    step_num: int
    tool_name: str
    args_delta: str


class ToolCallDone(EventBase):
    """Emitted when all tool arguments have been received."""

    event_type: Literal["tool_call_done"] = "tool_call_done"
    step_num: int
    tool_name: str
    tool_call_id: str
    full_args: dict


class ToolResult(EventBase):
    """Emitted after a tool finishes execution."""

    event_type: Literal["tool_result"] = "tool_result"
    step_num: int
    tool_name: str
    tool_call_id: str
    result: str
    is_error: bool = False
    duration_ms: float


# ── Guard events ─────────────────────────────────────────────────────


class BudgetWarning(EventBase):
    """Emitted when step budget reaches 80% threshold."""

    event_type: Literal["budget_warning"] = "budget_warning"
    step_num: int
    used_pct: float
    max_steps: int


class BudgetExhausted(EventBase):
    """Emitted when the step budget is fully consumed."""

    event_type: Literal["budget_exhausted"] = "budget_exhausted"
    step_num: int


class LoopDetected(EventBase):
    """Emitted when a tool call loop is detected."""

    event_type: Literal["loop_detected"] = "loop_detected"
    step_num: int
    tool_name: str
    consecutive_count: int


class Error(EventBase):
    """Emitted when an error occurs during agent execution."""

    event_type: Literal["error"] = "error"
    step_num: int
    error_type: str
    message: str
    traceback: str | None = None


# ── Discriminated union type ────────────────────────────────────────

Event = Annotated[
    StepStart
    | StepEnd
    | SessionEnd
    | LLMToken
    | LLMContentDone
    | ToolCallStart
    | ToolCallArgs
    | ToolCallDone
    | ToolResult
    | BudgetWarning
    | BudgetExhausted
    | LoopDetected
    | Error,
    Field(discriminator="event_type"),
]
