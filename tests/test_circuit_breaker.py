"""Tests for CircuitBreaker — sliding-window failure rate and state machine."""

import asyncio
import time
from unittest.mock import AsyncMock

import pytest

from loopai.resilience.circuit_breaker import CircuitBreaker, CircuitState


class TestInitialStateClosed:
    """Verify a new tool starts in CLOSED state."""

    def test_initial_state_closed(self):
        breaker = CircuitBreaker(window_size=10, failure_threshold=0.5)
        allowed, state = breaker.check("bash")
        assert allowed is True
        assert state == CircuitState.CLOSED
        assert breaker.get_tool_state("bash") == CircuitState.CLOSED


class TestOpensOnHighFailureRate:
    """Verify circuit opens when failure rate exceeds threshold."""

    @pytest.mark.asyncio
    async def test_opens_on_high_failure_rate(self):
        breaker = CircuitBreaker(window_size=10, failure_threshold=0.5)

        # 6 failures out of 10 -> 60% > 50%
        for i in range(10):
            success = i < 4  # first 4 succeed, last 6 fail
            await breaker.record("bash", success)

        assert breaker.get_tool_state("bash") == CircuitState.OPEN


class TestBlocksWhenOpen:
    """Verify check() returns (False, OPEN) when circuit is open."""

    @pytest.mark.asyncio
    async def test_blocks_when_open(self):
        breaker = CircuitBreaker(window_size=10, failure_threshold=0.5)

        # Trigger open: 6 failures of 10
        for i in range(10):
            await breaker.record("bash", i < 4)

        allowed, state = breaker.check("bash")
        assert allowed is False
        assert state == CircuitState.OPEN


class TestHalfOpenAfterCooldown:
    """Verify circuit transitions to HALF_OPEN after cooldown expires."""

    def test_half_open_after_cooldown(self):
        breaker = CircuitBreaker(
            window_size=10, failure_threshold=0.5, cooldown_seconds=0.001
        )

        # Manually set state to OPEN (bypassing sliding window)
        breaker._state["bash"] = CircuitState.OPEN
        breaker._opened_at["bash"] = time.monotonic()

        # Wait for cooldown
        time.sleep(0.01)

        allowed, state = breaker.check("bash")
        assert allowed is True
        assert state == CircuitState.HALF_OPEN
        assert breaker.get_tool_state("bash") == CircuitState.HALF_OPEN


class TestHalfOpenSuccessCloses:
    """Verify a successful probe closes the circuit."""

    @pytest.mark.asyncio
    async def test_half_open_success_closes(self):
        breaker = CircuitBreaker(
            window_size=10, failure_threshold=0.5, cooldown_seconds=0.001
        )

        # Manually set to OPEN, then transition via check()
        breaker._state["bash"] = CircuitState.OPEN
        breaker._opened_at["bash"] = time.monotonic()
        time.sleep(0.01)

        allowed, _ = breaker.check("bash")
        assert allowed is True  # HALF_OPEN probe

        # Probe succeeds
        await breaker.record("bash", True)
        assert breaker.get_tool_state("bash") == CircuitState.CLOSED


class TestHalfOpenFailureReopens:
    """Verify a failed probe re-opens the circuit."""

    @pytest.mark.asyncio
    async def test_half_open_failure_reopens(self):
        breaker = CircuitBreaker(
            window_size=10, failure_threshold=0.5, cooldown_seconds=0.001
        )

        breaker._state["bash"] = CircuitState.OPEN
        breaker._opened_at["bash"] = time.monotonic()
        time.sleep(0.01)

        allowed, _ = breaker.check("bash")
        assert allowed is True  # HALF_OPEN

        # Probe fails
        await breaker.record("bash", False)
        assert breaker.get_tool_state("bash") == CircuitState.OPEN


class TestEventsPublished:
    """Verify state-change events are published to the EventBus."""

    @pytest.mark.asyncio
    async def test_events_published(self):
        bus = AsyncMock()
        breaker = CircuitBreaker(window_size=10, failure_threshold=0.5)

        # Trigger OPEN via sliding window
        for i in range(10):
            await breaker.record("bash", i < 4, bus, session_id="sess-1")

        # Should have published circuit_opened
        open_calls = [
            c for c in bus.publish.call_args_list
            if c[0][0] == "circuit_opened"
        ]
        assert len(open_calls) >= 1

        # Now manually transition to half-open and succeed
        breaker._state["bash"] = CircuitState.OPEN
        breaker._opened_at["bash"] = time.monotonic() - 999  # well past cooldown
        breaker.check("bash")  # transition to HALF_OPEN

        # Reset mock to see new calls
        bus.reset_mock()

        await breaker.record("bash", True, bus, session_id="sess-1")

        close_calls = [
            c for c in bus.publish.call_args_list
            if c[0][0] == "circuit_closed"
        ]
        assert len(close_calls) >= 1


class TestDoesNotOpenOnLowFailureRate:
    """Verify circuit stays CLOSED when failure rate is below threshold."""

    @pytest.mark.asyncio
    async def test_does_not_open_on_low_failure_rate(self):
        breaker = CircuitBreaker(window_size=10, failure_threshold=0.5)

        # 3 failures out of 10 -> 30% <= 50%
        for i in range(10):
            await breaker.record("python", i < 7)  # first 7 succeed, last 3 fail

        assert breaker.get_tool_state("python") == CircuitState.CLOSED


class TestConcurrentProbeBlocks:
    """Verify only one concurrent probe is allowed (asyncio.Lock + probing set)."""

    @pytest.mark.asyncio
    async def test_concurrent_probe_blocks(self):
        breaker = CircuitBreaker(
            window_size=10, failure_threshold=0.5, cooldown_seconds=0.001
        )

        breaker._state["bash"] = CircuitState.OPEN
        breaker._opened_at["bash"] = time.monotonic()
        time.sleep(0.01)

        # First check() gets HALF_OPEN
        allowed1, state1 = breaker.check("bash")
        assert allowed1 is True
        assert state1 == CircuitState.HALF_OPEN
        assert "bash" in breaker._probing

        # Second check() should be blocked (probing already in progress)
        allowed2, state2 = breaker.check("bash")
        assert allowed2 is False
        assert state2 == CircuitState.OPEN

        # After record, probing set is cleared
        await breaker.record("bash", True)
        assert "bash" not in breaker._probing


class TestGetOpenTools:
    """Verify get_open_tools() returns tools in OPEN state."""

    @pytest.mark.asyncio
    async def test_get_open_tools(self):
        breaker = CircuitBreaker(window_size=10, failure_threshold=0.5)

        # Open bash
        for i in range(10):
            await breaker.record("bash", i < 4)

        # python stays closed
        for i in range(10):
            await breaker.record("python", i < 7)

        open_tools = breaker.get_open_tools()
        assert "bash" in open_tools
        assert "python" not in open_tools

        # Reset bash
        breaker.reset_tool("bash")
        assert breaker.get_tool_state("bash") == CircuitState.CLOSED
        assert "bash" not in breaker.get_open_tools()
