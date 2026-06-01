---
phase: 09-security-hardening
verified: 2026-06-01T22:51:00Z
status: gaps_found
score: 18/18 must-haves verified
overrides_applied: 0
gaps:
  - truth: "test_schemas.py 包含 4 个沙箱事件专用测试类（TestSandboxTimeoutSchema、TestSandboxViolationSchema、TestSandboxResourceExceededSchema、TestSandboxEventsDiscriminatedUnion）"
    status: partial
    reason: "09-01 GREEN 提交 (0194ca0) 添加了 4 个专用测试类并将事件类型计数从 22 更新为 25。09-02 GREEN 提交 (b7eb91b) 在处理 TDD RED→GREEN 流程时删除了所有沙箱事件测试引用，将计数降回 22。沙箱事件的 Pydantic 模型验证现在仅通过 sandbox executor 测试间接覆盖，失去了直接的 schema 单元测试。"
    artifacts:
      - path: "tests/test_schemas.py"
        issue: "SandboxTimeout/Violation/ResourceExceeded 不再出现在 TestAllEventsUniqueType 或 TestUpdatedEventTypeCount 中；4 个专用测试类已完全删除。计数为 22 而非 25。"
    missing:
      - "恢复 TestSandboxTimeoutSchema 类（验证实例化、字段类型、时间戳自动填充、JSON 序列化）"
      - "恢复 TestSandboxViolationSchema 类（验证 violation_type 3 值 Literal 约束、非法值拒绝）"
      - "恢复 TestSandboxResourceExceededSchema 类（验证 resource_type 3 值 Literal 约束、非法值拒绝）"
      - "恢复 TestSandboxEventsDiscriminatedUnion 类（验证 3 个新事件通过 Event 联合类型正确反序列化）"
      - "TestAllEventsUniqueType 和 TestUpdatedEventTypeCount 添加 SandboxTimeout/Violation/ResourceExceeded 到 event_classes 列表"
      - "TestAllEventsUniqueType 和 TestUpdatedEventTypeCount 计数更新为 25"
---

# Phase 9: 安全加固与沙箱隔离 Verification Report

**Phase Goal:** 安全加固与沙箱隔离——将基础 SandboxExecutor 升级为真正的安全边界：网络命名空间隔离、路径白名单校验、资源限制加固、沙箱违规审计事件
**Verified:** 2026-06-01T22:51:00Z
**Status:** gaps_found
**Re-verification:** No -- initial verification

## Goal Achievement

Phase goal is **achieved** -- all four requirements (DYN-11 through DYN-14) are implemented, tested, and working. One test-coverage regression gap exists (non-blocking).

### Observable Truths Assessment

| #   | Truth   | Status     | Evidence       |
| --- | ------- | ---------- | -------------- |
| 1   | SandboxTimeout 事件类已定义且包含所有必需字段 | VERIFIED | schemas.py:398-407 -- event_type, session_id, timestamp, step_num, tool_name, timeout_seconds |
| 2   | SandboxViolation 事件类已定义且包含 violation_type (3 值 Literal) 和 detail | VERIFIED | schemas.py:410-425 -- violation_type: path_escape, network_attempt, sensitive_path |
| 3   | SandboxResourceExceeded 事件类已定义且包含 resource_type (3 值 Literal) 和 limit/detail | VERIFIED | schemas.py:427-443 -- resource_type: memory, process, file_size |
| 4   | 三种新事件类型已加入 Python Event 区分联合类型 | VERIFIED | schemas.py:480-482 -- SandboxTimeout \| SandboxViolation \| SandboxResourceExceeded |
| 5   | TypeScript 前端事件类型已同步 | VERIFIED | eventTypes.ts:289-311 -- 3 个 interface + Event union (L388-390) + EVENT_TYPE_MAP (L427-429) |
| 6   | _build_cmd() 在 Linux 上返回 unshare 包装命令 | VERIFIED | sandbox.py:612-613 -- ["unshare", "--user", "--map-root-user", "--net"] + base_cmd |
| 7   | _build_cmd() 在非 Linux 上优雅降级 | VERIFIED | sandbox.py:593-594 -- 非 linux 直接返回 base_cmd |
| 8   | _validate_path() 使用 _safe_realpath + startswith 校验白名单 | VERIFIED | sandbox.py:658-696 -- 两阶段检查 (黑名单 + 白名单) |
| 9   | _set_limits() 设置 4 项 rlimit 硬限制 | VERIFIED | sandbox.py:754-810 -- RLIMIT_CPU(30,30), RLIMIT_AS(512MB), RLIMIT_NPROC(0,0), RLIMIT_FSIZE(100MB) |
| 10  | execute() 在 TimeoutExpired 时发布 sandbox_timeout 事件 | VERIFIED | sandbox.py:532-542 -- 捕获后条件发布到 event_bus |
| 11  | execute() 在路径校验失败时发布 sandbox_violation 事件并拒绝执行 | VERIFIED | sandbox.py:397-415 -- 校验失败返回 status="failed" + 发布事件 |
| 12  | execute() 在 stderr 检测到资源超限时发布 sandbox_resource_exceeded 事件 | VERIFIED | sandbox.py:493-523 -- _classify_violation 分类 + 条件发布 |
| 13  | 子进程网络连接被 unshare --net 阻断 | VERIFIED | test_network_isolation 测试通过；WSL2 Linux 环境验证阻断生效 |
| 14  | 子进程 os.fork() 因 RLIMIT_NPROC=0 被阻止 | VERIFIED | test_fork_bomb_prevented 测试通过 |
| 15  | DynamicToolCreator._stage4_self_test 使用加固沙箱 | VERIFIED | dynamic_creator.py:86-89 -- __init__ 关联 sandbox._event_bus = self._bus |
| 16  | DynamicToolCreator._make_func_ref 创建独立 SandboxExecutor(event_bus=None) | VERIFIED | dynamic_creator.py:604-605 -- 显式 event_bus=None |
| 17  | 自测阶段沙箱违规事件通过 EventBus 发布 | VERIFIED | test_stage4_uses_hardened_sandbox、test_stage4_timeout_publishes_event、test_stage4_path_validation 测试通过 |
| 18  | D-06 达成：自测在加固后的 SandboxExecutor 中运行，违规可被检测和审计 | VERIFIED | 4 个 D-06 集成测试全部通过 |

**Score:** 18/18 truths verified

### Requirements Coverage

| Requirement | Description | Status | Evidence |
| ----------- | ----------- | ------ | -------- |
| DYN-11 | 动态工具在独立子进程中执行（subprocess），与主进程隔离 | SATISFIED | sandbox.py execute() 使用 subprocess.run(shell=False)；test_subprocess_isolation 通过 |
| DYN-12 | resource.setrlimit 硬限制：CPU 时间、内存 512MB、超时 30s（可调至 120s） | SATISFIED | sandbox.py _set_limits() 设置 RLIMIT_CPU/AS/NPROC/FSIZE；5 个资源限制测试通过 |
| DYN-13 | 子进程禁止网络访问 | SATISFIED | sandbox.py _build_cmd() 注入 unshare --net；test_network_isolation 验证阻断；WSL2 Linux 实际阻断确认 |
| DYN-14 | 文件系统访问默认限于 .sandbox/tools_runtime/{tool_name}/，用户可在确认时授予额外目录 | SATISFIED | sandbox.py _validate_path() 使用 SANDBOX_ROOT + allowed_roots；test_path_whitelist_* 测试通过 |

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `src/loopai/events/schemas.py` | 3 个新事件类 + Event 联合类型更新 | VERIFIED | SandboxTimeout (L398), SandboxViolation (L410), SandboxResourceExceeded (L427), Event union (L480-482) |
| `frontend/src/lib/eventTypes.ts` | 3 个新 interface + Event union + EVENT_TYPE_MAP | VERIFIED | SandboxTimeoutEvent (L289), SandboxViolationEvent (L296), SandboxResourceExceededEvent (L304), Event union (L388-390), EVENT_TYPE_MAP (L427-429) |
| `src/loopai/tools/sandbox.py` | 加固后的 SandboxExecutor（6 个新方法/常量） | VERIFIED | _build_cmd (L568), _safe_realpath (L618), _validate_path (L659), _classify_violation (L701), _set_limits (L755), DENY_PATTERNS (L43), SANDBOX_ROOT (L54) |
| `tests/tools/test_sandbox.py` | 30 个测试用例覆盖 DYN-11~DYN-14 | VERIFIED | 746 行，30 个测试函数全部通过 |
| `src/loopai/tools/dynamic_creator.py` | D-06 集成：event_bus 关联 + 路径修复 | VERIFIED | __init__ 安全网 (L86-89), _make_func_ref 显式 event_bus=None (L604-605) |
| `tests/tools/test_dynamic_creator_sandbox.py` | 4 个 D-06 集成测试 | VERIFIED | 280 行，4 个测试函数全部通过 |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | --- | --- | ------ | ------- |
| SandboxExecutor.execute() | EventBus.publish('sandbox_timeout') | subprocess.TimeoutExpired 异常处理 | WIRED | sandbox.py:532-542: `if self._event_bus: await self._event_bus.publish("sandbox_timeout", {...})` |
| SandboxExecutor.execute() | EventBus.publish('sandbox_violation') | _validate_path 失败 + _classify_violation 检测 | WIRED | sandbox.py:399-408 (校验失败) + sandbox.py:497-505 (违规分类) |
| _build_cmd() | 子进程网络隔离 | unshare --user --map-root-user --net | WIRED | sandbox.py:612-613: `["unshare", "--user", "--map-root-user", "--net"] + base_cmd` |
| DynamicToolCreator._stage4_self_test() | SandboxExecutor.execute() | self._sandbox.execute() + sandbox._event_bus = self._bus | WIRED | dynamic_creator.py:86-89: __init__ 关联 event_bus |
| DynamicToolCreator._make_func_ref() | SandboxExecutor | SandboxExecutor(timeout=30.0, event_bus=None) | WIRED | dynamic_creator.py:604-605: 独立沙箱，显式 None |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| -------- | ------------- | ------ | ------------------ | ------ |
| SandboxExecutor.execute() | sandbox_timeout event | subprocess.TimeoutExpired exception | Real exception data | FLOWING |
| SandboxExecutor.execute() | sandbox_violation event | _validate_path() boolean + _classify_violation() string | Real violation detection | FLOWING |
| SandboxExecutor.execute() | sandbox_resource_exceeded event | subprocess returncode + stderr analysis | Real resource limit enforcement | FLOWING |
| DynamicToolCreator._stage4_self_test() | sandbox events via self._sandbox._event_bus | SandboxExecutor.execute() event publishing | Real sandbox events forwarded to creator's EventBus | FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| Simple Python execution | `executor.execute('print("hello world")', 'python')` | status="passed", output contains "hello world" | PASS |
| Simple Bash execution | `executor.execute('echo "hello bash"', 'bash')` | status="passed", output contains "hello bash" | PASS |
| Path validation blocks /etc | `executor.execute('print("test")', 'python', working_dir='/etc')` | status="failed", error contains "路径校验失败" | PASS |
| _build_cmd Linux unshare | `SandboxExecutor._build_cmd('/tmp/test.py', 'python')` on Linux | cmd[0]="unshare", "--net" in cmd | PASS |
| _safe_realpath nonexistent | `SandboxExecutor._safe_realpath('/tmp/nonexistent_test_path')` | Returns path without error | PASS |
| _validate_path allow/deny | `.sandbox/test.py` vs `/etc/passwd` | True / False correctly | PASS |
| _classify_violation detection | "Network is unreachable" / "Resource temporarily unavailable" / "Cannot allocate memory" | network_attempt / process / memory / None | PASS |
| Timeout event publishing | `executor.execute('time.sleep(5)', 'python')` with timeout=0.5 | sandbox_timeout event published to EventBus | PASS |
| Violation event publishing | `executor.execute('print("test")', 'python', working_dir='/etc')` | sandbox_violation event published with violation_type="sensitive_path" | PASS |
| Event schema instantiation | `SandboxTimeout(session_id='test', ...)` | Correct serialization and TypeAdapter deserialization | PASS |
| Literal constraint enforcement | Invalid violation_type / resource_type | ValidationError raised correctly | PASS |
| TypeScript compilation | `npx tsc --noEmit` | Zero errors | PASS |

### Test Results

```
tests/tools/test_sandbox.py ...................... 30 passed
tests/tools/test_dynamic_creator_sandbox.py .... 4 passed
tests/test_schemas.py ................... 19 passed
Total: 53 passed, 0 failed, 0 deselected
```

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| (none) | -- | -- | -- | No debt markers, empty implementations, or hardcoded stubs found in phase-modified files |

---

## Gap Detail

### GAP-1: test_schemas.py 沙箱事件测试类已删除（非阻塞）

**Found during:** Dedicated test class verification (Step 5 of verification process).

**What happened:** Commit `644d478` (09-01 RED) added 4 dedicated test classes:
- `TestSandboxTimeoutSchema` -- instantiation, field types, timestamp auto-fill, JSON serialization
- `TestSandboxViolationSchema` -- violation_type 3-value Literal constraint, invalid value rejection
- `TestSandboxResourceExceededSchema` -- resource_type 3-value Literal constraint
- `TestSandboxEventsDiscriminatedUnion` -- Event union deserialization for all 3 new types

Commit `0194ca0` (09-01 GREEN) kept these tests and updated `TestAllEventsUniqueType` and `TestUpdatedEventTypeCount` to include the 3 sandbox event classes with count 25.

Commit `b7eb91b` (09-02 GREEN) removed ALL sandbox event references from `test_schemas.py`:
- Removed `SandboxTimeout`, `SandboxViolation`, `SandboxResourceExceeded` imports
- Removed sandbox event classes from `TestAllEventsUniqueType` and `TestUpdatedEventTypeCount`  
- Removed all 4 dedicated test classes completely
- Changed event type count from 25 back to 22

The sandbox event schemas are still tested **indirectly** via the 30 sandbox executor tests (which create and publish these events), so functional correctness is not affected. However, dedicated Pydantic model validation tests (Literal constraint enforcement, JSON round-trip, union deserialization) are no longer in the schema test file.

**Severity:** WARNING -- non-blocking. Schemas work correctly (verified via behavioral spot-check). Test coverage exists indirectly. The gap is in test organization and direct coverage, not in functionality.

## Verification Summary

The phase goal is **achieved**. All four requirements (DYN-11 through DYN-14) are implemented with working code, passing tests, and correct event publishing. The SandboxExecutor has been upgraded from basic subprocess isolation to a three-layer security boundary:

1. **Network namespace isolation** (DYN-13): `unshare --user --map-root-user --net` on Linux
2. **Path whitelist validation** (DYN-14): `_safe_realpath()` + `DENY_PATTERNS` + `startswith()` containment check
3. **Resource limit hardening** (DYN-12): RLIMIT_NPROC=(0,0), RLIMIT_FSIZE=(100MB), plus existing RLIMIT_CPU and RLIMIT_AS
4. **Audit event publishing** (cross-cutting): sandbox_timeout, sandbox_violation, sandbox_resource_exceeded events via EventBus

The DynamicToolCreator integration (D-06) correctly passes the hardened SandboxExecutor through to self-test stage, with a safety net that auto-links the EventBus if not already set.

One non-blocking gap exists: the dedicated Pydantic schema test classes for sandbox events were removed during the 09-02 TDD cycle and not re-added. This is a test organization regression that should be addressed but does not affect functional correctness.

---

_Verified: 2026-06-01T22:51:00Z_
_Verifier: Claude (gsd-verifier)_
