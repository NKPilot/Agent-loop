---
phase: 09-security-hardening
plan: 02
subsystem: sandbox
tags: [sandbox, security, hardening, network-isolation, path-whitelist, rlimit]
requires:
  - "09-01"  # 沙箱事件 schema 定义 (SandboxTimeout, SandboxViolation, SandboxResourceExceeded)
provides:
  - "SandboxExecutor 三层安全加固（网络隔离 + 路径白名单 + rlimit 升级 + 事件发布）"
affects: []
tech-stack:
  added: []
  patterns:
    - "unshare CLI 包装（--user --map-root-user --net）"
    - "路径白名单校验（_safe_realpath + startswith + DENY_PATTERNS）"
    - "事件驱动违规通知（sandbox_timeout / sandbox_violation / sandbox_resource_exceeded）"
key-files:
  created:
    - "tests/tools/__init__.py"
    - "tests/tools/test_sandbox.py"
  modified:
    - "src/loopai/tools/sandbox.py"
decisions:
  - "unshare --net 网络隔离在 Linux 上强制生效，非 Linux 优雅降级为仅 rlimit"
  - "RLIMIT_NPROC=(0,0) 完全禁止子进程 fork，消除 fork bomb 风险"
  - "RLIMIT_FSIZE=(100MB,100MB) 硬限制文件写入，通过 SIGXFSZ 强制执行"
  - "路径白名单采用 _safe_realpath 逐级解析防止符号链接绕过"
  - "事件发布仅在 event_bus 已提供时触发，保持向后兼容"
metrics:
  duration: ""
  completed_date: ""
---

# Phase 9 Plan 2: SandboxExecutor 三层安全加固 Summary

SandboxExecutor 在现有子进程隔离 + rlimit 基础上增量增加三层安全防护：unshare 网络命名空间隔离、文件系统路径白名单校验、沙箱违规事件发布。30 个测试用例覆盖 DYN-11 至 DYN-14 全部需求，零回归。

## 任务完成

| 任务 | 名称 | 类型 | 提交 | 关键文件 |
|------|------|------|------|----------|
| 1 | 创建沙箱加固测试文件 | tdd (RED) | `9d0bf72` | `tests/tools/test_sandbox.py`, `tests/tools/__init__.py` |
| 2 | 实现 SandboxExecutor 三层加固 | tdd (GREEN) | `15bfbd7` | `src/loopai/tools/sandbox.py` |
| 3 | 运行完整测试套件验证 | auto | `b1214d6` | `tests/tools/test_sandbox.py` (修复) |

## 实现细节

### 新增方法

| 方法 | 类型 | 职责 |
|------|------|------|
| `_build_cmd(script_path, language)` | `@staticmethod` | Linux 上 `unshare --user --map-root-user --net` 包装；非 Linux 优雅降级；探测 unshare 可用性 |
| `_safe_realpath(path)` | `@staticmethod` | 逐级解析不存在的路径组件，防止符号链接绕过 |
| `_validate_path(path, allowed_roots)` | `@staticmethod` | 两阶段校验：DENY_PATTERNS 黑名单 → allowed_roots 白名单 |
| `_classify_violation(stderr)` | `@staticmethod` | stderr 分析，返回 `network_attempt` / `process` / `memory` / `file_size` / `None` |

### 修改内容

| 组件 | 变更 |
|------|------|
| `__init__` | 新增可选 `event_bus: EventBus \| None = None` 参数 |
| `_set_limits` | RLIMIT_NPROC `(50,50)` → `(0,0)`；新增 RLIMIT_FSIZE `(100MB,100MB)` |
| `execute` | 集成路径校验（执行前）+ unshare 命令构建 + 超时/违规/资源超限事件发布 |
| 模块级常量 | 新增 `DENY_PATTERNS`、`SANDBOX_ROOT`；新增 `logging` 和 `TYPE_CHECKING` 导入 |

### 事件发布

| 触发条件 | 事件类型 | 发布位置 |
|----------|----------|----------|
| path validate 失败 | `sandbox_violation` | execute() 路径校验阶段 |
| unshare --net 阻断连接 | `sandbox_violation` | execute() returncode != 0 分支 |
| subprocess.TimeoutExpired | `sandbox_timeout` | execute() 异常处理 |
| 资源超限（memory/process/file_size） | `sandbox_resource_exceeded` | execute() returncode != 0 分支 |

所有事件发布均有 `if self._event_bus:` 守卫，默认 `event_bus=None` 保持向后兼容。

## 测试结果

```
tests/tools/test_sandbox.py — 30 passed
tests/test_schemas.py — 19 passed
Total: 49 passed, 0 failed, 0 deselected
```

### 测试覆盖

| 需求 | 测试 | 类型 |
|------|------|------|
| DYN-11 | `test_subprocess_isolation` | 集成 |
| DYN-11 + DYN-13 | `test_network_isolation` | 集成 |
| DYN-12 | `test_memory_limit_enforced`, `test_memory_limit_rlimit_present` | 集成 |
| DYN-12 | `test_fork_bomb_prevented` | 集成 |
| DYN-12 | `test_filesize_limit_enforced` | 集成 |
| DYN-12 | `test_rlimit_cpu_enforced` | 集成 |
| DYN-12 | `test_timeout_event` | 集成 |
| DYN-13 | `test_non_linux_build_cmd`, `test_linux_build_cmd`, `test_build_cmd_bash` | 单元 |
| DYN-14 | `test_safe_realpath_*`, `test_validate_path_*`, `test_path_whitelist_*` | 单元 + 集成 |
| D-05 | `test_sandbox_violation_event`, `test_sandbox_timeout_event`, `test_sandbox_resource_exceeded_event` | 集成 |
| D-05 | `test_classify_violation_*` | 单元 |
| 回归 | `test_simple_python_execution`, `test_simple_bash_execution`, `test_execute_unknown_language` | 集成 |
| 构造函数 | `test_sandbox_init_*` | 单元 |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] _classify_violation 对 "Resource temporarily unavailable" 过于严格**
- **Found during:** Task 2 (GREEN phase)
- **Issue:** 原实现要求同时匹配 "Resource temporarily unavailable" 和 ("fork" 或 "process")，但 RLIMIT_NPROC 的标准错误消息 "OSError: Resource temporarily unavailable" 不一定包含 "fork" 或 "process" 关键词
- **Fix:** 移除额外条件，仅匹配 "resource temporarily unavailable" 即可判定为进程创建限制
- **Files modified:** `src/loopai/tools/sandbox.py`

**2. [Rule 3 - Blocking] 临时目录被路径白名单拒绝**
- **Found during:** Task 2 (GREEN phase)
- **Issue:** 当 `working_dir=None` 时 executor 创建临时目录（如 `/tmp/claude-1000/sandbox_xxx`），但 `_validate_path` 仅检查 `SANDBOX_ROOT`（`.sandbox`），导致正常的简单代码执行也被拒绝
- **Fix:** 自动创建的临时目录添加到 `allowed_roots` 列表中，始终允许
- **Files modified:** `src/loopai/tools/sandbox.py`

**3. [Rule 1 - Bug] test_timeout_event 与 pytest-timeout 竞争**
- **Found during:** Task 2 (GREEN phase)
- **Issue:** executor timeout=10s 与 pytest-timeout 默认 10s 存在竞争，导致测试框架超时而非子进程 TimeoutExpired
- **Fix:** 将 executor timeout 从 10s 减小至 5s
- **Files modified:** `tests/tools/test_sandbox.py`

## Threat Flags

None — all security surface changes match the plan's `<threat_model>` mitigations.

## Self-Check

All files verified present and commits confirmed via `git log --oneline -3`:

- `b1214d6` — fix timeout test race
- `15bfbd7` — implement three-layer hardening
- `9d0bf72` — add failing tests (RED phase)

TDD gate sequence: RED (`test(...)`) → GREEN (`feat(...)`) → FIX (`fix(...)`) — compliant.
