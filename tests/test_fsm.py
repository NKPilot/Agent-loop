"""Tests for ReActFSM — the ReAct loop state machine with guard integration.

Covers all 5 state transitions, guard integration, event publishing,
and error handling per the D-01/D-02 decision documents.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from loopai.events.bus import EventBus
from loopai.session.context import AgentState, Session
from loopai.state_machine.guards import (
    BudgetGuard,
    LoopDetector,
    MessageValidator,
    PermissionGuard,
    ValidationError,
)
from loopai.tools.types import ToolMetadata, ToolResult, PermissionLevel


# ── Helpers ────────────────────────────────────────────────────────────


def make_tool_call(name="bash", arguments=None, tool_call_id="call_1"):
    """Create a tool_call dict for mock LLM responses."""
    return {
        "name": name,
        "arguments": arguments or {"cmd": "ls"},
        "tool_call_id": tool_call_id,
    }


def make_response(content=None, tool_calls=None):
    """Create a mock LLM response dict."""
    return {
        "content": content,
        "tool_calls": tool_calls or [],
        "role": "assistant",
    }


def _create_phase1_fsm(client, bus, budget_guard, loop_detector, message_validator):
    """Helper: create ReActFSM with Phase 1 behavior (no real tools).

    The mock registry returns None for any tool lookup, simulating a
    registry that doesn't have the requested tool registered. This keeps
    Phase 1 test behavior intact: unknown tools get error messages.
    """
    from loopai.state_machine.fsm import ReActFSM

    registry = MagicMock()
    registry.get.return_value = None  # No tools registered
    registry.get_schemas.return_value = []

    executor = MagicMock()
    executor.execute = AsyncMock()

    permission_guard = MagicMock()
    permission_guard.check = AsyncMock(return_value=(True, "allow"))

    return ReActFSM(
        client, bus, budget_guard, loop_detector, message_validator,
        registry, executor, permission_guard,
    )


# ── Test 1: REASON → FINISH (D-01) ────────────────────────────────────


@pytest.mark.asyncio
async def test_reason_to_finish_no_tool_calls():
    """LLM returns plain text (no tool_calls) → FSM transitions REASON→FINISH.

    Decision D-01: When the LLM responds with content and no tool_calls,
    the agent has reached its final answer and should terminate.
    """
    bus = EventBus()
    session = Session()

    client = MagicMock()
    client.complete = AsyncMock(
        return_value=make_response(content="The answer is 391.")
    )

    budget_guard = BudgetGuard(max_steps=15)
    loop_detector = LoopDetector()
    message_validator = MessageValidator()

    fsm = _create_phase1_fsm(client, bus, budget_guard, loop_detector, message_validator)

    result = await fsm.run(session)

    assert result.state == AgentState.FINISH
    assert result.messages[-1]["role"] == "assistant"
    assert result.messages[-1]["content"] == "The answer is 391."
    assert "tool_calls" not in result.messages[-1] or not result.messages[-1].get("tool_calls")


# ── Test 2: REASON → ACT ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reason_to_act_with_tool_calls():
    """LLM returns tool_calls → FSM transitions REASON→ACT→OBSERVE→REASON.

    The FSM handles the tool_calls, attempts to look up tools in the registry,
    and injects error messages for unregistered tools. Loops back to REASON
    for the next LLM call.
    """
    bus = EventBus()
    session = Session()

    client = MagicMock()
    client.complete = AsyncMock(
        side_effect=[
            make_response(
                content=None,
                tool_calls=[make_tool_call("bash", {"cmd": "ls -la"}, "call_abc")],
            ),
            make_response(content="Done listing files."),
        ]
    )

    budget_guard = BudgetGuard(max_steps=15)
    loop_detector = LoopDetector()
    message_validator = MessageValidator()

    fsm = _create_phase1_fsm(client, bus, budget_guard, loop_detector, message_validator)

    result = await fsm.run(session)

    assert result.state == AgentState.FINISH
    roles = [m["role"] for m in result.messages]
    assert "assistant" in roles
    assert "tool" in roles
    # Phase 2: unregistered tools get "未注册" message
    tool_msgs = [m for m in result.messages if m["role"] == "tool"]
    assert any("未注册" in (m.get("content") or "") for m in tool_msgs)


# ── Test 3: Full ReAct cycle ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_full_react_cycle_multiple_steps():
    """Multiple REASON→ACT→OBSERVE cycles before final FINISH.

    Verifies the FSM correctly loops through multiple tool-using steps
    and ultimately terminates when the LLM gives a final answer.
    """
    bus = EventBus()
    session = Session()

    client = MagicMock()
    client.complete = AsyncMock(
        side_effect=[
            make_response(
                content=None,
                tool_calls=[make_tool_call("bash", {"cmd": "df -h"}, "call_1")],
            ),
            make_response(
                content=None,
                tool_calls=[make_tool_call("bash", {"cmd": "du -sh"}, "call_2")],
            ),
            make_response(content="Disk usage analysis complete."),
        ]
    )

    budget_guard = BudgetGuard(max_steps=15)
    loop_detector = LoopDetector()
    message_validator = MessageValidator()

    fsm = _create_phase1_fsm(client, bus, budget_guard, loop_detector, message_validator)

    result = await fsm.run(session)

    assert result.state == AgentState.FINISH
    # After 2 tool cycles + final answer, step_count should be 3
    assert result.step_count == 3
    assert result.messages[-1]["content"] == "Disk usage analysis complete."


# ── Test 4: Exception → ERROR ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_error_state_on_exception():
    """Unhandled exception during LLM call → ERROR state.

    The FSM transitions to ERROR (Phase 1 terminal state) and publishes
    a SessionEnd event with exit_reason="error".
    """
    bus = EventBus()
    session = Session()

    client = MagicMock()
    client.complete = AsyncMock(side_effect=RuntimeError("API connection failed"))

    budget_guard = BudgetGuard(max_steps=15)
    loop_detector = LoopDetector()
    message_validator = MessageValidator()

    fsm = _create_phase1_fsm(client, bus, budget_guard, loop_detector, message_validator)

    result = await fsm.run(session)

    assert result.state == AgentState.ERROR

    # Verify SessionEnd event published with error exit_reason
    session_end_events = bus.replay("session_end")
    assert len(session_end_events) == 1
    assert session_end_events[0]["final_state"] == "error"
    assert "error" in session_end_events[0]["exit_reason"]


# ── Test 5: Step events emitted ───────────────────────────────────────


@pytest.mark.asyncio
async def test_step_events_emitted():
    """StepStart and StepEnd events published for each cycle.

    Verifies the observability contract: every REASON cycle emits
    a StepStart event at entry and StepEnd event at exit.
    SessionEnd is always published before run() returns.
    """
    bus = EventBus()
    session = Session()

    client = MagicMock()
    client.complete = AsyncMock(
        side_effect=[
            make_response(
                content=None,
                tool_calls=[make_tool_call("bash", {}, "call_x")],
            ),
            make_response(content="Final answer."),
        ]
    )

    budget_guard = BudgetGuard(max_steps=15)
    loop_detector = LoopDetector()
    message_validator = MessageValidator()

    fsm = _create_phase1_fsm(client, bus, budget_guard, loop_detector, message_validator)

    await fsm.run(session)

    step_starts = bus.replay("step_start")
    step_ends = bus.replay("step_end")
    session_ends = bus.replay("session_end")

    # Two REASON cycles → two StepStart + two StepEnd
    assert len(step_starts) == 2
    assert len(step_ends) == 2
    assert len(session_ends) == 1

    # Step numbers should increment
    assert step_starts[0]["step_num"] == 1
    assert step_starts[1]["step_num"] == 2

    # StepEnd should contain state_transition
    assert "state_transition" in step_ends[0]
    assert "state_transition" in step_ends[1]


# ── Test 6: BudgetGuard warning at 80% ────────────────────────────────


@pytest.mark.asyncio
async def test_budget_guard_injects_warning():
    """BudgetGuard at 80% threshold publishes budget_warning event.

    When step_count reaches the 80% threshold, BudgetGuard.check returns
    action="warn" and the FSM publishes a budget_warning event.
    """
    bus = EventBus()
    session = Session()
    session.step_count = 4  # At 80% of max_steps=5 (warn_threshold=4)

    client = MagicMock()
    client.complete = AsyncMock(
        return_value=make_response(content="I'll try to conclude soon.")
    )

    budget_guard = BudgetGuard(max_steps=5)
    loop_detector = LoopDetector()
    message_validator = MessageValidator()

    fsm = _create_phase1_fsm(client, bus, budget_guard, loop_detector, message_validator)

    await fsm.run(session)

    budget_warnings = bus.replay("budget_warning")
    assert len(budget_warnings) >= 1
    assert budget_warnings[0]["used_pct"] >= 80.0


# ── Test 7: Budget exhausted → final summary ──────────────────────────


@pytest.mark.asyncio
async def test_budget_exhausted_final_summary():
    """BudgetGuard at 100% forces FINISH with exit_reason="budget_exhausted".

    The FSM allows one more REASON cycle for the LLM to produce a final
    answer, then forces FINISH regardless of tool_calls.
    """
    bus = EventBus()
    session = Session()
    session.step_count = 5  # At max_steps=5, triggers "final" action

    client = MagicMock()
    # Even if LLM tries to call tools, FSM must force FINISH
    client.complete = AsyncMock(
        return_value=make_response(
            content="Based on what I know, the answer is 42.",
            tool_calls=[make_tool_call("bash", {"cmd": "verify"}, "call_forced")],
        )
    )

    budget_guard = BudgetGuard(max_steps=5)
    loop_detector = LoopDetector()
    message_validator = MessageValidator()

    fsm = _create_phase1_fsm(client, bus, budget_guard, loop_detector, message_validator)

    result = await fsm.run(session)

    assert result.state == AgentState.FINISH

    session_ends = bus.replay("session_end")
    assert len(session_ends) == 1
    assert session_ends[0]["exit_reason"] == "budget_exhausted"


# ── Test 8: Loop detection blocks tool ────────────────────────────────


@pytest.mark.asyncio
async def test_loop_detection_blocks_tool():
    """LoopDetector blocks repeated tool calls at 5+ consecutive calls.

    When the same tool+args is called 5 times consecutively, LoopDetector
    returns (False, "block"). The FSM injects a block message and counts
    it as a failure. On the 6th call, force_exit triggers FINISH.

    Note: Phase 2 adaptation — the registry mock returns valid metadata so
    that the "未注册" path is not taken (which would trigger unreachable
    detection before the loop detector can reach its block threshold).
    """
    from loopai.state_machine.fsm import ReActFSM

    bus = EventBus()
    session = Session()

    client = MagicMock()
    # Each cycle returns the same tool_call, triggering loop detection
    client.complete = AsyncMock(
        return_value=make_response(
            content=None,
            tool_calls=[make_tool_call("bash", {"cmd": "ls"}, "call_loop")],
        )
    )

    budget_guard = BudgetGuard(max_steps=15)
    loop_detector = LoopDetector(warn_threshold=3, block_threshold=5)
    message_validator = MessageValidator()

    # Phase 2: registry must return valid metadata so loop detector reaches
    # its threshold before unreachable detection kills the session.
    registry = MagicMock()
    registry.get.return_value = ToolMetadata(
        name="bash",
        description="Execute bash commands",
        permission_level=PermissionLevel.SAFE,
        timeout=60.0,
    )
    registry.get_schemas.return_value = []
    executor = MagicMock()
    executor.execute = AsyncMock(
        return_value=ToolResult.success(data="output", duration_ms=5.0)
    )
    permission_guard = MagicMock()
    permission_guard.check = AsyncMock(return_value=(True, "allow"))

    fsm = ReActFSM(
        client, bus, budget_guard, loop_detector, message_validator,
        registry, executor, permission_guard,
    )

    result = await fsm.run(session)

    # Should have terminated (either by force_exit → FINISH or unreachable → FINISH)
    assert result.state == AgentState.FINISH

    # Verify loop_detected events were published (at warn threshold)
    loop_events = bus.replay("loop_detected")
    assert len(loop_events) >= 1

    # Verify blocked tool message was injected
    tool_msgs = [m for m in result.messages if m["role"] == "tool"]
    blocked_msgs = [
        m for m in tool_msgs if "blocked" in (m.get("content") or "").lower()
    ]
    assert len(blocked_msgs) >= 1


# ── Test 9: Unreachable detection ─────────────────────────────────────


@pytest.mark.asyncio
async def test_unreachable_detection_too_many_failures():
    """BudgetGuard.check_unreachable triggers FINISH after 3+ consecutive failures.

    Each blocked tool call increments the consecutive failure counter.
    After 3 failures, check_unreachable returns "unreachable" and the
    FSM transitions to FINISH.
    """
    bus = EventBus()
    session = Session()

    client = MagicMock()
    # Always return tool_calls so the loop detector can block it
    client.complete = AsyncMock(
        return_value=make_response(
            content=None,
            tool_calls=[make_tool_call("bash", {"cmd": "ls"}, "call_fail")],
        )
    )

    budget_guard = BudgetGuard(max_steps=15)
    # LoopDetector that always blocks (returns False for should_proceed)
    loop_detector = MagicMock()
    loop_detector.check = MagicMock(return_value=(False, "block"))

    message_validator = MessageValidator()

    fsm = _create_phase1_fsm(client, bus, budget_guard, loop_detector, message_validator)

    result = await fsm.run(session)

    assert result.state == AgentState.FINISH

    session_ends = bus.replay("session_end")
    assert len(session_ends) == 1
    assert session_ends[0]["exit_reason"] == "unreachable"


# ── Test 10: Message validation rejects orphans ───────────────────────


@pytest.mark.asyncio
async def test_message_validation_rejects_orphans():
    """MessageValidator detects orphan tool_call → ValidationError → ERROR.

    When session messages contain a structural violation (e.g., tool_call
    without matching tool_result), MessageValidator.validate() raises
    ValidationError, and the FSM transitions to ERROR.
    """
    bus = EventBus()
    session = Session()

    # Pre-populate with an orphan assistant message (tool_call but no tool result)
    session.add_message(
        "assistant",
        content=None,
        tool_calls=[
            {
                "name": "bash",
                "arguments": {"cmd": "ls"},
                "id": "call_orphan",
                "tool_call_id": "call_orphan",
            }
        ],
    )

    client = MagicMock()
    # The LLM call should not happen because validation fails first
    client.complete = AsyncMock(
        return_value=make_response(content="Should not reach this.")
    )

    budget_guard = BudgetGuard(max_steps=15)
    loop_detector = LoopDetector()
    # Use real MessageValidator to detect the orphan
    message_validator = MessageValidator()

    fsm = _create_phase1_fsm(client, bus, budget_guard, loop_detector, message_validator)

    result = await fsm.run(session)

    assert result.state == AgentState.ERROR

    # LLM should never have been called
    client.complete.assert_not_called()

    session_ends = bus.replay("session_end")
    assert len(session_ends) == 1
    assert session_ends[0]["final_state"] == "error"


# ── Phase 2 Tests: Tool Registry + Executor + PermissionGuard ─────────


def _make_fsm_with_tools(client, bus, budget_guard, loop_detector, message_validator):
    """Helper: create ReActFSM with tool mocks for Phase 2 tests."""
    from loopai.state_machine.fsm import ReActFSM

    registry = MagicMock()
    executor = MagicMock()
    executor.execute = AsyncMock(
        return_value=ToolResult.success(data="output", duration_ms=10.0)
    )
    permission_guard = MagicMock()
    permission_guard.check = AsyncMock(return_value=(True, "allow"))

    # Register a mock tool metadata
    meta = ToolMetadata(
        name="bash",
        description="Execute bash commands",
        permission_level=PermissionLevel.SAFE,
        timeout=60.0,
        param_schema={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The command to run"},
            },
            "required": ["command"],
        },
    )
    registry.get.return_value = meta
    registry.get_schemas.return_value = [meta.to_openai_schema()]

    fsm = ReActFSM(
        client, bus, budget_guard, loop_detector, message_validator,
        registry, executor, permission_guard,
    )
    return fsm, registry, executor, permission_guard


@pytest.mark.asyncio
async def test_fsm_uses_tool_registry_and_executor():
    """Test 5: FSM._handle_act() uses ToolRegistry + ToolExecutor for tool execution.

    Verifies that when the LLM returns a tool_call, the FSM:
    1. Looks up the tool in the registry
    2. Calls executor.execute() with the tool name and arguments
    3. Publishes a tool_result event with execution results
    """
    bus = EventBus()
    session = Session()

    client = MagicMock()
    client.complete = AsyncMock(
        side_effect=[
            make_response(
                content=None,
                tool_calls=[make_tool_call("bash", {"command": "ls -la"}, "call_1")],
            ),
            make_response(content="Done."),
        ]
    )

    budget_guard = BudgetGuard(max_steps=15)
    loop_detector = LoopDetector()
    message_validator = MessageValidator()

    fsm, registry, executor, permission_guard = _make_fsm_with_tools(
        client, bus, budget_guard, loop_detector, message_validator
    )

    result = await fsm.run(session)

    # Tool was looked up
    registry.get.assert_called_with("bash")

    # Executor was called with the correct arguments
    executor.execute.assert_called_with("bash", {"command": "ls -la"})

    # Tool result event was published
    tool_results = bus.replay("tool_result")
    assert len(tool_results) >= 1
    assert tool_results[0]["tool_name"] == "bash"
    assert tool_results[0]["tool_call_id"] == "call_1"
    assert tool_results[0]["is_error"] is False
    assert "duration_ms" in tool_results[0]

    # Tool result message is in the session
    assert result.state == AgentState.FINISH


@pytest.mark.asyncio
async def test_fsm_handles_unregistered_tool():
    """Test 6: FSM injects "工具未注册" message for unknown tools.

    When the LLM tries to call a tool that's not in the registry,
    the FSM injects a system message indicating the tool is not registered
    and does NOT call the executor.
    """
    bus = EventBus()
    session = Session()

    client = MagicMock()
    client.complete = AsyncMock(
        side_effect=[
            make_response(
                content=None,
                tool_calls=[make_tool_call("unknown_tool", {}, "call_x")],
            ),
            make_response(content="Final answer."),
        ]
    )

    budget_guard = BudgetGuard(max_steps=15)
    loop_detector = LoopDetector()
    message_validator = MessageValidator()

    fsm, registry, executor, permission_guard = _make_fsm_with_tools(
        client, bus, budget_guard, loop_detector, message_validator
    )
    # Override: tool is NOT registered
    registry.get.return_value = None

    result = await fsm.run(session)

    # Executor should NOT have been called for the unknown tool
    executor.execute.assert_not_called()

    # Tool result message should contain "未注册"
    tool_msgs = [m for m in result.messages if m["role"] == "tool"]
    unregistered_msgs = [
        m for m in tool_msgs if "未注册" in (m.get("content") or "")
    ]
    assert len(unregistered_msgs) >= 1


@pytest.mark.asyncio
async def test_fsm_permission_guard_check_called():
    """Test 7: FSM calls PermissionGuard.check() before executing tools.

    The FSM must always invoke the permission guard's check method
    with the tool_name, tool_args, permission_level, session_id, and
    step_num BEFORE calling executor.execute().
    """
    bus = EventBus()
    session = Session()

    client = MagicMock()
    client.complete = AsyncMock(
        side_effect=[
            make_response(
                content=None,
                tool_calls=[make_tool_call("bash", {"command": "rm -rf /tmp/x"}, "call_danger")],
            ),
            make_response(content="Done."),
        ]
    )

    budget_guard = BudgetGuard(max_steps=15)
    loop_detector = LoopDetector()
    message_validator = MessageValidator()

    fsm, registry, executor, permission_guard = _make_fsm_with_tools(
        client, bus, budget_guard, loop_detector, message_validator
    )

    result = await fsm.run(session)

    # PermissionGuard.check() was called
    permission_guard.check.assert_called()
    call_args = permission_guard.check.call_args
    assert call_args[0][0] == "bash"  # tool_name
    assert call_args[0][1] == {"command": "rm -rf /tmp/x"}  # tool_args


@pytest.mark.asyncio
async def test_fsm_waits_for_confirm_then_proceeds():
    """Test 8: FSM waits for PermissionGuard confirmation, then proceeds.

    When PermissionGuard.check() returns (True, "allow") after waiting
    for user confirmation, the FSM proceeds with tool execution.
    """
    from loopai.state_machine.fsm import ReActFSM

    bus = EventBus()
    session = Session()

    client = MagicMock()
    client.complete = AsyncMock(
        side_effect=[
            make_response(
                content=None,
                tool_calls=[make_tool_call("bash", {"command": "rm /tmp/x"}, "call_danger")],
            ),
            make_response(content="Cleaned up."),
        ]
    )

    budget_guard = BudgetGuard(max_steps=15)
    loop_detector = LoopDetector()
    message_validator = MessageValidator()

    # Build mocks with permission_guard returning allow
    registry = MagicMock()
    executor = MagicMock()
    executor.execute = AsyncMock(
        return_value=ToolResult.success(data="Cleaned up.", duration_ms=10.0)
    )
    permission_guard = MagicMock()
    permission_guard.check = AsyncMock(return_value=(True, "allow"))

    meta = ToolMetadata(
        name="bash",
        description="Execute bash commands",
        permission_level=PermissionLevel.SAFE,
        timeout=60.0,
        param_schema={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The command to run"},
            },
            "required": ["command"],
        },
    )
    registry.get.return_value = meta
    registry.get_schemas.return_value = [meta.to_openai_schema()]

    fsm = ReActFSM(
        client, bus, budget_guard, loop_detector, message_validator,
        registry, executor, permission_guard,
    )

    result = await fsm.run(session)

    # Executor should have been called (confirmation was granted)
    executor.execute.assert_called()
    assert result.state == AgentState.FINISH


@pytest.mark.asyncio
async def test_fsm_injects_rejection_on_user_denied():
    """Test 9: FSM injects rejection message when user denies confirmation.

    When PermissionGuard.check() returns (False, "user_denied"), the FSM
    must inject a "[SYSTEM] 操作被用户拒绝" message and NOT call the executor.
    """
    from loopai.state_machine.fsm import ReActFSM

    bus = EventBus()
    session = Session()

    client = MagicMock()
    client.complete = AsyncMock(
        side_effect=[
            make_response(
                content=None,
                tool_calls=[make_tool_call("bash", {"command": "rm /tmp/x"}, "call_rejected")],
            ),
            make_response(content="OK, I won't delete that."),
        ]
    )

    budget_guard = BudgetGuard(max_steps=15)
    loop_detector = LoopDetector()
    message_validator = MessageValidator()

    # Build mocks with permission_guard returning deny from the start
    registry = MagicMock()
    executor = MagicMock()
    executor.execute = AsyncMock(
        return_value=ToolResult.success(data="output", duration_ms=10.0)
    )
    permission_guard = MagicMock()
    permission_guard.check = AsyncMock(return_value=(False, "user_denied"))

    meta = ToolMetadata(
        name="bash",
        description="Execute bash commands",
        permission_level=PermissionLevel.SAFE,
        timeout=60.0,
        param_schema={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The command to run"},
            },
            "required": ["command"],
        },
    )
    registry.get.return_value = meta
    registry.get_schemas.return_value = [meta.to_openai_schema()]

    fsm = ReActFSM(
        client, bus, budget_guard, loop_detector, message_validator,
        registry, executor, permission_guard,
    )

    result = await fsm.run(session)

    # Executor should NOT have been called
    executor.execute.assert_not_called()

    # Rejection message should be in tool messages
    tool_msgs = [m for m in result.messages if m["role"] == "tool"]
    rejected_msgs = [
        m for m in tool_msgs if "用户拒绝" in (m.get("content") or "")
    ]
    assert len(rejected_msgs) >= 1


@pytest.mark.asyncio
async def test_fsm_injects_timeout_on_confirmation_timeout():
    """Test 10: FSM injects timeout message when confirmation times out.

    When PermissionGuard.check() returns (False, "timeout"), the FSM
    must inject a "[SYSTEM] 操作被确认超时" message and NOT call the executor.
    """
    from loopai.state_machine.fsm import ReActFSM

    bus = EventBus()
    session = Session()

    client = MagicMock()
    client.complete = AsyncMock(
        side_effect=[
            make_response(
                content=None,
                tool_calls=[make_tool_call("bash", {"command": "dd if=/dev/zero"}, "call_timeout")],
            ),
            make_response(content="I'll try something else."),
        ]
    )

    budget_guard = BudgetGuard(max_steps=15)
    loop_detector = LoopDetector()
    message_validator = MessageValidator()

    # Build mocks with permission_guard returning timeout
    registry = MagicMock()
    executor = MagicMock()
    executor.execute = AsyncMock(
        return_value=ToolResult.success(data="output", duration_ms=10.0)
    )
    permission_guard = MagicMock()
    permission_guard.check = AsyncMock(return_value=(False, "timeout"))

    meta = ToolMetadata(
        name="bash",
        description="Execute bash commands",
        permission_level=PermissionLevel.SAFE,
        timeout=60.0,
        param_schema={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The command to run"},
            },
            "required": ["command"],
        },
    )
    registry.get.return_value = meta
    registry.get_schemas.return_value = [meta.to_openai_schema()]

    fsm = ReActFSM(
        client, bus, budget_guard, loop_detector, message_validator,
        registry, executor, permission_guard,
    )

    result = await fsm.run(session)

    # Executor should NOT have been called
    executor.execute.assert_not_called()

    # Timeout message should be in tool messages
    tool_msgs = [m for m in result.messages if m["role"] == "tool"]
    timeout_msgs = [
        m for m in tool_msgs if "超时" in (m.get("content") or "")
    ]
    assert len(timeout_msgs) >= 1
