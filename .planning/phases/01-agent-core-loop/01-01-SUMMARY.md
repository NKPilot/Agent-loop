---
phase: 01-agent-core-loop
plan: 01
subsystem: events
tags: [event-bus, pydantic, asyncio, infrastructure]
requires: []
provides: [EventBus, Event schemas, test fixtures]
affects: [01-02, 01-03, 01-04, 01-05]
tech-stack:
  added: [pydantic 2.13.4 (event models), asyncio.Queue (pub/sub backbone)]
  patterns: [Discriminated Union, Publish/Subscribe, Bounded Queue Backpressure]
key-files:
  created:
    - pyproject.toml (project config, deps, pytest/ruff settings)
    - src/loopai/events/schemas.py (13 pydantic event models with discriminated union)
    - src/loopai/events/bus.py (EventBus class with asyncio.Queue pub/sub)
    - tests/conftest.py (shared pytest fixtures)
    - tests/test_schemas.py (6 schema tests)
    - tests/test_event_bus.py (10 EventBus tests)
    - .gitignore (Python/build artifact exclusions)
  modified: []
decisions:
  - "Event schemas use pydantic v2 BaseModel with Literal event_type discriminators"
  - "EventBus uses put_nowait + QueueFull warning for backpressure (non-blocking)"
  - "Event union type: Annotated[... | Error, Field(discriminator='event_type')]"
  - "Wildcard subscription '*' for consumers that need all events"
  - "JSON serializability validated at publish() boundary (TypeError on non-serializable)"
  - "event_type consistency enforced: publish() topic must match event_data['event_type']"
metrics:
  duration: ~8min
  completed_date: "2026-05-27"
---

# Phase 1 Plan 1: Project Skeleton and Event Bus Foundation

Establish the project skeleton and Event Bus backbone -- the communication spine that all other Phase 01 components depend on. The Event Bus with typed pydantic schemas is the nervous system of the entire system: FSM publishes events, and each consumer (CLI, JSONL, future SSE) subscribes independently.

## Execution Summary

All 4 tasks executed successfully in a fully autonomous wave. The project directory structure, pyproject.toml with pinned dependencies (openai 2.38.0, pydantic 2.13.4, rich 15.0.0, httpx 0.28.1), 13 pydantic event models with discriminated union, asyncio.Queue-based EventBus with publish/subscribe/fan-out/replay/shutdown, and shared pytest fixtures were built and tested. 16 tests pass (6 schema + 10 EventBus).

## Completed Tasks

| # | Task | Type | Commit | Result |
|---|------|------|--------|--------|
| 1 | Create project skeleton with pyproject.toml | auto | d89b776 | Directory structure, pyproject.toml, __init__.py files, all deps installed |
| 2 | Define all 13 event pydantic models | auto | 2903eaf | EventBase + 12 concrete models, discriminated Event union type, 6 passing tests |
| 3 | Implement EventBus with asyncio.Queue pub/sub | auto | f12d69f | publish/subscribe/unsubscribe/replay/shutdown, 10 passing tests |
| 4 | Create conftest.py with shared fixtures | auto | ea49415 | 6 shared fixtures (event_bus, sample_session_id, 4 sample events) |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Validation] Added event_type mismatch test**
- **Found during:** Task 3 implementation
- **Issue:** The publish() method validates that event_data["event_type"] matches the publish topic, but no test covered this validation path
- **Fix:** Added `test_event_type_mismatch` test case verifying ValueError is raised on mismatch
- **Files modified:** tests/test_event_bus.py
- **Commit:** f12d69f

**2. [Rule 2 - Missing Configuration] Added .gitignore for build artifacts**
- **Found during:** Post-execution cleanup
- **Issue:** __pycache__/ and *.egg-info/ directories were untracked, risking accidental commits of build artifacts
- **Fix:** Created .gitignore with standard Python exclusions
- **Files modified:** .gitignore (new)
- **Commit:** (included in final metadata commit)

### Plan Adherence

None of the plan's specified files, models, or acceptance criteria were modified. All 13 event types, 9 EventBus methods, and 6 conftest fixtures are exactly as specified. The plan executed exactly as written with the two minimal Rule 2 additions above.

## Verification Results

**Combined test suite:** 16/16 passing
```
tests/test_schemas.py::TestStepStartCreation::test_step_start_creation PASSED
tests/test_schemas.py::TestLLMTokenCreation::test_llm_token_creation PASSED
tests/test_schemas.py::TestToolCallDoneFullArgs::test_tool_call_done_full_args_type PASSED
tests/test_schemas.py::TestEventDiscriminatedUnion::test_event_discriminated_union PASSED
tests/test_schemas.py::TestAllEventsUniqueType::test_all_events_have_unique_type PASSED
tests/test_schemas.py::TestJsonSerialization::test_json_serialization PASSED
tests/test_event_bus.py::test_publish_subscribe_single_topic PASSED
tests/test_event_bus.py::test_fan_out_multiple_subscribers PASSED
tests/test_event_bus.py::test_wildcard_subscription PASSED
tests/test_event_bus.py::test_replay_history PASSED
tests/test_event_bus.py::test_replay_by_topic PASSED
tests/test_event_bus.py::test_unsubscribe PASSED
tests/test_event_bus.py::test_shutdown_sentinel PASSED
tests/test_event_bus.py::test_bounded_queue_backpressure PASSED
tests/test_event_bus.py::test_invalid_event_data PASSED
tests/test_event_bus.py::test_event_type_mismatch PASSED
```

**pyproject.toml validation:** Valid TOML, all pinned versions resolved correctly.

**fixture importability:** All 6 conftest fixtures importable from module scope.

## Threat Coverage

All 4 threats from the plan's threat model are addressed:

| Threat | Disposition | Implementation |
|--------|-------------|---------------|
| T-01-01 (API key leakage) | Mitigated | No secrets in any file; OPENAI_API_KEY from env only |
| T-01-02 (DoS via queue) | Mitigated | Bounded queues (maxsize=256); QueueFull triggers warning + drop |
| T-01-03 (Data tampering) | Mitigated | JSON serializability validation at publish() boundary; TypeError on non-serializable |
| T-01-04 (PII in events) | Accepted | Event schemas contain no PII fields; JSONL logger (Plan 04) will handle file permissions |

## Known Stubs

None. All models, methods, and fixtures are fully implemented.

## Threat Flags

None. No new security surface beyond what was documented in the plan's threat model.

## Self-Check: PASSED

- [x] pyproject.toml exists at repo root
- [x] src/loopai/events/schemas.py exists (13 models, ~180 lines)
- [x] src/loopai/events/bus.py exists (EventBus class, ~120 lines)
- [x] tests/conftest.py exists (6 fixtures)
- [x] tests/test_schemas.py exists (6 test cases)
- [x] tests/test_event_bus.py exists (10 test cases)
- [x] Commit d89b776: project skeleton
- [x] Commit 2903eaf: event schemas
- [x] Commit f12d69f: EventBus
- [x] Commit ea49415: conftest fixtures
