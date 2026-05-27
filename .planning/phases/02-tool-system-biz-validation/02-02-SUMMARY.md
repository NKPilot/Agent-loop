---
phase: 02-tool-system-biz-validation
plan: 02
subsystem: tools
tags: [bash, security, command-classification, permission-guard]
requires: [02-01]
provides:
  - CommandClassifier (whitelist/blacklist + path-aware escalation)
  - BashTool (safe subprocess execution with shell=False)
  - PermissionGuard (dangerous command confirmation via EventBus)
affects: [src/loopai/tools/command_classifier.py, src/loopai/tools/bash.py, src/loopai/state_machine/guards.py]
tech-stack:
  added: [shlex, subprocess, asyncio, re]
  patterns:
    - TDD (RED/GREEN) for all three tasks
    - PermissionLevel-based command gating
    - EventBus-driven confirmation flow for dangerous commands
    - Path-aware security escalation (SAFE -> MODERATE -> DANGEROUS)
key-files:
  created:
    - src/loopai/tools/command_classifier.py (244 lines)
    - src/loopai/tools/bash.py (307 lines)
    - tests/test_bash_tool.py (46 tests, ~530 lines)
  modified:
    - src/loopai/state_machine/guards.py (+178 lines: PermissionGuard class)
decisions:
  - "Command classification ordered as: shell meta check -> blacklist -> pattern scan -> path escalation -> whitelist -> conservative default"
  - "Shell metacharacters checked TWICE: once in classifier (returns MODERATE) and once in BashTool (returns error, hard block)"
  - "PermissionGuard does NOT classify commands itself — receives pre-classified PermissionLevel from BashTool"
  - "confirmation_id format: {session_id}_{tool_name}_{step_num}"
  - "PermissionGuard timeout publishes confirmation_timeout event for audit trail"
metrics:
  duration: ""
  completed_date: "2026-05-27"
  task_count: 3
  file_count: 4
  test_count: 46
---

# Phase 2 Plan 2: Bash 安全执行层 Summary

构建 Bash/Shell 工具的安全执行层：命令白名单/黑名单分类器（路径感知的危险级别判定）、安全的 subprocess 执行封装、PermissionGuard 守卫。

## Tasks Completed

| Task | Name | Type | Files | Commit |
|------|------|------|-------|--------|
| 1 | CommandClassifier (RED) | test | tests/test_bash_tool.py | `5b8bfe5` |
| 1 | CommandClassifier (GREEN) | feat | src/loopai/tools/command_classifier.py | `327b251` |
| 2 | BashTool (RED) | test | tests/test_bash_tool.py | `8d9094b` |
| 2 | BashTool (GREEN) | feat | src/loopai/tools/bash.py | `f0549b1` |
| 3 | PermissionGuard (RED) | test | tests/test_bash_tool.py | `566b424` |
| 3 | PermissionGuard (GREEN) | feat | src/loopai/state_machine/guards.py | `10292de` |

## Key Deliverables

### 1. CommandClassifier (`command_classifier.py`)
- **13 SAFE commands**: ls, df, du, find, cat, head, tail, wc, grep, sort, uniq, echo, stat
- **9 DANGEROUS commands**: rm, dd, mkfs, shred, fdisk, mkfs.ext4, mkfs.xfs, mkfs.btrfs, mkswap
- **3 DANGEROUS patterns**: `> /dev/`, `chmod 777 /`, `chown <user> /`
- **14 SYSTEM_PATHS**: /etc, /dev, /sys, /proc, /boot, /usr, /lib, /lib64, /bin, /sbin, /var, /root, /opt
- **Path-aware escalation**: SAFE + system_path -> MODERATE; MODERATE + system_path -> DANGEROUS
- **Shell metacharacter detection**: pipe (`|`), cmd substitution (`$()`, backtick), logic ops (`&&`, `||`), semicolon (`;`) -> MODERATE (conservative)
- **Chinese-language reason strings** for all classifications

### 2. BashTool (`bash.py`)
- `subprocess.run()` with `shell=False` + argument list (never a string)
- `shlex.split()` for safe command string parsing
- CommandClassifier integration for permission level classification
- Shell metacharacter interception (hard block, returns error)
- `asyncio.wait_for()` timeout control (default 60s per D-07)
- Output truncation at 100KB (configurable via `max_output_bytes`)
- `create_bash_tool()` factory returns `@tool`-decorated callable with `__tool_meta__`

### 3. PermissionGuard (`guards.py`)
- SAFE/MODERATE commands pass through immediately
- DANGEROUS commands: publish `confirmation_required` event via EventBus, block via `asyncio.Event`
- `respond(confirmation_id, approved)` for CLI/frontend consumers
- Configurable `confirmation_timeout` (default 120s)
- Timeout auto-denies, publishes `confirmation_timeout` event
- `confirmation_response` events for audit trail (D-09, T-02-09)

## Test Results

```
166 passed in 5.56s  (full suite — zero regressions)
 46 passed in 1.42s  (test_bash_tool.py specifically)
```

All Phase 1 tests continue to pass. 46 new tests added:
- Tests 1-9: CommandClassifier (32 parametrized variants)
- Tests 10-16 + bonus: BashTool (8 tests)
- Tests 17-22: PermissionGuard (6 tests)

## Deviations from Plan

None — plan executed exactly as written. All three tasks followed TDD (RED/GREEN) cycle. No auto-fixes needed.

## Requirements Satisfied

- **TOOL-03**: Bash/Shell 工具 (subprocess, shell=False, 超时控制)
- **TOOL-05**: 命令权限分级 (safe/moderate/dangerous) — CommandClassifier + path-aware escalation

## TDD Gate Compliance

All three tasks follow the TDD RED/GREEN cycle. Each plan file has a `test(...)` commit followed by a `feat(...)` commit:

| Task | RED commit | GREEN commit | Gates |
|------|-----------|--------------|-------|
| 1 | `5b8bfe5` | `327b251` | RED -> GREEN PASSED |
| 2 | `8d9094b` | `f0549b1` | RED -> GREEN PASSED |
| 3 | `566b424` | `10292de` | RED -> GREEN PASSED |

## Known Stubs

None. All implemented code is fully functional:
- CommandClassifier performs real path matching and pattern detection
- BashTool executes real subprocess commands
- PermissionGuard publishes real EventBus events and blocks on real asyncio.Events

## Threat Flags

No new threat surface beyond what is documented in the plan's `<threat_model>`. All six threats (T-02-05 through T-02-10) are mitigated as specified.

## Self-Check

- [x] `src/loopai/tools/command_classifier.py` exists and is committed
- [x] `src/loopai/tools/bash.py` exists and is committed
- [x] `src/loopai/state_machine/guards.py` modified with PermissionGuard
- [x] `tests/test_bash_tool.py` exists with 46 tests passing
- [x] All 6 commits in git log
- [x] Full test suite: 166 passed, 0 failed
- [x] No untracked files, no accidental deletions
