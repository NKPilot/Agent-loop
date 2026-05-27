---
phase: 01-agent-core-loop
plan: "03"
subsystem: llm
tags: [openai, streaming, event-bus, session, fsm]

# Dependency graph
requires:
  - phase: "01-01"
    provides: EventBus with publish/subscribe, event schemas (LLMToken, ToolCallStart, etc.)
  - phase: "01-02"
    provides: AgentConfig with api_key, base_url, model, max_steps
provides:
  - LLMClient wrapping OpenAI beta streaming API with typed EventBus publishing
  - Session data class with AgentState enum for FSM state container
  - 7 passing tests for LLMClient covering text responses, tool calls, errors, edge cases
affects:
  - "01-05" (FSM implementation - consumes LLMClient and Session)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Mock-based async testing: MagicMock for Pydantic models, _MockStream for OpenAI SDK async context manager protocol"
    - "Event publishing pattern: LLMClient iterates beta stream events and fans out typed events to EventBus"
    - "Fallback parsing: parsed_arguments used when available, json.loads as fallback for None"

key-files:
  created:
    - src/loopai/llm/__init__.py - LLM integration package
    - src/loopai/llm/client.py - LLMClient with beta streaming and EventBus integration (123 lines)
    - src/loopai/session/__init__.py - Session package
    - src/loopai/session/context.py - Session dataclass with AgentState enum (92 lines)
    - tests/test_llm_client.py - 7 test cases for LLMClient
  modified: []

key-decisions:
  - "ChunkEvent used to extract tool_call_id from delta before ToolCallStart emission"
  - "parsed_arguments=None fallback to json.loads() implemented in both stream handler and _build_response"
  - "Session uses dataclass (not Pydantic) for simplicity - config field accepts AgentConfig | None"

patterns-established:
  - "LLMClient pattern: constructor receives config + bus, complete() method handles streaming + publishing"
  - "Session pattern: dataclass with methods for message building, step tracking, tool call logging"

requirements-completed: [CORE-02]

# Metrics
duration: 10min
completed: 2026-05-27
---

# Phase 01 Plan 03: LLM Client and Session Foundation Summary

**LLMClient wrapping OpenAI beta streaming API with token-level EventBus publishing, Session data class with AgentState enum for ReAct FSM**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-05-27T12:37:00Z
- **Completed:** 2026-05-27T12:47:00Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments
- LLMClient using client.beta.chat.completions.stream() with 7 event types handled: content.delta, content.done, chunk, tool_calls.function.arguments.delta, tool_calls.function.arguments.done, plus Error event on exceptions
- 7 passing tests covering: client configuration, text response events, tool call events (ToolCallStart/Args/Done), stream return value, error publishing, empty tool calls, multiple tool calls with correct indexing
- Session data class with AgentState enum (REASON/ACT/OBSERVE/FINISH/ERROR per D-02), supporting all 4 OpenAI message roles
- All imports verified: LLMClient, Session, and EventBus compose cleanly

## Task Commits

Each task was committed atomically:

1. **Task 1: Implement LLMClient with OpenAI beta streaming + EventBus (TDD)** - `2d958ac` (test), `77071c0` (feat)
2. **Task 2: Implement Session data class with AgentState enum** - `3686abb` (feat)

## Files Created/Modified
- `src/loopai/llm/__init__.py` - LLM integration package (5 lines)
- `src/loopai/llm/client.py` - LLMClient: beta streaming wrapper with EventBus publishing (123 lines)
- `src/loopai/session/__init__.py` - Session package (5 lines)
- `src/loopai/session/context.py` - AgentState enum + Session dataclass with message management (92 lines)
- `tests/test_llm_client.py` - 7 test cases for LLMClient (589 lines)

## Decisions Made
- Extracted tool_call_id from ChunkEvent (chunk.choices[0].delta.tool_calls[i].id) to populate ToolCallStart events during streaming. The FunctionToolCallArgumentsDeltaEvent does not include tool_call_id, so the ChunkEvent is the source of truth.
- Implemented parsed_arguments=None fallback (json.loads on raw arguments) in both stream event handler and _build_response, per plan's REFACTOR phase guidance. This was folded into the GREEN implementation to avoid a separate commit.
- Used dataclass (not Pydantic) for Session to keep it lightweight. The config field accepts AgentConfig | None for flexibility.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed test mock approach: autospec prevents deep attribute mocking**
- **Found during:** Task 1 (LLMClient GREEN phase)
- **Issue:** `patch("openai.AsyncOpenAI", autospec=True)` prevents mocking `.beta.chat.completions.stream` because `beta` is a `cached_property` not exposed in the mock spec
- **Fix:** Changed to `patch("loopai.llm.client.AsyncOpenAI")` (module-level reference without autospec), manually constructing MagicMock for the instance chain
- **Files modified:** tests/test_llm_client.py
- **Committed in:** `77071c0` (Task 1 feat commit)

**2. [Rule 1 - Bug] Fixed test helper Pydantic validation errors with ParsedChatCompletionSnapshot**
- **Found during:** Task 1 (RED phase - test construction)
- **Issue:** Direct construction of ParsedChatCompletionSnapshot and ParsedChatCompletion failed due to missing required fields (finish_reason, object literal constraint)
- **Fix:** Replaced real Pydantic model construction with MagicMock objects that expose the same attribute API expected by LLMClient (id, choices, message, content, tool_calls, etc.)
- **Files modified:** tests/test_llm_client.py
- **Committed in:** `2d958ac` (Task 1 test commit)

---

**Total deviations:** 2 auto-fixed (Rule 1 bugs in test infrastructure)
**Impact on plan:** Both fixes limited to test code. Production code unchanged. No scope creep.

## Issues Encountered
- None.

## User Setup Required
None - no external service configuration required. Tests run with mocked OpenAI API.

## Next Phase Readiness
- LLMClient ready for FSM integration in Plan 05
- Session data class provides canonical state container for FSM
- All 7 LLMClient tests pass with mock API
- EventBus publish/subscribe pattern validated end-to-end through streaming

---
*Phase: 01-agent-core-loop*
*Plan: 03*
*Completed: 2026-05-27*
