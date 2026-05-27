---
phase: 01-agent-core-loop
plan: 05
subsystem: agent-core-loop
tags: [react-fsm, cli-entry, session-orchestration, graceful-shutdown, guard-integration, tdd]
requires: [01-01 (EventBus + Schemas), 01-02 (Guards + Config), 01-03 (LLMClient + Session), 01-04 (JSONLLogger + CLIAgentRenderer)]
provides: [ReActFSM, run_session, main_cli]
affects: [CORE-01]
tech-stack:
  added: []
  patterns:
    - "ReAct loop: REASON -> ACT -> OBSERVE -> REASON cycle with guard checkpoints"
    - "FSM state dispatch via _handle_{state} methods in while loop"
    - "Graceful shutdown: None sentinel -> asyncio.gather drain (5s timeout) -> logger.stop()"
    - "Phase 1 synthetic tool_result for tool_calls (no actual tools yet)"
    - "TDD: RED test -> GREEN implementation per task"
key-files:
  created:
    - src/loopai/state_machine/fsm.py
    - src/loopai/main.py
    - tests/test_fsm.py
  modified:
    - src/loopai/state_machine/guards.py
decisions:
  - "D-01: REASON->FINISH on plain text response (no tool_calls) confirmed in _handle_reason()"
  - "D-02: REASON->ACT->OBSERVE->REASON cycle with guard integration at each transition"
  - "Phase 1 tool handling: synthetic tool_result injected when LLM requests tools (no actual execution)"
  - "BudgetGuard 'final' action: allows one more REASON cycle then forces FINISH with exit_reason='budget_exhausted'"
  - "LoopDetector: 5+ repeated identical tool calls blocked, persistent blocking triggers force_exit -> FINISH"
  - "Unreachable detection: 3+ consecutive failures -> FINISH with exit_reason='unreachable'"
  - "DeepSeek API confirmed compatible (base_url=https://api.deepseek.com, model=deepseek-chat)"
metrics:
  duration: "~5 minutes"
  completed_date: "2026-05-27T21:00:00Z"
---

# Phase 01 Plan 05: Agent Core Loop Integration Summary

**One-liner:** ReActFSM with full guard integration driving the agent lifecycle, CLI entry point with session orchestration and graceful shutdown via None sentinel consumer drain.

## Tasks Executed

| Task | Name | Type | Commit | Tests |
|------|------|------|--------|-------|
| 1 (RED) | ReActFSM failing tests | test | `177ba06` | 10 fail (expected) |
| 1 (GREEN) | ReActFSM with guard integration | feat | `986ed8f` | 10 pass |
| 2 | CLI entry point with session orchestration | feat | `4ffd0c9` | -- |
| 3 | E2E human verification (checkpoint) | verify | -- | 95/95 pass |

## What Was Built

### ReActFSM (`fsm.py` - 297 lines)

Full finite state machine implementing the ReAct agent loop with 5 states:

**State transitions (per D-01, D-02):**
- REASON --[has tool_calls]--> ACT
- REASON --[no tool_calls, has content]--> FINISH (D-01)
- REASON --[LLM error]--> ERROR
- ACT --[tool executed]--> OBSERVE
- ACT --[tool error]--> ERROR
- OBSERVE --[steps < max]--> REASON
- OBSERVE --[steps >= max]--> FINISH (via BudgetGuard "final")
- OBSERVE --[unreachable]--> FINISH
- ANY --[unhandled exception]--> ERROR

**Guard integration at every transition:**
- Pre-REASON: `BudgetGuard.check()` + `MessageValidator.validate()`
- Pre-ACT: `LoopDetector.check()` (blocks at 5+ repeated calls)
- Post-OBSERVE: `BudgetGuard.check_unreachable()` (FINISH at 3+ consecutive failures)

**Event publishing:**
- `StepStart` / `StepEnd` per cycle
- `SessionEnd` always published before `run()` returns
- All events routed through EventBus for consumer observability

**Phase 1 tool handling:**
When LLM returns `tool_calls` but no tools are registered (Phase 2 scope), FSM injects a synthetic tool_result: `"[SYSTEM] No tools are available in Phase 1. Please provide your answer directly."` This allows the full REACT->ACT->OBSERVE->REASON cycle to be exercised and tested without actual tool execution.

### CLI Entry Point (`main.py` - 200 lines)

Complete session lifecycle orchestration:

```
run_session(prompt, config, max_steps_override) -> Session:
  1. Create EventBus, Session, LLMClient, Guards, ReActFSM
  2. Create JSONLLogger, CLIAgentRenderer consumers
  3. Start consumers as asyncio tasks
  4. Run FSM to completion (FINISH or ERROR)
  5. Graceful shutdown:
     - bus.shutdown() -> None sentinels to all subscribers
     - asyncio.wait_for(gather, timeout=5.0) -> drain consumers
     - logger.stop() -> fsync + close
  6. Return session with full message history
```

`main_cli()` entry point:
- argparse: `prompt` (positional), `--max-steps`, `--verbose`
- Delegates to `add_cli_args()` for config flags (api-key, base-url, model)
- Loads config via `load_config(args)`, runs via `asyncio.run(run_session(...))`
- Secure: API key never printed (SecretStr + verbose mode guard per T-05-01)

### Tests (`test_fsm.py` - 10 tests)

All 10 ReActFSM tests pass with mocked dependencies (LLMClient as AsyncMock, EventBus/Guards as MagicMock):

1. `test_reason_to_finish_no_tool_calls` -- D-01: plain text -> FINISH
2. `test_reason_to_act_with_tool_calls` -- tool_calls -> ACT transition
3. `test_full_react_cycle` -- REASON->ACT->OBSERVE->REASON->FINISH
4. `test_error_on_exception` -- unhandled exception -> ERROR
5. `test_step_events_emitted` -- StepStart/StepEnd per cycle
6. `test_budget_guard_injects_warning` -- 80% budget warning
7. `test_budget_exhausted_final_summary` -- 100% budget -> FINISH
8. `test_loop_detection_blocks_tool` -- 5+ repeated calls -> block
9. `test_unreachable_detection` -- 3+ consecutive failures -> FINISH
10. `test_message_validation_rejects_orphans` -- ValidationError -> ERROR

Full test suite: **95/95 pass** (including all tests from plans 01-01 through 01-05).

## Checkpoint Verification (Task 3)

All 5 verification steps passed using **DeepSeek API** (`deepseek-chat` model):

| Step | Description | Result |
|------|-------------|--------|
| 1 | Direct answer: "What is 17 * 23?" | 391 in 1 step (REASON->FINISH) |
| 2 | Tool simulation: directory listing with --max-steps 5 | ACT triggered, synthetic result injected, multi-step completion |
| 3 | JSONL logs: permissions and format | 0o600 permissions, valid JSON per line, all event types present |
| 4 | Budget exhaustion: long essay with --max-steps 3 | Budget warning appeared, terminated with budget_exhausted |
| 5 | Full test suite | 95/95 pass |

**API compatibility confirmed:** The agent works correctly with OpenAI-compatible APIs using `base_url` and `model` configuration.

## Deviations from Plan

None -- plan executed exactly as written. The single guards.py fix (1 line change, commit `986ed8f`) was a minor integration adjustment for the `check_unreachable` method signature, not a deviation.

## TDD Gate Compliance

```
177ba06  test(01-05): add failing tests for ReActFSM (RED phase)    <- RED gate
986ed8f  feat(01-05): implement ReActFSM with guard integration     <- GREEN gate
```

TDD cycle complete: 10 tests written first (all failing), then implementation makes all pass. No REFACTOR phase was needed as the GREEN implementation met all acceptance criteria on the first pass.

## Threat Flags

No new threat surface beyond what is documented in the plan's threat model. All mitigations are in place:
- T-05-01 (Info Leak): SecretStr protects API key; verbose mode guards prevent logging
- T-05-02 (DoS): BudgetGuard max_steps + LoopDetector + 5s shutdown timeout
- T-05-03 (Spoofing): tool_role messages with tool_call_id, never merged into user messages
- T-05-04 (Privilege Escalation): json.loads() only, no eval()/exec(); Phase 1 tools are no-op
- T-05-05 (Repudiation): JSONL audit trail accepted (no cryptographic signing in Phase 1)

## Phase 01 Completion Status

With Plan 05 complete, all Phase 01 deliverables are now built and verified:

| Plan | Component | Status |
|------|-----------|--------|
| 01-01 | EventBus + Event Schemas | Complete |
| 01-02 | Guards + Configuration | Complete |
| 01-03 | LLMClient + Session | Complete |
| 01-04 | JSONLLogger + CLI Renderer | Complete |
| 01-05 | ReActFSM + CLI Entry Point | Complete |

The Phase 01 agent core loop is fully operational: CLI -> Session -> FSM -> LLM -> EventBus -> Consumers, with real-time streaming output, JSONL audit logging, and graceful shutdown.
