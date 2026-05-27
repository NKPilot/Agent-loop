"""ReActFSM: ReAct loop state machine with guard integration.

Drives the agent through the REASON -> ACT -> OBSERVE cycle defined in D-02.
Integrates BudgetGuard, LoopDetector, and MessageValidator at their specified
intervention points. Publishes StepStart/StepEnd/SessionEnd events for
observability.
"""

from __future__ import annotations

import traceback
from typing import TYPE_CHECKING, Any

from loopai.session.context import AgentState
from loopai.state_machine.guards import ValidationError

if TYPE_CHECKING:
    from loopai.events.bus import EventBus
    from loopai.llm.client import LLMClient
    from loopai.session.context import Session
    from loopai.state_machine.guards import BudgetGuard, LoopDetector, MessageValidator


class ReActFSM:
    """ReAct loop finite state machine driving the agent cycle.

    Integrates LLMClient for reasoning, guards for safety, and EventBus
    for observability. Each iteration through the main loop dispatches to
    a handler based on the current AgentState.

    Attributes:
        client: LLMClient for API calls with streaming.
        bus: EventBus for publishing observability events.
        budget_guard: BudgetGuard for step budget enforcement.
        loop_detector: LoopDetector for tool call loop detection.
        message_validator: MessageValidator for message structure validation.
    """

    def __init__(
        self,
        client: LLMClient,
        bus: EventBus,
        budget_guard: BudgetGuard,
        loop_detector: LoopDetector,
        message_validator: MessageValidator,
    ) -> None:
        self.client = client
        self.bus = bus
        self.budget_guard = budget_guard
        self.loop_detector = loop_detector
        self.message_validator = message_validator
        self._exit_reason = "completed"
        self._last_act_failed = False

    async def run(self, session: Session) -> Session:
        """Execute the ReAct loop until FINISH or ERROR state.

        The main loop dispatches to _handle_reason, _handle_act, or
        _handle_observe based on session.state. Always publishes
        SessionEnd before returning.

        Args:
            session: The Session object with initial messages and state=REASON.

        Returns:
            The same Session object, now in FINISH or ERROR state.
        """
        while session.state not in (AgentState.FINISH, AgentState.ERROR):
            if session.state == AgentState.REASON:
                await self._handle_reason(session)
            elif session.state == AgentState.ACT:
                await self._handle_act(session)
            elif session.state == AgentState.OBSERVE:
                await self._handle_observe(session)
            else:
                session.state = AgentState.ERROR
                self._exit_reason = "unknown_state"

        # Always publish SessionEnd before returning
        await self.bus.publish(
            "session_end",
            {
                "event_type": "session_end",
                "session_id": session.session_id,
                "final_state": session.state.value,
                "total_steps": session.step_count,
                "exit_reason": self._exit_reason,
            },
        )

        return session

    # ── State handlers ──────────────────────────────────────────────────

    async def _handle_reason(self, session: Session) -> None:
        """Handle the REASON state: validate messages, check budget, call LLM.

        Transitions:
        - content + no tool_calls -> FINISH (D-01)
        - tool_calls -> ACT
        - ValidationError -> ERROR
        - Exception -> ERROR
        - budget "final" action -> FINISH after LLM response
        """
        step_num = session.step_count + 1

        await self.bus.publish(
            "step_start",
            {
                "event_type": "step_start",
                "session_id": session.session_id,
                "step_num": step_num,
            },
        )

        transition = "REASON_to_FINISH"

        try:
            # Guard: validate message structure before LLM call
            self.message_validator.validate(session.messages)

            # Guard: budget check (may inject system messages)
            should_continue, messages, action = self.budget_guard.check(
                session.step_count, session.messages
            )

            # Increment step count now (before LLM call) so SessionEnd reports correctly
            session.increment_step()

            # LLM call with (possibly modified) messages
            response = await self.client.complete(
                messages,
                session_id=session.session_id,
                step_num=step_num,
            )

            content = response.get("content", "")
            tool_calls: list[dict[str, Any]] = response.get("tool_calls", []) or []

            # Build assistant message
            add_kwargs: dict[str, Any] = {"role": "assistant"}
            if content:
                add_kwargs["content"] = content
            if tool_calls:
                add_kwargs["tool_calls"] = tool_calls
            session.messages.append(add_kwargs)

            # Determine next state
            if action == "final":
                # Budget exhausted: allow this final response, then force FINISH
                session.state = AgentState.FINISH
                transition = "REASON_to_FINISH"
                self._exit_reason = "budget_exhausted"
                await self.bus.publish(
                    "budget_exhausted",
                    {
                        "event_type": "budget_exhausted",
                        "session_id": session.session_id,
                        "step_num": step_num,
                    },
                )
            elif tool_calls:
                session.state = AgentState.ACT
                transition = "REASON_to_ACT"
            else:
                session.state = AgentState.FINISH
                transition = "REASON_to_FINISH"

            # Handle budget warning
            if action == "warn":
                await self.bus.publish(
                    "budget_warning",
                    {
                        "event_type": "budget_warning",
                        "session_id": session.session_id,
                        "step_num": step_num,
                        "used_pct": (session.step_count / self.budget_guard.max_steps) * 100,
                        "max_steps": self.budget_guard.max_steps,
                    },
                )

        except ValidationError:
            session.state = AgentState.ERROR
            transition = "REASON_to_ERROR"
            self._exit_reason = "validation_error"
        except Exception:
            session.state = AgentState.ERROR
            transition = "REASON_to_ERROR"
            self._exit_reason = "error"

        # Publish StepEnd
        await self.bus.publish(
            "step_end",
            {
                "event_type": "step_end",
                "session_id": session.session_id,
                "step_num": step_num,
                "state_transition": transition,
                "token_usage": None,
            },
        )

    async def _handle_act(self, session: Session) -> None:
        """Handle the ACT state: loop-detect tool calls, execute (or stub) tools.

        For Phase 1, no real tools exist. Each tool_call gets a synthetic
        tool_result message indicating tools are unavailable. Blocked or
        force-exited tool calls are handled per LoopDetector results.

        Transitions:
        - tool(s) processed -> OBSERVE
        - force_exit from LoopDetector -> FINISH
        """
        tool_calls_data = session.messages[-1].get("tool_calls", [])
        step_num = session.step_count
        any_blocked = False

        for tc in tool_calls_data:
            tool_name = tc.get("name", "unknown")
            tool_call_id = tc.get("tool_call_id", "")

            # Resolve arguments: may be a dict or a JSON string
            raw_args = tc.get("arguments", {})
            if isinstance(raw_args, str):
                import json as _json
                try:
                    raw_args = _json.loads(raw_args)
                except _json.JSONDecodeError:
                    raw_args = {}

            # Guard: loop detection
            should_proceed, loop_action = self.loop_detector.check(
                tool_name, raw_args
            )

            # Publish loop_detected warning event
            if loop_action == "warn":
                await self.bus.publish(
                    "loop_detected",
                    {
                        "event_type": "loop_detected",
                        "session_id": session.session_id,
                        "step_num": step_num,
                        "tool_name": tool_name,
                        "consecutive_count": self.loop_detector._consecutive_count,
                    },
                )

            if not should_proceed:
                if loop_action == "force_exit":
                    session.state = AgentState.FINISH
                    self._exit_reason = "loop_detected"
                    return

                # block: inject system message, treat as failure
                session.add_message(
                    "tool",
                    content=(
                        f"[SYSTEM] Tool call to '{tool_name}' has been blocked "
                        f"due to repeated identical calls. "
                        f"Please try a different approach or provide your answer directly."
                    ),
                    tool_call_id=tool_call_id,
                )
                any_blocked = True
                continue

            # Phase 1: synthetic tool result (no actual tool execution)
            session.add_message(
                "tool",
                content=(
                    "[SYSTEM] No tools are available in Phase 1. "
                    "Please provide your answer directly."
                ),
                tool_call_id=tool_call_id,
            )

        # Track whether any tool was blocked (for unreachable detection)
        self._last_act_failed = any_blocked
        session.state = AgentState.OBSERVE

    async def _handle_observe(self, session: Session) -> None:
        """Handle the OBSERVE state: increment step, check unreachable.

        Transitions:
        - step_count < max and not unreachable -> REASON
        - unreachable detected (3+ consecutive failures) -> FINISH
        """
        # Check unreachable detection via BudgetGuard
        unreachable = self.budget_guard.check_unreachable(self._last_act_failed)
        self._last_act_failed = False  # Reset for next cycle

        if unreachable == "unreachable":
            session.state = AgentState.FINISH
            self._exit_reason = "unreachable"
        else:
            session.state = AgentState.REASON
