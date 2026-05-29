"""Per-tool circuit breaker with sliding-window failure rate.

Implements the standard closed -> open -> half-open -> closed state
machine (D-05).  State transitions are published to the EventBus
(D-06) so the dashboard and JSONL logger can observe them.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from loopai.events.bus import EventBus


class CircuitState(str, Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation — calls are allowed
    OPEN = "open"  # Tripped — calls are blocked
    HALF_OPEN = "half_open"  # Probing — one trial call allowed


class CircuitBreaker:
    """Per-tool circuit breaker driven by sliding-window failure rate.

    Each tool has its own independent sliding window and state.
    After cooldown_seconds, a single probe call is allowed (half-open).
    Success closes the circuit; failure re-opens it.

    Thread-safety for the half-open probe is provided via an
    ``asyncio.Lock`` and a ``_probing`` set (Pitfall 1).
    """

    def __init__(
        self,
        window_size: int = 10,
        failure_threshold: float = 0.5,
        cooldown_seconds: float = 30.0,
    ) -> None:
        self.window_size = window_size
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds

        # Per-tool state
        self._window: dict[str, deque[bool]] = {}  # tool_name -> [success/fail]
        self._state: dict[str, CircuitState] = {}  # tool_name -> state
        self._opened_at: dict[str, float] = {}  # tool_name -> monotonic timestamp
        self._probing: set[str] = set()  # tools currently in half-open probe
        self._lock: asyncio.Lock = asyncio.Lock()

    # ── Public API ──────────────────────────────────────────────────

    def check(self, tool_name: str) -> tuple[bool, CircuitState]:
        """Check whether *tool_name* is allowed to execute.

        Returns:
            ``(allowed, current_state)``.
            - ``(True, CLOSED)`` — normal operation.
            - ``(True, HALF_OPEN)`` — probe call allowed.
            - ``(False, OPEN)`` — blocked (cooldown not expired or
              another probe already in progress).
        """
        # Half-open mutual exclusion (Pitfall 1)
        if tool_name in self._probing:
            return (False, CircuitState.OPEN)

        state = self._state.get(tool_name, CircuitState.CLOSED)

        if state == CircuitState.OPEN:
            elapsed = time.monotonic() - self._opened_at.get(tool_name, 0.0)
            if elapsed >= self.cooldown_seconds:
                self._state[tool_name] = CircuitState.HALF_OPEN
                self._probing.add(tool_name)
                return (True, CircuitState.HALF_OPEN)
            return (False, CircuitState.OPEN)

        return (True, state)

    async def record(
        self,
        tool_name: str,
        success: bool,
        bus: EventBus | None = None,
        *,
        session_id: str = "",
    ) -> None:
        """Record a tool execution outcome and update state.

        Args:
            tool_name: The tool that was executed.
            success: ``True`` if execution succeeded.
            bus: Optional EventBus for publishing state-change events.
            session_id: Session ID for event payloads.
        """
        # Initialise sliding window for new tools
        if tool_name not in self._window:
            self._window[tool_name] = deque(maxlen=self.window_size)
            self._state.setdefault(tool_name, CircuitState.CLOSED)

        self._window[tool_name].append(success)

        # Remove from probing set (probe completed)
        self._probing.discard(tool_name)

        # Calculate failure rate
        window = self._window[tool_name]
        failures = sum(1 for r in window if not r)
        rate = failures / len(window) if window else 0.0

        state = self._state.get(tool_name, CircuitState.CLOSED)

        if state == CircuitState.HALF_OPEN:
            async with self._lock:
                if success:
                    previous = CircuitState.HALF_OPEN.value
                    self._state[tool_name] = CircuitState.CLOSED
                    if bus is not None:
                        await bus.publish(
                            "circuit_closed",
                            {
                                "event_type": "circuit_closed",
                                "session_id": session_id,
                                "tool_name": tool_name,
                                "previous_state": previous,
                                "new_state": CircuitState.CLOSED.value,
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            },
                        )
                else:
                    previous = CircuitState.HALF_OPEN.value
                    self._state[tool_name] = CircuitState.OPEN
                    self._opened_at[tool_name] = time.monotonic()
                    if bus is not None:
                        await bus.publish(
                            "circuit_opened",
                            {
                                "event_type": "circuit_opened",
                                "session_id": session_id,
                                "tool_name": tool_name,
                                "failure_rate": rate,
                                "window_size": self.window_size,
                                "previous_state": previous,
                                "new_state": CircuitState.OPEN.value,
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            },
                        )

        elif state == CircuitState.CLOSED and rate > self.failure_threshold:
            previous = CircuitState.CLOSED.value
            self._state[tool_name] = CircuitState.OPEN
            self._opened_at[tool_name] = time.monotonic()
            if bus is not None:
                await bus.publish(
                    "circuit_opened",
                    {
                        "event_type": "circuit_opened",
                        "session_id": session_id,
                        "tool_name": tool_name,
                        "failure_rate": rate,
                        "window_size": self.window_size,
                        "previous_state": previous,
                        "new_state": CircuitState.OPEN.value,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                )

    async def record_with_session(
        self,
        tool_name: str,
        success: bool,
        session_id: str,
        bus: EventBus | None = None,
    ) -> None:
        """Convenience wrapper that passes *session_id* to ``record``."""
        await self.record(tool_name, success, bus, session_id=session_id)

    def get_open_tools(self) -> set[str]:
        """Return the set of tool names currently in OPEN state.

        Used by the FSM to filter tool schemas presented to the LLM.
        """
        return {
            name
            for name, state in self._state.items()
            if state == CircuitState.OPEN
        }

    def get_tool_state(self, tool_name: str) -> CircuitState:
        """Return the current circuit state for *tool_name*.

        Defaults to ``CLOSED`` if the tool has no recorded state.
        """
        return self._state.get(tool_name, CircuitState.CLOSED)

    def reset_tool(self, tool_name: str) -> None:
        """Reset all state for *tool_name* (window, state, timers, probing)."""
        self._window.pop(tool_name, None)
        self._state.pop(tool_name, None)
        self._opened_at.pop(tool_name, None)
        self._probing.discard(tool_name)
