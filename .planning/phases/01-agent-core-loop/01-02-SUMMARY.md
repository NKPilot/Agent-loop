---
phase: 01-agent-core-loop
plan: "02"
subsystem: agent-loop
tags: [pydantic, guards, loop-detection, budget-enforcement, message-validation, tdd]

# Dependency graph
requires: []
provides:
  - BudgetGuard class with step budget enforcement (80% warn, 100% final summary, unreachable detection)
  - LoopDetector class with SHA256-based deterministic signature matching and 3-level escalation
  - MessageValidator class with strict tool_call/tool_result pairing validation
  - AgentConfig pydantic model with env var and CLI flag loading
  - load_config() function with CLI-over-env priority
affects:
  - 01-fsm (state machine guards integration)
  - 01-agent-loop (main loop will import all three guards + config)

# Tech tracking
tech-stack:
  added:
    - pydantic 2.13.4 (SecretStr for API key masking, BaseModel for config)
    - argparse (CLI flag registration via add_cli_args helper)
    - hashlib.sha256 (deterministic loop detection signatures)
    - collections.deque (sliding window with auto-eviction)
    - pytest 9.0.3 (test framework)
    - pytest-asyncio 1.4.0 (async test support)
  patterns:
    - Guard pattern: independent safety net classes, zero dependency on EventBus or LLM Client
    - SecretStr masking: api_key hidden in repr/str/model_dump via pydantic SecretStr
    - TDD RED/GREEN/REFACTOR: each guard class written test-first
    - Immutable output: BudgetGuard.check() always returns message list copy

key-files:
  created:
    - src/loopai/config.py (129 lines) — AgentConfig + load_config + add_cli_args
    - src/loopai/state_machine/guards.py (258 lines) — BudgetGuard, LoopDetector, MessageValidator, ValidationError
    - tests/test_config.py (158 lines) — 11 config tests
    - tests/test_guards.py (442 lines) — 25 guard tests
    - pyproject.toml — project metadata, pytest/asyncio config
    - .gitignore — Python cache, venv, env files
  modified: []

key-decisions:
  - "Strict message validation: reject orphan tool_calls with ValidationError containing specific tool_call_id, per RESEARCH.md open question #2 recommendation"
  - "BudgetGuard always returns message list copies (never mutates input), ensuring thread safety and caller predictability"
  - "LoopDetector escalation: warn at 3 consecutive identical calls, block at 5, force_exit at 6+ after block persists"
  - "check_unreachable() triggers at 3+ consecutive failures per D-08, with success resetting the counter"
  - "max_steps only overridable via CLI (--max-steps), not from environment variable — keeps budget control explicit"

patterns-established:
  - "Guard Pattern: independent classes with no shared state, each handling one failure mode (budget/loop/validation)"
  - "TDD Gate: test file created before implementation, RED commit (failing tests) -> GREEN commit (passing impl) -> REFACTOR commit (edge cases)"
  - "SecretStr for credentials: pydantic SecretStr ensures api_key never appears in logs, repr, or serialization output"
  - "Copy-on-read for mutable inputs: BudgetGuard.check() returns list(messages) + [new_msg], never modifies original"

requirements-completed:
  - CORE-04
  - CORE-05
  - CORE-06

# Metrics
duration: 7min
completed: 2026-05-27
---

# Phase 01 Plan 02: Guards and Config Summary

**BudgetGuard with step enforcement, LoopDetector with SHA256 signature escalation, and MessageValidator with strict tool_call pairing — all TDD with 36 passing tests**

## Performance

- **Duration:** 7 min
- **Started:** 2026-05-27T12:24:00Z
- **Completed:** 2026-05-27T12:31:00Z
- **Tasks:** 3
- **Files modified:** 6 created, 0 modified

## Accomplishments
- AgentConfig pydantic model loads LLM settings from environment variables with CLI flag overrides, api_key masked via SecretStr
- LoopDetector catches infinite tool-calling loops with 3-level escalation (warn/block/force_exit) using deterministic SHA256 signatures
- MessageValidator enforces strict tool_call/tool_result pairing, rejecting orphaned calls with specific error messages
- BudgetGuard enforces step budget with 80% warning injection and final summary opportunity at exhaustion
- 36 tests pass (11 config + 25 guards) covering all acceptance criteria and edge cases

## Task Commits

Each task was committed atomically:

1. **Task 1: AgentConfig with env var + CLI loading** — `a2b4e8f` (feat)
2. **Task 2: LoopDetector + MessageValidator (TDD)** — `c3a6b43` test, `62b400e` feat, `edf964d` refactor
3. **Task 3: BudgetGuard (TDD)** — `915626b` test, `826fc03` feat

**Plan metadata:** (to be committed after SUMMARY.md creation)

## Files Created/Modified
- `src/loopai/config.py` — AgentConfig model, load_config(), add_cli_args() helper
- `src/loopai/state_machine/guards.py` — BudgetGuard, LoopDetector, MessageValidator, ValidationError
- `tests/test_config.py` — 11 tests: env loading, CLI override, defaults, validation, key masking
- `tests/test_guards.py` — 25 tests: 7 LoopDetector + 6 MessageValidator + 8 BudgetGuard + 4 edge cases
- `pyproject.toml` — Project config with pytest asyncio_mode=auto, pythonpath=src
- `.gitignore` — Python cache, venv, env files, IDE files

## Decisions Made
- Used `hashlib.sha256` with `json.dumps(sort_keys=True)` for deterministic loop signatures — Python's `hash()` is per-process randomized
- Implemented strict validation (reject orphans with ValidationError) rather than tolerant auto-fix — per RESEARCH.md recommendation that auto-fix masks agent logic bugs
- BudgetGuard returns message list copies via `list(messages) + [new_msg]` — never mutates input, safe for concurrent access patterns
- warn_pct default 0.80 with `int(max_steps * warn_pct)` threshold calculation — matches D-09 80% budget warning spec
- check_unreachable uses simple consecutive failure counter with success reset — clean implementation of D-08 system-level unreachable detection

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Added .gitignore for Python generated files**
- **Found during:** Post-execution cleanup
- **Issue:** `__pycache__/` directories from pytest runs were untracked; no .gitignore existed
- **Fix:** Created .gitignore with Python, venv, IDE, and env file patterns
- **Files modified:** .gitignore (created)
- **Verification:** git status no longer shows pycache as untracked
- **Committed in:** Will be committed alongside SUMMARY.md

**2. [Rule 1 - Bug] Fixed test_default_values missing API key**
- **Found during:** Task 1 verification
- **Issue:** `test_default_values` deleted OPENAI_BASE_URL and OPENAI_MODEL env vars but didn't set OPENAI_API_KEY, causing ValidationError
- **Fix:** Added `monkeypatch.setenv("OPENAI_API_KEY", "sk-test-default")` before testing defaults
- **Files modified:** tests/test_config.py
- **Verification:** Test passes after fix
- **Committed in:** a2b4e8f (Task 1 commit)

---

**Total deviations:** 2 auto-fixed (1 missing critical, 1 bug)
**Impact on plan:** Both fixes essential for correctness. No scope creep.

## Issues Encountered
- `uv pip install --system` failed due to externally-managed-environment on Ubuntu — switched to `uv venv` + activate workflow
- `python -c "from loopai..."` import failed without PYTHONPATH — tests pass via pyproject.toml `pythonpath = ["src"]` config

## Threat Model Verification

All four threat mitigations from the plan's threat model are implemented:

| Threat ID | Mitigation | Status |
|-----------|-----------|--------|
| T-02-01 (Info Disclosure) | SecretStr + custom repr masking | Verified via test_api_key_not_in_repr |
| T-02-02 (DoS) | BudgetGuard enforces max_steps, "final" action regardless of LLM behavior | Verified via test_step_equal_max_final_summary |
| T-02-03 (Spoofing) | Strict orphan detection prevents tool_result injection without matching tool_call | Verified via test_orphan_tool_call_rejected |
| T-02-04 (Privilege Escalation) | sha256 used only for deterministic comparison, not security | Accepted risk, noted in threat model |

## Known Stubs

None — all implemented guards and config classes are fully functional with complete logic and no placeholder values.

## Next Phase Readiness
- All three guards independently tested and ready for FSM integration (Plan 01-03)
- AgentConfig ready for LLM client construction with type-safe configuration
- Zero dependencies on EventBus or LLM Client — guards can be wired into any state machine loop

---
*Phase: 01-agent-core-loop*
*Plan: 02 — Guards and Config*
*Completed: 2026-05-27*
