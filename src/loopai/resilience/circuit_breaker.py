""":mod:`loopai.resilience.circuit_breaker` — Three-state tool circuit breaker (RES-06).

Implements the Circuit Breaker pattern for individual tools:
Closed (normal) → Open (failures exceed threshold) → Half-Open (probing) → Closed/Half-Open.

Decision reference:
    RES-06: Three-state circuit breaker per tool with sliding-window failure rate.
"""

from __future__ import annotations

import asyncio
import time
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from loopai.events.bus import EventBus


class CircuitState(StrEnum):
    """Circuit breaker states (D-03).

    CLOSED: Normal operation, calls pass through.
    OPEN: Failure threshold exceeded, calls are blocked.
    HALF_OPEN: Probing state — one call allowed to test recovery.
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class _ToolCircuit:
    """Per-tool circuit state machine."""

    def __init__(self, window_size: int = 10, failure_threshold: float = 0.5,
                 cooldown_seconds: float = 30.0) -> None:
        self.window_size = window_size
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.state = CircuitState.CLOSED
        self._results: list[bool] = []  # True=success, False=failure
        self._last_failure_time: float = 0.0
        self._lock = asyncio.Lock()

    @property
    def failure_rate(self) -> float:
        if not self._results:
            return 0.0
        return self._results.count(False) / len(self._results)

    def _transition(self) -> None:
        """Internal state machine transition (caller must hold lock)."""
        if self.state == CircuitState.CLOSED:
            if self.failure_rate >= self.failure_threshold:
                self.state = CircuitState.OPEN
                self._last_failure_time = time.monotonic()
        elif self.state == CircuitState.OPEN:
            if time.monotonic() - self._last_failure_time > self.cooldown_seconds:
                self.state = CircuitState.HALF_OPEN
        elif self.state == CircuitState.HALF_OPEN:
            if self.failure_rate < self.failure_threshold:
                self.state = CircuitState.CLOSED
            else:
                self.state = CircuitState.OPEN
                self._last_failure_time = time.monotonic()

    async def record(self, success: bool) -> CircuitState | None:
        """Record an execution result and trigger state transitions.

        Returns the new state if a transition occurred, None otherwise.
        """
        async with self._lock:
            old_state = self.state
            self._results.append(success)
            if len(self._results) > self.window_size:
                self._results = self._results[-self.window_size:]
            self._transition()
            if self.state != old_state:
                return self.state
            return None


class CircuitBreaker:
    """Three-state circuit breaker for individual tools (RES-06).

    Each tool has its own independent circuit. Failures are tracked in a
    sliding window; when the failure rate exceeds ``failure_threshold``,
    the circuit opens and calls are blocked. After ``cooldown_seconds``,
    the circuit transitions to half-open for probing.

    Attributes:
        window_size: Sliding window size for failure tracking.
        failure_threshold: Fraction (0.0-1.0) of failures to trigger OPEN.
        cooldown_seconds: Seconds to wait before transitioning OPEN → HALF_OPEN.
    """

    def __init__(
        self,
        window_size: int = 10,
        failure_threshold: float = 0.5,
        cooldown_seconds: float = 30.0,
    ) -> None:
        self._window_size = window_size
        self._failure_threshold = failure_threshold
        self._cooldown_seconds = cooldown_seconds
        self._tools: dict[str, _ToolCircuit] = {}

    def _get_or_create(self, tool_name: str) -> _ToolCircuit:
        if tool_name not in self._tools:
            self._tools[tool_name] = _ToolCircuit(
                window_size=self._window_size,
                failure_threshold=self._failure_threshold,
                cooldown_seconds=self._cooldown_seconds,
            )
        return self._tools[tool_name]

    def check(self, tool_name: str) -> tuple[bool, CircuitState]:
        """Check if a tool call should be allowed.

        Args:
            tool_name: The tool name to check.

        Returns:
            (allowed, state) — allowed is False when the circuit is OPEN.
        """
        tc = self._get_or_create(tool_name)
        # For OPEN circuits, check if cooldown has elapsed
        if tc.state == CircuitState.OPEN:
            if time.monotonic() - tc._last_failure_time > tc.cooldown_seconds:
                tc.state = CircuitState.HALF_OPEN
        return (tc.state != CircuitState.OPEN, tc.state)

    async def record(self, tool_name: str, success: bool,
                     bus: EventBus | None = None) -> None:
        """Record a tool execution result.

        Args:
            tool_name: The tool that was executed.
            success: Whether the execution succeeded.
            bus: Optional EventBus for publishing circuit state change events.
        """
        await self.record_with_session(tool_name, success, "", bus)

    async def record_with_session(
        self, tool_name: str, success: bool, session_id: str = "",
        bus: EventBus | None = None,
    ) -> None:
        """Record a tool execution result with session context.

        Args:
            tool_name: The tool that was executed.
            success: Whether the execution succeeded.
            session_id: Optional session identifier for event publishing.
            bus: Optional EventBus for publishing circuit state change events.
        """
        tc = self._get_or_create(tool_name)
        new_state = await tc.record(success)
        if new_state is not None and bus is not None:
            event_type = "circuit_opened" if new_state == CircuitState.OPEN else "circuit_closed"
            await bus.publish(
                event_type,
                {
                    "event_type": event_type,
                    "session_id": session_id,
                    "tool_name": tool_name,
                    "circuit_state": new_state.value,
                    "failure_rate": tc.failure_rate,
                },
            )

    def get_open_tools(self) -> set[str]:
        """Return the set of tool names whose circuit is currently OPEN.

        Returns:
            Set of tool name strings.
        """
        return {name for name, tc in self._tools.items() if tc.state == CircuitState.OPEN}

    def get_tool_state(self, tool_name: str) -> CircuitState:
        """Get the current circuit state for a tool.

        Args:
            tool_name: The tool name to query.

        Returns:
            The current CircuitState (CLOSED if tool has no circuit yet).
        """
        tc = self._tools.get(tool_name)
        return tc.state if tc else CircuitState.CLOSED

    def reset_tool(self, tool_name: str) -> None:
        """Reset the circuit for a tool back to CLOSED.

        Args:
            tool_name: The tool to reset.
        """
        if tool_name in self._tools:
            del self._tools[tool_name]
