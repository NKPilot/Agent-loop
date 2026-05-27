"""Session data class and AgentState enum for the loopAI agent framework.

Session provides a normalized state container for the ReAct FSM:
- Messages array in OpenAI-compatible format
- Step counter and tool call history
- AgentState tracking through the REASON/ACT/OBSERVE/FINISH/ERROR cycle

See: .planning/phases/01-agent-core-loop/01-CONTEXT.md D-02 (five states)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from loopai.config import AgentConfig


class AgentState(str, Enum):
    """ReAct agent FSM states as defined in D-02.

    REASON is the entry point. Each loop iteration starts from REASON.
    """

    REASON = "reason"
    ACT = "act"
    OBSERVE = "observe"
    FINISH = "finish"
    ERROR = "error"


@dataclass
class Session:
    """Canonical state container for the ReAct agent loop.

    Holds conversation history, step counter, tool call log, and
    the current AgentState. The FSM (Plan 05) reads and writes this
    object at each step.

    Attributes:
        session_id: Auto-generated UUID string identifying this session.
        state: Current agent state, defaults to REASON.
        messages: List of message dicts in OpenAI-compatible format.
        step_count: Number of completed loop iterations.
        tool_history: Log of (tool_name, signature) tuples for loop detection.
        created_at: ISO 8601 timestamp of session creation.
        config: Optional AgentConfig reference for this session.
    """

    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    state: AgentState = AgentState.REASON
    messages: list[dict[str, Any]] = field(default_factory=list)
    step_count: int = 0
    tool_history: list[tuple[str, str]] = field(default_factory=list)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    config: AgentConfig | None = None

    def add_message(
        self,
        role: str,
        content: str | None = None,
        *,
        tool_calls: list[dict[str, Any]] | None = None,
        tool_call_id: str | None = None,
        name: str | None = None,
    ) -> dict[str, Any]:
        """Append a message to the conversation history.

        Builds an OpenAI-compatible message dict for the given role.
        Supports all four API roles: system, user, assistant, tool.

        Args:
            role: One of "system", "user", "assistant", "tool".
            content: Text content of the message (may be None for tool_calls).
            tool_calls: Optional list of tool call dicts (assistant role only).
            tool_call_id: Tool call ID this message responds to (tool role only).
            name: Optional function name (tool role only).

        Returns:
            The constructed message dict that was appended to messages.

        Raises:
            ValueError: If role is not one of the four valid API roles.
        """
        valid_roles = {"system", "user", "assistant", "tool"}
        if role not in valid_roles:
            raise ValueError(
                f"Invalid role {role!r}. Must be one of: {', '.join(sorted(valid_roles))}"
            )

        message: dict[str, Any] = {"role": role}

        if content is not None or role not in ("assistant", "tool"):
            message["content"] = content

        if tool_calls is not None:
            message["tool_calls"] = tool_calls

        if tool_call_id is not None:
            message["tool_call_id"] = tool_call_id

        if name is not None:
            message["name"] = name

        self.messages.append(message)
        return message

    def increment_step(self) -> int:
        """Increment the step counter by one.

        Returns:
            The new step count after incrementing.
        """
        self.step_count += 1
        return self.step_count

    def record_tool_call(self, tool_name: str, signature: str) -> None:
        """Record a tool invocation in the tool history.

        The signature should be a hash or unique representation of the
        tool arguments, used by the loop detector (Plan 02 guards) to
        detect repeated identical calls.

        Args:
            tool_name: Name of the invoked tool.
            signature: Unique argument signature to detect repeated calls.
        """
        self.tool_history.append((tool_name, signature))
