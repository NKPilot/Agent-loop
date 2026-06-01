---
phase: 09-security-hardening
plan: 03
subsystem: tools/dynamic_creator
tags: [sandbox, integration, D-06, audit, path-validation, network-isolation, event-bus]
requires: ["09-02"]
provides: ["09-04"]
affects: [sandbox-executor-path, dynamic-tool-creation-pipeline]
tech-stack:
  added: []
  patterns: [event-bus-linkage, sandbox-path-whitelist, temp-dir-within-sandbox]
key-files:
  created: [tests/tools/test_dynamic_creator_sandbox.py]
  modified: [src/loopai/tools/dynamic_creator.py]
decisions:
  - "D-06: __init__ 中自动关联 self._sandbox._event_bus = self._bus 作为安全网，确保即使外部未传入 event_bus 也能审计自测阶段违规"
  - "D-06: _make_func_ref 显式传入 event_bus=None，工具运行时沙箱独立执行不产生审计事件"
  - "路径修复: _stage4_self_test 和 _make_func_ref 的临时目录从 /tmp 改为 .sandbox 内，适配加固沙箱的路径白名单校验"
metrics:
  duration_seconds: 404
  completed_date: "2026-06-01"
---

# Phase 9 Plan 3: D-06 加固沙箱集成到 DynamicToolCreator Summary

## 一句话概述

将 Plan 09-02 加固后的 SandboxExecutor（网络隔离 + 路径白名单 + rlimit + 审计事件）集成到 DynamicToolCreator 的自测阶段和工具运行时，确保 LLM 生成的代码在隔离安全环境中执行，违规可被检测和审计。

## 完成内容

### 核心变更

1. **DynamicToolCreator.__init__ — D-06 event_bus 关联**
   - 在 `__init__` 末尾添加安全网：`if self._sandbox._event_bus is None: self._sandbox._event_bus = self._bus`
   - 确保即使外部调用者未传入 event_bus，自测阶段的沙箱也能发布审计事件
   - 不影响已传入 event_bus 的正常路径

2. **_stage4_self_test — 适配加固沙箱路径白名单**
   - 临时目录从 `tempfile.mkdtemp(prefix="tool_test_")`（/tmp）改为 `tempfile.mkdtemp(prefix="tool_test_", dir=".sandbox")`
   - 添加 `os.makedirs(".sandbox", exist_ok=True)` 确保目录存在
   - 方法体其余逻辑不变——通过 `self._sandbox.execute()` 透明调用加固沙箱

3. **_make_func_ref — 工具运行时独立沙箱**
   - 临时目录从 `/tmp` 改为 `.sandbox` 内，适配路径白名单
   - 显式传入 `event_bus=None`，工具运行时执行不产生审计事件
   - 每次调用创建独立 SandboxExecutor，与自测阶段隔离

### 测试覆盖 (4 个 D-06 集成测试)

| 测试 | 验证点 | 状态 |
|------|--------|------|
| `test_stage4_uses_hardened_sandbox` | 自测网络违规被 unshare --net 阻断，sandbox_violation 事件发布 | PASSED |
| `test_stage4_timeout_publishes_event` | 自测代码超时，sandbox_timeout 事件发布 | PASSED |
| `test_stage4_path_validation` | extra_dirs=["/etc"] 被路径白名单拒绝，sandbox_violation 事件发布 | PASSED |
| `test_func_ref_creates_independent_sandbox` | func_ref 创建独立 SandboxExecutor(event_bus=None)，工具正常执行，无审计事件泄漏 | PASSED |

### 回归验证

- **34 个沙箱相关测试**: 全部通过（30 SandboxExecutor + 4 DynamicToolCreator integration）
- **19 个事件 schema 测试**: 全部通过
- **326 个全量回归测试** (排除 API): 全部通过，零回归

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] _stage4_self_test 临时目录在 /tmp 被加固沙箱路径白名单拒绝**

- **发现于:** Task 1 (RED 阶段首次运行)
- **问题:** Plan 09-02 的 SandboxExecutor.execute() 新增路径白名单校验（仅允许 `.sandbox` 内的路径），但 `_stage4_self_test` 使用 `tempfile.mkdtemp(prefix="tool_test_")` 在 `/tmp` 创建临时工作目录，导致所有自测调用被拒绝并返回 `status="failed"`。错误信息: "路径校验失败: /tmp/claude-1000/tool_test_XXX 不在白名单内"
- **修复:** 将临时目录创建位置从 `/tmp` 改为 `.sandbox`，使用 `tempfile.mkdtemp(prefix="tool_test_", dir=".sandbox")`，并添加 `os.makedirs(".sandbox", exist_ok=True)` 确保目录存在
- **文件修改:** `src/loopai/tools/dynamic_creator.py` (line ~456)
- **提交:** 1f57abd

**2. [Rule 1 - Bug] _make_func_ref 临时目录同样在 /tmp 被拒绝**

- **发现于:** Task 2 (GREEN 阶段测试运行)
- **问题:** `_make_func_ref` 闭包中使用 `tempfile.TemporaryDirectory(prefix="tool_run_")` 在 `/tmp` 创建临时目录，被加固沙箱的路径白名单拒绝
- **修复:** 将临时目录创建位置从 `/tmp` 改为 `.sandbox`，使用 `tempfile.TemporaryDirectory(prefix="tool_run_", dir=".sandbox")`
- **文件修改:** `src/loopai/tools/dynamic_creator.py` (line ~601)
- **提交:** 1f57abd

**3. [Rule 1 - Bug] 网络违规测试代码捕获异常导致误判**

- **发现于:** Task 2 (GREEN 阶段测试运行)
- **问题:** 测试 `test_stage4_uses_hardened_sandbox` 的自测代码使用 `try/except OSError` 捕获网络错误，导致子进程退出码为 0，SandboxExecutor 判定执行通过而不发布 sandbox_violation 事件
- **修复:** 移除 try/except，让 OSError 导致子进程非零退出码，以便 `_classify_violation()` 检测到 `network_attempt` 违规并发布事件
- **文件修改:** `tests/tools/test_dynamic_creator_sandbox.py`
- **提交:** 1f57abd

### 计划外发现

- **无架构级变更** — 所有修复均为 Rule 1 级别的 bug 修复，未引入新接口、新表或架构变更

## Commits

| Hash | 消息 |
|------|------|
| 7dd0807 | test(09-03): 添加 D-06 集成测试 — 加固沙箱违规检测（RED） |
| 1f57abd | feat(09-03): D-06 集成 — DynamicToolCreator 使用加固沙箱 + 路径修复 |

## Success Criteria Verification

- [x] DynamicToolCreator.__init__ 将 self._bus 关联到 sandbox._event_bus（D-06 自测审计）
- [x] _stage4_self_test 通过 self._sandbox.execute() 透明使用加固沙箱
- [x] _make_func_ref 中 SandboxExecutor 创建保持 event_bus=None（工具运行时独立）
- [x] 自测阶段的网络违规被检测并发布 sandbox_violation 事件
- [x] 自测阶段的超时被检测并发布 sandbox_timeout 事件
- [x] 自测阶段的路径违规被检测并发布 sandbox_violation 事件
- [x] 全部 34 个沙箱测试通过（30 SandboxExecutor + 4 DynamicToolCreator integration）
- [x] 事件 schema 测试无回归
- [x] 全量 326 个回归测试通过

## Requirements Fulfilled

| 需求 ID | 描述 | 状态 |
|---------|------|------|
| DYN-11 | 子进程隔离——SystemExit 被捕获，主进程不受影响 | ✅ 加固沙箱在 subprocess 中隔离执行 |
| DYN-12 | rlimit 资源硬限制——CPU/内存/进程数/文件大小 | ✅ 加固沙箱通过 preexec_fn 设置 rlimit |
| DYN-13 | 网络命名空间隔离——unshare --net 阻断所有网络连接 | ✅ 网络违规测试验证阻断和事件发布 |
| DYN-14 | 路径白名单校验——realpath + startswith 包含性检查 | ✅ 路径违规测试验证拒绝和事件发布 |

## Self-Check: PASSED

- [x] `tests/tools/test_dynamic_creator_sandbox.py` 存在
- [x] 提交 7dd0807 存在
- [x] 提交 1f57abd 存在
- [x] 34 个沙箱相关测试全部通过
- [x] 326 个全量回归测试全部通过
