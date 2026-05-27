---
phase: 01-agent-core-loop
plan: 04
subsystem: consumers
tags: [jsonl-logger, cli-renderer, event-bus, observability, rich]
requires: [01-01 (EventBus + Schemas)]
provides: [JSONLLogger, CLIAgentRenderer]
affects: [CORE-07, CORE-03]
tech-stack:
  added: []
  patterns:
    - "Append-only JSONL session logging (1:1 event-to-line mapping)"
    - "Rich Live atomic full-rebuild Layout rendering"
    - "Event Bus consumer pattern (subscribe, consume loop, None sentinel shutdown)"
key-files:
  created:
    - src/loopai/consumers/__init__.py
    - src/loopai/consumers/jsonl_logger.py
    - src/loopai/consumers/cli_renderer.py
    - tests/test_jsonl_logger.py
    - tests/test_cli_renderer.py
  modified: []
decisions:
  - "D-10: 1:1 event-to-line mapping confirmed in JSONLLogger._write()"
  - "D-11: File naming YYYY-MM-DD_{session_id}.jsonl confirmed for per-session isolation"
  - "D-03: Dual-granularity display (step panels + token streaming + tool cards) in CLIAgentRenderer"
  - "RESEARCH.md Trap 5: Atomic full-rebuild Layout updates via live.update(), no incremental panel updates"
  - "Tool call lifecycle tracking via list of dicts with status field (starting/receiving args/executing/done/error)"
metrics:
  duration: "~2 minutes"
  completed_date: "2026-05-27T12:43:47Z"
---

# Phase 01 Plan 04: Event Bus Consumers Summary

**One-liner:** JSONL Logger with per-session append-only persistence and Rich Live CLI renderer with atomic full-rebuild display -- both as independent Event Bus consumers.

## Tasks Executed

| Task | Name | Type | Commit | Tests |
|------|------|------|--------|-------|
| 1 | JSONL Logger Consumer | feat | `75d9a40` | 7 passed |
| 2 | CLI Renderer Consumer | feat | `55f082a` | 19 passed |

## What Was Built

### JSONL Logger (`jsonl_logger.py`)

Per-session event persistence consumer that writes every Event Bus event as one JSON line to disk:
- File format: `logs/sessions/YYYY-MM-DD_{session_id}.jsonl` (D-11)
- Security: file permissions `0o600`, directory `0o700`
- Durability: `flush()` after each write, `os.fsync()` on stop
- Append-only mode for crash-resilient audit trail
- None sentinel clean shutdown
- Entry fields: `seq`, `ts` (ISO 8601 UTC), `session_id`, plus all event fields

### CLI Renderer (`cli_renderer.py`)

Terminal display consumer rendering agent activity via Rich Live:
- Dual-granularity display (D-03): step progress panel, Markdown-rendered thinking content, tool call cards
- Atomic full-rebuild Layout updates (RESEARCH.md Trap 5 mitigation)
- Rich Live with `transient=True`, `refresh_per_second=10`
- Handles all 13 event types: step lifecycle, streaming tokens, tool call lifecycle, budget/error/loop guard events
- Tool call lifecycle states: `starting` -> `receiving args` -> `executing` -> `done`/`error`

## Verification

```
26 passed in 0.13s
```

- `python -m pytest tests/test_jsonl_logger.py tests/test_cli_renderer.py -v` -- 26/26 passing
- `python -c "from loopai.consumers.jsonl_logger import JSONLLogger; from loopai.consumers.cli_renderer import CLIAgentRenderer; print('Consumer imports OK')"` -- OK

## Deviations from Plan

None -- plan executed exactly as written.

## Known Stubs

None -- both consumers are fully functional with all data wired from Event Bus events.

## Threat Model Compliance

| Threat ID | Mitigation | Status |
|-----------|-----------|--------|
| T-04-01 (Info Disclosure) | File 0o600, directory 0o700 | Implemented |
| T-04-02 (Tampering) | Append-only mode | Implemented |
| T-04-03 (DoS) | Bounded queue (maxsize=256) in EventBus | Accepted |
| T-04-04 (Info Disclosure) | api_key excluded from event data | Relies on upstream (LLMClient) |

## Self-Check: PASSED

- [x] `src/loopai/consumers/__init__.py` exists
- [x] `src/loopai/consumers/jsonl_logger.py` exists
- [x] `src/loopai/consumers/cli_renderer.py` exists
- [x] `tests/test_jsonl_logger.py` exists
- [x] `tests/test_cli_renderer.py` exists
- [x] Commit `75d9a40` found
- [x] Commit `55f082a` found
- [x] 26/26 tests passing
