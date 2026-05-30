---
phase: 07-chat-mode
reviewed: 2026-05-30T10:00:00Z
depth: standard
files_reviewed: 13
files_reviewed_list:
  - src/loopai/session/context.py
  - src/loopai/state_machine/fsm.py
  - src/loopai/events/schemas.py
  - src/loopai/api/schemas.py
  - src/loopai/api/routes/control.py
  - src/loopai/api/app.py
  - frontend/src/lib/eventTypes.ts
  - frontend/src/lib/api.ts
  - frontend/src/stores/uiStore.ts
  - frontend/src/stores/eventStore.ts
  - frontend/src/App.tsx
  - frontend/src/components/SessionList.tsx
  - tests/test_fsm.py
findings:
  critical: 0
  warning: 10
  info: 4
  total: 14
status: issues_found
---

# Phase 07: Code Review Report — Chat Mode

**Reviewed:** 2026-05-30T10:00:00Z
**Depth:** standard
**Files Reviewed:** 13
**Status:** issues_found

## Summary

Reviewed 13 source files implementing Phase 07 chat mode transformations: backend adds FINISH_WAIT state and multi-turn message flow, frontend rewrites to chat UI with round grouping and SSE integration. Found 0 critical issues, 10 warnings, and 4 info items.

The core architecture (FINISH_WAIT state, `_run_and_cleanup` loop, multi-turn queue) is sound. Most issues center on round grouping correctness on the frontend, missing input validation at the API boundary, and inconsistency between streaming and bulk-load event handling paths.

## Warnings

### WR-01: `updateRounds` silently drops events before first `user_message`

**File:** `frontend/src/stores/eventStore.ts:33-62`

**Issue:** The `updateRounds` function returns `rounds` unchanged when `rounds.length === 0` for any event that is not `user_message` (line 55) or `round_end` (line 45). This means ALL events from the first round of a session (before any `user_message` arrives via `send_message`) are silently dropped from the `roundsBySession` store. The `round_end` event for the first round is also dropped because no round exists to append it to.

The first round of any session is processed entirely before any `send_message` call — the initial prompt in `start_session` never generates a `user_message` event on the bus. Since `updateRounds` has no fallback for events arriving without a preceding `user_message`, the first round's data is absent from `getSessionRounds()`.

Impact is currently limited because App.tsx recomputes rounds from raw events via `buildRound` (which does handle pre-user_message events via flush-on-round_end), but any code path consuming `getSessionRounds()` will miss the first round entirely.

**Fix:** Add a fallback in `updateRounds` to create a new round when events arrive and `rounds` is empty — similar to the flush logic in `rebuildRounds`. Alternatively, publish a `user_message` event for the initial prompt in `start_session`.

```typescript
// In updateRounds, before the switch:
if (rounds.length === 0 && event.event_type !== "user_message") {
  const impliedRound: RoundInfo = {
    round_num: 1,
    events: [event],
  };
  return [impliedRound];
}
```

---

### WR-02: `rebuildRounds` and `buildRound` compute `round_num` from array position instead of event data

**File:** `frontend/src/stores/eventStore.ts:65-101` (rebuildRounds), `frontend/src/App.tsx:108,114,124` (buildRound)

**Issue:** Both `rebuildRounds` and the `buildRound` logic in App.tsx derive `round_num = rounds.length + 1` from the current array length rather than extracting it from the `user_message` event's `round_num` field. The `UserMessageEvent` already carries a `round_num` field emitted by the backend (`control.py:300`). If rounds ever arrive out of order or with non-sequential numbering, the UI will show incorrect round numbers.

In current practice round numbers are always sequential starting from 1, so this is latent — but it creates a silent mismatch between backend-assigned `round_num` and frontend-assigned `round_num` that will break if sessions are resumed from checkpoints or if round numbering ever becomes non-contiguous.

**Fix:** Extract `round_num` from the `user_message` event data when available:

```typescript
// In rebuildRounds (eventStore.ts:74,83):
if (event.event_type === "user_message") {
  round_num: (event as UserMessageEvent).round_num,
  events: currentEvents,
}
```

```typescript
// In App.tsx buildRound logic:
const userMsgRoundNum = currentUserMsg?.round_num ?? result.length + 1;
result.push(buildRound(userMsgRoundNum, currentUserMsg, currentEvents, tc));
```

---

### WR-03: First round has no `user_message` event — the initial prompt is invisible in the UI

**File:** `src/loopai/api/routes/control.py:140-194`

**Issue:** `start_session` never publishes a `user_message` event for the initial prompt. The prompt is passed to `create_agent_components` and embedded in `session.messages`, but no event flows onto the bus. As a result:

1. The frontend's `buildRound` produces a round with `userMessage: null` for the first round — the user's own prompt bubble is missing from the conversation UI.
2. The first message the user sent is only visible as a diminishing `startPrompt` state variable that gets cleared immediately after `startSession` succeeds.
3. The SSE stream begins with `step_start` events that have no preceding `user_message` to anchor a round.

**Fix:** Publish a `user_message` event in `start_session` before starting the agent task, carrying the initial prompt content and `round_num=1`:

```python
# In start_session, after creating session, before starting _run_and_cleanup:
await bus.publish(
    "user_message",
    {
        "event_type": "user_message",
        "session_id": session.session_id,
        "round_num": 1,
        "content": body.prompt,
    },
)
```

---

### WR-04: `isAgentThinking` persists indefinitely when session ends without `round_end`

**File:** `frontend/src/App.tsx:171-177`

**Issue:** The `isAgentThinking` memo checks for absence of `round_end` in the last round's events to determine if the agent is still processing. However, when a session terminates via FINISH or ERROR (instead of FINISH_WAIT), the FSM publishes `session_end` — not `round_end`. In this case, `hasRoundEnd` is `false` and `lastRound.agentEvents.length > 0` could be `true`, causing the "Agent is thinking..." indicator to show permanently even after the session has ended.

This affects sessions that hit ERROR state or terminate without reaching FINISH_WAIT (e.g., MessageValidator rejection, or future external kill).

**Fix:** Also check for `session_end` in the last round:

```typescript
const isAgentThinking = useMemo(() => {
  if (!activeSessionId) return false;
  const lastRound = rounds[rounds.length - 1];
  if (!lastRound) return false;
  const hasRoundEnd = lastRound.agentEvents.some(
    (e) => e.event_type === "round_end" || e.event_type === "session_end"
  );
  return !hasRoundEnd && lastRound.agentEvents.length > 0;
}, [activeSessionId, rounds]);
```

---

### WR-05: No input validation on `SendMessageRequest.content` — empty strings and unbounded payloads allowed

**File:** `src/loopai/api/schemas.py:68-71`

**Issue:** `SendMessageRequest.content` is typed as `str` with no `min_length`, `max_length`, or pattern validation. The API accepts empty strings (`""`) and arbitrarily large payloads. Empty strings add noise to the session history. Large payloads consume excessive memory in the session's message list and could be sent to the LLM as-is, incurring unnecessary token costs.

The frontend does guard against empty input (`App.tsx:156`), but the API should not rely on frontend validation for defense in depth.

**Fix:** Add Pydantic validators:

```python
from pydantic import BaseModel, Field

class SendMessageRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=100000)  # 100KB ceiling
```

---

### WR-06: `_round_num` private attribute accessed from `control.py`

**File:** `src/loopai/api/routes/control.py:300`

**Issue:** The `send_message` endpoint accesses `fsm._round_num` — a private attribute (prefixed `_`) of `ReActFSM`:

```python
round_num = getattr(entry.get("fsm"), "_round_num", 0) + 1
```

This is fragile: the attribute name `_round_num` is not part of the class's public API. If `ReActFSM` is refactored and the attribute is renamed, `send_message` will silently fall back to `0 + 1 = 1` on every call, causing all rounds to be reported with incorrect `round_num`. There is no type checking or IDE-level warning to prevent this.

**Fix:** Add a public property to `ReActFSM`:

```python
@property
def round_num(self) -> int:
    return self._round_num
```

Then use `entry["fsm"].round_num` in control.py.

---

### WR-07: Unsafe type cast in `SessionList.tsx` — `as unknown as Event[]` bypasses type checking

**File:** `frontend/src/components/SessionList.tsx:71`

**Issue:** Historical events loaded from the REST API are cast through `as unknown as Event[]`:

```typescript
detail.events as unknown as Event[]
```

This double cast completely bypasses TypeScript's type system. The REST API returns `events: Array<Record<string, unknown>>` (from `SessionDetail`), but the code silently assumes every object matches the discriminated `Event` union type. A mismatch between the backend's serialized event shape and the frontend's `Event` type definition will produce runtime errors (missing required fields, wrong `event_type` discriminators) that TypeScript should have caught at compile time.

**Fix:** Add runtime validation using a type guard or schema validator (e.g., Zod) for API boundary deserialization:

```typescript
function isEvent(obj: unknown): obj is Event {
  if (typeof obj !== "object" || obj === null) return false;
  const e = obj as Record<string, unknown>;
  return typeof e.event_type === "string" && typeof e.session_id === "string";
}

// Then filter: detail.events.filter(isEvent)
```

---

### WR-08: High cyclomatic complexity in `_handle_reason`

**File:** `src/loopai/state_machine/fsm.py:167-367`

**Issue:** The `_handle_reason` method is ~200 lines with 4 levels of nesting, an inline async closure (`_summary_fn`), 3 try/except branches, and 5 conditional checks (guard_pipeline, token_guard, budget_guard, tool_calls, budget warnings). The inline closure at lines 227-234 captures `self` and is defined on every call but only used when compression triggers. The `session.messages.clear()` + `session.messages.extend(compressed)` at lines 242-243 is a destructive operation on the session's message list that could lose all messages if `compressed` is empty (though currently guarded).

The high complexity makes it difficult to verify all state transitions are correct and increases the risk of future regressions.

**Fix:** Extract token guard and context compression logic into separate methods:

```python
async def _check_and_compress(self, session, step_num) -> bool:
    """Returns True if compression occurred."""
    ...
```

---

### WR-09: `_run_and_cleanup` does not await agent tasks during app shutdown

**File:** `src/loopai/api/app.py:28-31`

**Issue:** The `lifespan` shutdown handler sends `None` to all session queues and calls `bus.shutdown()`, but does not await the agent tasks stored in `app.state.active_sessions`. The `_run_and_cleanup` tasks are `asyncio.Task` objects that may be in the middle of an `fsm.run()` call or waiting on `queue.get()`. When the event loop begins shutting down, pending tasks may be cancelled before their `finally` blocks complete (publishing `session_end` events and cleaning up queue entries).

This means `session_end` events may be lost for in-flight sessions during server restart, leaving the frontend with a dangling "connected" session.

**Fix:** Gather and await all active agent tasks with a timeout during shutdown:

```python
# In lifespan shutdown:
for entry in app.state.active_sessions.values():
    task = entry.get("task")
    if task and not task.done():
        task.cancel()
# Wait briefly for tasks to finish cleanup
await asyncio.gather(
    *[t for t in tasks if not t.done()],
    return_exceptions=True,
)
```

---

### WR-10: `updateRounds` and `rebuildRounds` have inconsistent event handling logic

**File:** `frontend/src/stores/eventStore.ts:33-101`

**Issue:** The two round-grouping functions implement different rules for events arriving before the first `user_message`:

- **`updateRounds` (streaming path):** Returns `rounds` unchanged (empty array) for ALL event types except `user_message` when `rounds.length === 0`. Events before the first `user_message` are silently lost.

- **`rebuildRounds` (bulk load path):** Accumulates all events in `currentEvents` and flushes them into a round when a `user_message` or `round_end` is encountered. Events before the first `user_message` are preserved.

This inconsistency means the same sequence of events produces different round groupings depending on whether they arrive via SSE (streaming) or are loaded from the REST API (bulk load). A session viewed live will show different round boundaries than the same session loaded from history.

**Fix:** Align `updateRounds` with `rebuildRounds` behavior by handling events before the first `user_message` the same way:

```typescript
function updateRounds(rounds: RoundInfo[], event: Event): RoundInfo[] {
  // If no rounds exist and event is not user_message, handle like rebuildRounds
  if (rounds.length === 0 && event.event_type !== "user_message") {
    // ...accumulate or create implicit round...
  }
  // ...existing switch logic...
}
```

---

## Info

### IN-01: `_handle_reason` defines inline closure `_summary_fn` on every call

**File:** `src/loopai/state_machine/fsm.py:227-234`

**Issue:** The `_summary_fn` async closure is defined unconditionally inside `_handle_reason`, but only used when compression is triggered (line 237). In the common path (no compression needed), this closure is garbage-collected without ever being used.

**Fix:** Move the closure definition inside the `if tg_action == "compress" and self.compressor is not None:` block, or define it as a module-level coroutine that takes parameters.

---

### IN-02: Dead code — `session.state == AgentState.FINISH` handler in `_run_and_cleanup`

**File:** `src/loopai/api/routes/control.py:95-98`

**Issue:** The FINISH state is checked in `_run_and_cleanup` but `AgentState.FINISH` is never set by any FSM handler. All terminal transitions go to FINISH_WAIT or ERROR. The FINISH enum value exists for future use or external intervention but the handler in `_run_and_cleanup` is currently unreachable. This is misleading for future maintainers.

**Fix:** Either remove the dead branch, or document it as a planned extension point with a comment.

---

### IN-03: Magic number `2` for `_layer2_max_attempts`

**File:** `src/loopai/state_machine/fsm.py:101-102`

**Issue:** `_layer2_max_attempts = 2` is hardcoded. Layer 2 retry logic (tracked via `_layer2_retry_count`) currently has no runtime configuration path. This should be configurable or documented as a stub.

---

### IN-04: Missing return type annotations on several frontend functions

**File:** `frontend/src/stores/eventStore.ts:29-63`, `frontend/src/App.tsx:30-37`

**Issue:** Functions `updateRounds`, `rebuildRounds`, and `getAccumulatedText` lack explicit return type annotations. TypeScript infers them, but explicit annotations improve readability and catch logic errors at the definition site.

```typescript
function updateRounds(rounds: RoundInfo[], event: Event): RoundInfo[] { ... }
function getAccumulatedText(events: Event[]): string { ... }
```

---

## Files with No Issues Found

- `src/loopai/session/context.py` — Clean. The `AgentState` enum, `Session` dataclass, and `add_message`/`increment_step`/`record_tool_call` methods are correct.
- `src/loopai/events/schemas.py` — All 22 event models are structurally consistent. The `Event` discriminated union is correctly typed.
- `src/loopai/api/schemas.py` — Aside from the `SendMessageRequest.content` validation gap (WR-05), the schemas are clean.
- `frontend/src/lib/api.ts` — Correct fetch usage with proper error handling and `encodeURIComponent`.
- `frontend/src/stores/uiStore.ts` — Clean Zustand store with no logic errors.
- `tests/test_fsm.py` — Tests cover the correct state transitions and assertions. No reliability issues found.

---

_Reviewed: 2026-05-30T10:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
