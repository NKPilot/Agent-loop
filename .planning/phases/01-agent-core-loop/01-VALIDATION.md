---
phase: 01
slug: agent-core-loop
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-27
---

# Phase 01 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest + pytest-asyncio |
| **Config file** | none — Wave 0 creates pyproject.toml |
| **Quick run command** | `python -m pytest tests/ -x --timeout=10` |
| **Full suite command** | `python -m pytest tests/ -v --cov=loopai --cov-report=term-missing` |
| **Estimated runtime** | ~15 seconds (quick) / ~30 seconds (full) |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/ -x --timeout=10`
- **After every plan wave:** Run `python -m pytest tests/ -v --cov=loopai --cov-report=term-missing`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 01-01-01 | 01 | 1 | CORE-01 | — | FSM transitions REASON→FINISH when no tool_calls | unit | `pytest tests/test_fsm.py::test_reason_to_finish_no_tool_calls -x` | ❌ W0 | ⬜ pending |
| 01-01-02 | 01 | 1 | CORE-01 | — | Full REASON→ACT→OBSERVE→REASON cycle | unit | `pytest tests/test_fsm.py::test_full_react_cycle -x` | ❌ W0 | ⬜ pending |
| 01-01-03 | 01 | 1 | CORE-01 | — | Unhandled exception → ERROR | unit | `pytest tests/test_fsm.py::test_error_state_on_exception -x` | ❌ W0 | ⬜ pending |
| 01-01-04 | 01 | 1 | CORE-02 | T-01-01 | API key from env var only, never hardcoded | unit | `pytest tests/test_llm_client.py::test_client_configuration -x` | ❌ W0 | ⬜ pending |
| 01-01-05 | 01 | 1 | CORE-02 | T-01-01 | Configurable base_url and model | integration | `pytest tests/test_llm_client.py::test_chat_completion -x` | ❌ W0 | ⬜ pending |
| 01-01-06 | 01 | 1 | CORE-03 | — | llm_token events emitted for content deltas | unit | `pytest tests/test_event_bus.py::test_llm_token_streaming -x` | ❌ W0 | ⬜ pending |
| 01-01-07 | 01 | 1 | CORE-03 | — | step_start and step_end bracket each cycle | unit | `pytest tests/test_fsm.py::test_step_events_emitted -x` | ❌ W0 | ⬜ pending |
| 01-01-08 | 01 | 1 | CORE-04 | — | 80% budget warning injected into messages | unit | `pytest tests/test_guards.py::test_budget_warning_at_80_percent -x` | ❌ W0 | ⬜ pending |
| 01-01-09 | 01 | 1 | CORE-04 | — | Budget exhausted → final summary opportunity | unit | `pytest tests/test_guards.py::test_budget_exhausted_final_summary -x` | ❌ W0 | ⬜ pending |
| 01-01-10 | 01 | 1 | CORE-05 | T-01-04 | Orphan tool_call rejected before LLM send | unit | `pytest tests/test_guards.py::test_orphan_tool_call_rejected -x` | ❌ W0 | ⬜ pending |
| 01-01-11 | 01 | 1 | CORE-05 | T-01-04 | Valid alternating messages pass validation | unit | `pytest tests/test_guards.py::test_valid_messages_pass -x` | ❌ W0 | ⬜ pending |
| 01-01-12 | 01 | 1 | CORE-06 | — | 3 consecutive same tool calls → warning | unit | `pytest tests/test_guards.py::test_loop_detection_warns_at_3 -x` | ❌ W0 | ⬜ pending |
| 01-01-13 | 01 | 1 | CORE-06 | — | 5 consecutive same tool calls → blocked | unit | `pytest tests/test_guards.py::test_loop_detection_blocks_at_5 -x` | ❌ W0 | ⬜ pending |
| 01-01-14 | 01 | 1 | CORE-07 | T-01-05 | Log file created on session start with 0o600 | unit | `pytest tests/test_jsonl_logger.py::test_log_file_created -x` | ❌ W0 | ⬜ pending |
| 01-01-15 | 01 | 1 | CORE-07 | T-01-05 | Each event → one JSON line, correct format | unit | `pytest tests/test_jsonl_logger.py::test_event_to_line_mapping -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/conftest.py` — Shared fixtures: mock EventBus, mock AsyncOpenAI, test Session
- [ ] `tests/test_fsm.py` — CORE-01 state machine transitions (6 test cases)
- [ ] `tests/test_event_bus.py` — CORE-03 event pub/sub, fan-out, ordering, shutdown (5 test cases)
- [ ] `tests/test_guards.py` — CORE-04 budget, CORE-05 message validation, CORE-06 loop detection (8 test cases)
- [ ] `tests/test_jsonl_logger.py` — CORE-07 log file creation, format, append (4 test cases)
- [ ] `tests/test_llm_client.py` — CORE-02 configuration, mock responses (3 test cases)
- [ ] `tests/test_cli_renderer.py` — Rich renderable output (3 test cases)
- [ ] `uv pip install pytest pytest-asyncio pytest-cov pytest-timeout` — Framework install
- [ ] `pyproject.toml` — Configure asyncio mode, test paths, timeouts

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| CLI live display renders correctly | CORE-03 | Rich terminal output capture is fragile; visual inspection needed | Run agent with `--verbose`, verify step panels render in terminal |
| OpenAI API key from env var | CORE-02 | Cannot test actual env var reading in automated tests without leaking key | Manual: unset `OPENAI_API_KEY`, verify error message; set it, verify agent starts |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
