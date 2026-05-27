---
phase: "02-tool-system-biz-validation"
plan: "01"
subsystem: "tools"
tags: ["types", "decorator", "registry", "executor", "errors", "retry"]
requires: ["phase-01-event-bus", "phase-01-fsm"]
provides: ["tool-types", "tool-decorator", "tool-registry", "tool-executor"]
affects: ["future-bash-tools", "future-permission-system", "future-fsm-integration"]
tech-stack:
  added: ["Pydantic create_model", "asyncio.to_thread", "asyncio.wait_for", "StrEnum"]
  patterns: ["TDD (RED/GREEN/REFACTOR)", "per-task atomic commits", "Pydantic model-based validation"]
key-files:
  created:
    - "src/loopai/tools/__init__.py"
    - "src/loopai/tools/types.py"
    - "src/loopai/tools/decorator.py"
    - "src/loopai/tools/registry.py"
    - "src/loopai/tools/executor.py"
    - "src/loopai/tools/errors.py"
  modified:
    - "tests/test_tools.py"
decisions:
  - "StrEnum used for ErrorCategory/PermissionLevel instead of (str, Enum) per ruff UP042"
  - "ToolMetadata.error field renamed to error_message to avoid Pydantic name collision with classmethod"
  - "Decorator wrapper validates on call (sync/async transparent); executor adds timeout + retry on top"
metrics:
  duration: "9m"
  completed_date: "2026-05-27"
---

# Phase 2 Plan 1: Tool System Core Foundation Summary

Implemented the foundational tool system layer: type definitions, @tool decorator with
auto-generated JSON Schema, instance-based ToolRegistry, execution pipeline with timeout
and error classification, and exponential-backoff retry for transient errors.

## TDD Gate Compliance

Three full RED/GREEN cycles executed:

| Gate | Task | RED commit | GREEN commit |
|------|------|-----------|-------------|
| RED-1 | Types | `bcdb923` | `b6c9873` |
| RED-2 | Decorator + Registry | `fc4051b` | `58ffae5` |
| RED-3 | Executor + Errors | `59d7592` | `f8b9afe` |

All RED phases confirmed failing before GREEN implementation.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] ToolResult.error field vs classmethod name collision**
- **Found during:** Task 1 GREEN
- **Issue:** Pydantic field `error` collided with classmethod `error()`, causing
  `result.error` to return a bound method instead of the error string.
- **Fix:** Renamed field to `error_message`; classmethod `ToolResult.error()` remains
  as the factory API per plan spec. Tests updated accordingly.
- **Files modified:** `src/loopai/tools/types.py`, `tests/test_tools.py`
- **Commit:** `b6c9873`

**2. [Rule 1 - Bug] Positional argument validation failure**
- **Found during:** Task 2 GREEN
- **Issue:** Decorator wrapper only validated keyword arguments (`**kwargs`),
  but tests called decorated functions with positional args (e.g., `my_helper("hello")`).
- **Fix:** Added `_merge_args_kwargs()` helper that maps positional args to
  parameter names from the function signature before validation.
- **Files modified:** `src/loopai/tools/decorator.py`
- **Commit:** `58ffae5`

**3. [Rule 3 - Blocking] Ruff linting issues**
- **Found during:** Task 3 completion (post-implementation linting)
- **Issue:** 13 ruff violations including unused imports (`math`, `get_type_hints`,
  `Enum`), `Callable` from wrong module, long line, `asyncio.TimeoutError` aliasing,
  and `str, Enum` instead of `StrEnum`.
- **Fix:** Applied automatic and manual fixes for all violations. Converted
  `ErrorCategory`/`PermissionLevel` to `StrEnum`, fixed imports, split long line.
- **Files modified:** All 5 tool modules
- **Commit:** `eb00bfa`

## Verification Results

- **Unit tests:** 120/120 passed (95 Phase 1 + 25 new test_tools.py)
- **Phase 1 regression:** No regressions detected
- **Ruff linting:** All checks passed (0 errors)
- **Line count minimums:** All exceeded (types: 214/60, decorator: 300+/120,
  registry: 132/80, executor: 225+/100, errors: 87/40)

## Threat Mitigation Status

| Threat | Disposition | Status |
|--------|-------------|--------|
| T-02-01 (Tampering - decorator) | mitigate | Pydantic validation on every call + executor-side validation |
| T-02-02 (Elevation of Privilege - executor) | mitigate | FATAL errors re-raise to terminate session |
| T-02-03 (Denial of Service - executor) | mitigate | Per-tool timeout + max_attempts cap + max_delay ceiling |
| T-02-04 (Information Disclosure - types) | mitigate | func_ref + validation_model excluded via Field(exclude=True) |

## Self-Check

All files verified present and commits confirmed:

- [x] `src/loopai/tools/__init__.py` — created, committed
- [x] `src/loopai/tools/types.py` — 214 lines, committed
- [x] `src/loopai/tools/decorator.py` — 300+ lines, committed
- [x] `src/loopai/tools/registry.py` — 132 lines, committed
- [x] `src/loopai/tools/executor.py` — 225+ lines, committed
- [x] `src/loopai/tools/errors.py` — 87 lines, committed
- [x] `tests/test_tools.py` — 633 lines, 25 tests, committed
- [x] No stubs detected
- [x] No new threat surfaces beyond documented threat model
