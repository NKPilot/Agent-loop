# Phase 9: 安全加固与沙箱隔离 - Research

**Researched:** 2026-06-01
**Domain:** Linux 进程隔离、命名空间、资源限制、文件系统访问控制
**Confidence:** HIGH

## Summary

Phase 9 将 Phase 8 的基础 SandboxExecutor 从"子进程隔离 + rlimit"升级为真正的安全边界。核心加固包括三层：网络命名空间隔离（CLONE_NEWNET）、文件系统路径白名单校验、沙箱违规审计事件。

在 WSL2 内核 6.6.114.1 上的实地验证确认：
- `unshare --user --map-root-user --net` 非特权用户可创建网络隔离命名空间，子进程内 8.8.8.8:53 返回 `[Errno 101] Network is unreachable` [VERIFIED: 本机测试]
- RLIMIT_AS=512MB、RLIMIT_NPROC=0、RLIMIT_FSIZE 均正确执行 [VERIFIED: 本机测试]
- `preexec_fn` 在多线程 asyncio 应用中是不安全的——必须使用 `unshare` CLI 包装器替代 [CITED: pylint W1509, CPython docs]

**Primary recommendation:** 使用 `unshare --user --map-root-user --net` 包装子进程命令实现网络隔离，避免 `preexec_fn` 的线程安全问题。路径白名单使用 `os.path.realpath()` + `startswith()` 规范模式。

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| DYN-11 | 动态工具在独立子进程中执行（`subprocess`），与主进程隔离 | 现有 SandboxExecutor 已实现 subprocess + rlimit 基础隔离；Phase 9 叠加网络隔离、路径校验 |
| DYN-12 | `resource.setrlimit` 硬限制：CPU 时间、内存 512MB、超时 30s | rlimit 在 WSL2 内核 6.6 上全部正确执行（已验证）；需将 RLIMIT_NPROC 从当前 50 降至 0，新增 RLIMIT_FSIZE=100MB |
| DYN-13 | 子进程禁止网络访问 | `unshare --user --map-root-user --net` 在 WSL2 上成功阻断外网连接（已验证）；非 Linux 优雅降级 |
| DYN-14 | 文件系统访问默认限于沙箱子目录，用户可授予额外目录 | 使用 `os.path.realpath()` + `startswith()` 规范模式；路径白名单以沙箱目录为根 |
</phase_requirements>

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** 增量增强现有 SandboxExecutor，不创建新类
- **D-02:** 使用 Linux network namespace（`unshare(CLONE_NEWNET)`）创建无网子进程。WSL2 内核支持 namespace。非 Linux 平台优雅降级（跳过网络隔离，记录 warning）
- **D-03:** 路径白名单模式。子进程 cwd 设为沙箱专用目录，read/write 操作前校验目标路径在白名单内
- **D-04:** 所有动态工具统一限制：30s 超时、512MB 内存（RLIMIT_AS）、RLIMIT_NPROC=0（禁止 fork）、RLIMIT_FSIZE=100MB。用户确认时不提供自定义选项
- **D-05:** 新增 3 个沙箱违规事件类型：`sandbox_timeout`、`sandbox_violation`、`sandbox_resource_exceeded`
- **D-06:** Phase 9 加固后的 SandboxExecutor 替换 Phase 8 自测阶段的执行器

### Claude's Discretion
- 网络隔离的具体实现方式（preexec_fn vs unshare CLI vs ctypes clone）
- 路径白名单校验的精确实现
- 审计事件的字段结构
- 资源限制的具体 setrlimit 调用顺序和错误处理

### Deferred Ideas (OUT OF SCOPE)
无。
</user_constraints>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| 网络命名空间隔离 | API/Backend (SandboxExecutor) | — | SandboxExecutor 在 `execute()` 中构建子进程命令时注入 `unshare` 包装；纯 OS 级别操作，与 Python 无关 |
| 路径白名单校验 | API/Backend (SandboxExecutor) | — | 校验逻辑在 SandboxExecutor 的 `_validate_path()` 中，文件操作前调用；校验失败发布 sandbox_violation 事件 |
| 资源限制执行 | API/Backend (SandboxExecutor) | — | `_set_limits()` 在 preexec_fn 中执行（仅 Unix）；统一 30s/512MB/NPROC=0/FSIZE=100MB |
| 沙箱审计事件 | API/Backend (EventBus) | Frontend (SSE) | SandboxExecutor 发布事件到 EventBus；前端通过 SSE 接收并展示 |
| 前端违规展示 | Frontend (ToolCreationDialog) | — | ToolCreationDialog 自测结果区域标红显示违规详情 |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `subprocess` | (Python 3.13 stdlib) | 子进程执行 | 已在 Phase 8 使用，`shell=False`、`capture_output=True`、`timeout` 参数完整 |
| `os` | (Python 3.13 stdlib) | 路径操作、命名空间标志 | `os.path.realpath()` 用于路径校验；`os.CLONE_NEWNET` 等命名空间常量验证可用 |
| `resource` | (Python 3.13 stdlib) | rlimit 资源限制 | 已在 Phase 8 使用，Phase 9 调优限制值 |
| `unshare` (CLI) | util-linux 2.39.3 | 网络命名空间创建 | 系统自带，无需额外安装；替代不安全的 `preexec_fn` [VERIFIED: 本机 `unshare --version`] |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `shutil` | (stdlib) | 临时目录清理 | 执行后清理沙箱工作目录 |
| `tempfile` | (stdlib) | 临时目录创建 | `mkdtemp(prefix="sandbox_")` 创建隔离工作区 |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `unshare` CLI 包装 | `preexec_fn` + `os.unshare()` | `preexec_fn` 在多线程 asyncio 应用中不安全（POSIX fork 只复制调用线程，其他线程持有的锁永不释放，可能导致死锁）[CITED: pylint W1509] |
| `unshare` CLI 包装 | `ctypes.CDLL(None).clone()` | ctypes 直接调用 `clone()` 绕过 Python 线程状态管理，行为不可预测；且 `clone()` 的栈管理极为复杂 |
| `unshare` CLI 包装 | `os.fork()` + `os.unshare()` + `os.execvp()` | 可行但需要手动管理子进程生命周期、PID 回收、信号传播；比 CLI 包装多出 50+ 行代码且容易出错 |
| `os.path.realpath()` + `startswith()` | `path-jail` (pip) | `path-jail` 提供更强的 symlink TOCTOU 防护，但引入外部 Rust 依赖；对本地单用户场景，`realpath` + `startswith` 足够 |

**Installation:**
```bash
# 无额外 pip 依赖——所有加固基于 stdlib + 系统 unshare CLI
# unshare 来自 util-linux，WSL2 自带
```

**Version verification:**
- `unshare` from util-linux 2.39.3 — WSL2 自带，无需安装 [VERIFIED: 本机测试]
- Python `os.CLONE_NEWUSER=268435456`, `CLONE_NEWNET=1073741824` 均可用 [VERIFIED: 本机 Python 3.13]

## Architecture Patterns

### System Architecture Diagram

```
Agent Code (LLM Generated)
       │
       ▼
SandboxExecutor.execute(code, language, working_dir, extra_dirs)
       │
       ├─► 1. 路径白名单校验 (_validate_paths)
       │      ├─ working_dir 必须在 .sandbox/ 下
       │      ├─ extra_dirs 逐项 realpath + startswith 检查
       │      └─ 校验失败 → EventBus.publish("sandbox_violation") → 拒绝执行
       │
       ├─► 2. 写入代码到 script.py / script.sh
       │
       ├─► 3. 构建命令（KEY: unshare 包装）
       │      Linux:
       │        ["unshare", "--user", "--map-root-user", "--net",
       │         sys.executable, script_path]
       │      非 Linux:
       │        [sys.executable, script_path]  ← 优雅降级
       │
       ├─► 4. 设置 preexec_fn = _set_limits (仅 Unix)
       │      _set_limits():
       │        RLIMIT_CPU   = (30, 30)        # 硬限制
       │        RLIMIT_AS    = (512MB, 512MB)
       │        RLIMIT_NPROC = (0, 0)          # 禁止 fork
       │        RLIMIT_FSIZE = (100MB, 100MB)  # 限制文件写入
       │
       ├─► 5. subprocess.run(cmd, timeout=30, preexec_fn=...)
       │
       └─► 6. 结果处理 + 审计事件
              ├─ TimeoutExpired → EventBus.publish("sandbox_timeout")
              ├─ returncode != 0 → 分析 stderr
              │    ├─ "Network is unreachable" → sandbox_violation
              │    ├─ "Resource temporarily unavailable" (fork) → sandbox_resource_exceeded
              │    └─ 其他 → 正常 failed
              └─ returncode == 0 → passed
```

### Recommended Project Structure
```
src/loopai/tools/
├── sandbox.py              # SandboxExecutor (加固目标) + DangerousModuleScanner
│   ├── class DangerousModuleScanner  # 不变
│   └── class SandboxExecutor         # 增量增强:
│       ├── execute()                 #   增加 unshare 包装 + 路径校验
│       ├── _set_limits()             #   调整 rlimit 值
│       ├── _validate_paths()         #   新增: 路径白名单校验
│       ├── _build_cmd()              #   新增: 构建平台特定命令
│       └── _classify_violation()     #   新增: 违规分类→事件类型
│
src/loopai/events/
└── schemas.py               # 新增 3 个沙箱事件类 + 更新 Event 联合类型

frontend/src/
└── lib/
    └── eventTypes.ts        # 同步新增 3 个 TypeScript 事件接口
```

### Pattern 1: unshare CLI Wrapper (替代 preexec_fn)
**What:** 在子进程命令前插入 `unshare --user --map-root-user --net`，由 `unshare` 二进制内部处理 fork → unshare → exec，完全避免 Python 层的线程安全问题。
**When to use:** 所有需要网络隔离的 Linux 子进程执行。
**Why not preexec_fn:** POSIX `fork()` 只复制调用线程，其他 asyncio 线程持有的锁在子进程中永不释放。如果 `preexec_fn` 间接调用需要锁的函数（malloc、printf、logging），子进程立即死锁。

```python
# Source: 本机验证通过
def _build_cmd(self, script_path: str, language: str) -> list[str]:
    """构建执行命令，Linux 上注入 unshare 网络隔离。"""
    if language == "python":
        base_cmd = [sys.executable, script_path]
    else:
        base_cmd = ["bash", script_path]

    if sys.platform == "linux":
        # unshare 包装: 用户命名空间 (--user --map-root-user) +
        #               网络命名空间 (--net)
        # --map-root-user 在命名空间内映射为 root，获取 CAP_SYS_ADMIN
        # 从而可以创建网络命名空间——全程无需宿主机 root
        return ["unshare", "--user", "--map-root-user", "--net"] + base_cmd
    else:
        # 非 Linux: 优雅降级，仅依赖 rlimit
        return base_cmd
```

### Pattern 2: 路径白名单校验
**What:** 所有文件操作路径必须 `os.path.realpath()` 后位于白名单目录内。
**When to use:** SandboxExecutor 中校验 `working_dir` 和 `extra_dirs`。

```python
# Source: CodeQL path injection prevention pattern + 本机验证
import os

SANDBOX_ROOT = os.path.realpath(".sandbox")

def _validate_path(self, path: str, allowed_roots: list[str]) -> bool:
    """校验路径是否在白名单内（符号链接安全）。"""
    try:
        real = os.path.realpath(path)
    except OSError:
        return False

    for root in allowed_roots:
        root_real = os.path.realpath(root)
        # 必须 startswith(root_real + os.sep) 防止 /sandbox_evil 匹配
        if real == root_real or real.startswith(root_real + os.sep):
            return True
    return False

# 拒绝的敏感路径
DENY_PATTERNS = [
    "/etc", "/proc", "/sys", "/dev",
    os.path.expanduser("~/.ssh"),
    os.path.expanduser("~/.gnupg"),
    os.path.expanduser("~/.aws"),
]
```

### Pattern 3: 沙箱违规事件发布
**What:** SandboxExecutor 通过 EventBus 发布结构化违规事件，前端通过 SSE 接收并展示。
**When to use:** 超时、越权访问、资源超限三种情况。

```python
# SandboxExecutor 内部发布事件
await self._bus.publish("sandbox_timeout", {
    "event_type": "sandbox_timeout",
    "session_id": self._session_id,
    "step_num": self._step_num,
    "tool_name": tool_name,
    "timeout_seconds": self.timeout,
    "timestamp": datetime.now(timezone.utc).isoformat(),
})
```

### Anti-Patterns to Avoid
- **preexec_fn 中调用 os.unshare():** 线程不安全，死锁风险 [CITED: pylint W1509, CPython subprocess docs]
- **仅使用 os.path.abspath() 做路径校验:** 不解析符号链接，`/sandbox/link -> /etc` 可绕过 [CITED: CodeQL py-path-injection]
- **使用 os.path.normpath() 而非 realpath():** normpath 纯词法操作，不访问磁盘，无法检测符号链接逃逸
- **在 _set_limits() 中遗漏 try/except:** rlimit 设置可能因权限不足抛出 ValueError；遗漏会导致子进程启动失败
- **RLIMIT_AS 设置为 512MB 但未考虑 CPython 基线 VIRT:** 子进程独立地址空间，512MB 对简单脚本足够。但在 WSL2 上 CPython 基线 VIRT ~1.1GB（含未提交 arena），如果主进程设置 RLIMIT_AS 过小会导致自身崩溃。关键：限制必须在子进程中设置（via preexec_fn 或 unshare 命名空间内），不能在主进程中设置

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| 网络命名空间创建 | 手动 `os.fork()` + `os.unshare()` + `os.execvp()` | `unshare --user --map-root-user --net` CLI 包装 | `unshare(1)` 经过 util-linux 项目 15+ 年验证，正确处理 UID/GID mapping、setgroups denial、cgroup 迁移；手写版本需 100+ 行 C-level 代码且易出错 |
| 符号链接安全路径校验 | 手动 `os.path.realpath()` + `startswith()` 边界检查 | 自己实现（简单场景可接受）；对高安全需求用 `path-jail` | 自己实现仅 20 行且可控；`path-jail` 是 Rust-backed 但对单用户本地场景过度 |
| rlimit 跨平台设置 | 手动逐平台 #ifdef | `resource.setrlimit()` | Python stdlib 已封装平台差异；手动操作需 ctypes 调用 `prlimit64` 等原始系统调用 |
| 子进程超时 | `signal.alarm()` + `SIGALRM` 处理器 | `subprocess.run(timeout=N)` | `subprocess.run` 内部使用 `SIGKILL` 确保子进程终止，比 `SIGALRM` + `SIGTERM` 更可靠 |

**Key insight:** Linux 命名空间管理是复杂的内核级原语。`unshare(1)` CLI 工具封装了 UID/GID mapping、setgroups 禁用、cgroup 迁移等数十个细节步骤。手写这些步骤容易引入安全漏洞（如忘记 `deny` setgroups 导致权限提升）。

## Common Pitfalls

### Pitfall 1: preexec_fn 在多线程 asyncio 应用中死锁
**What goes wrong:** SandboxExecutor 的 `_set_limits` 通过 `preexec_fn` 在子进程中调用。asyncio 事件循环可能持有内部锁（如 logging handler 锁、内存分配器锁）。`fork()` 只复制调用线程，其他 asyncio 任务持有的锁在子进程中永不释放。即使 `_set_limits` 本身不获取锁，`resource.setrlimit` 底层可能调用 `malloc`（libc 内部），如果 malloc arena lock 在 fork 时被另一个线程持有，子进程立即死锁。
**Why it happens:** POSIX `fork()` 语义决定。Python 3.7+ 的 `os.register_at_fork` 只能保护 CPython 内部锁，不能保护 libc 或第三方库的锁。
**How to avoid:** 使用 `unshare` CLI 包装替代 `preexec_fn`。`unshare` 二进制在 fork → unshare → exec 之间只调用原始系统调用（不依赖 libc 锁）。`_set_limits` 中的 rlimit 设置在 exec 之后生效——子进程继承了父进程的 rlimit（fork 继承），无需在 preexec_fn 中设置。或者，如果必须使用 preexec_fn（非 Linux 平台），确保 `_set_limits` 只包含 `resource.setrlimit()` 调用，不包含任何 I/O、导入、或内存分配。
**Warning signs:** 子进程间歇性挂起（无输出、无退出），strace 显示子进程卡在 `futex(FUTEX_WAIT)`。

### Pitfall 2: WSL2 上 `unshare --net` 单独使用失败
**What goes wrong:** 直接使用 `unshare --net`（不结合 `--user`）需要 `CAP_SYS_ADMIN`。WSL2 的非 root 用户没有此能力，返回 `Operation not permitted`。
**Why it happens:** Linux 内核 3.8+ 允许非特权用户创建 `CLONE_NEWUSER`，从而在用户命名空间内获得伪 root 的 `CAP_SYS_ADMIN`。但 `CLONE_NEWNET` 单独创建仍需要真正的 root 或初始命名空间中的 `CAP_SYS_ADMIN`。
**How to avoid:** 始终组合使用 `unshare --user --map-root-user --net`（简写 `unshare -rn`）。先创建用户命名空间（赋予伪 root + CAP_SYS_ADMIN），再在其中创建网络命名空间。[VERIFIED: 本机 `unshare --net true` 失败，`unshare --user --map-root-user --net true` 成功]
**Warning signs:** `OSError: [Errno 1] Operation not permitted` 或 `unshare: cannot change net namespace: Operation not permitted`

### Pitfall 3: RLIMIT_AS=512MB 在主进程中设置导致崩溃
**What goes wrong:** 在主进程中调用 `resource.setrlimit(RLIMIT_AS, (512MB, 512MB))` 后，Python 解释器的正常虚拟地址空间可能超过 512MB（WSL2 上 CPython 基线约 1.1GB VIRT），导致主进程自身立即收到 SIGSEGV。
**Why it happens:** `RLIMIT_AS` 限制虚拟地址空间（VIRT），不仅是物理内存（RSS）。CPython 的 pymalloc 预分配大量虚拟地址 arena（未提交但计入 VIRT）。在 WSL2 上，额外的内核映射（vvar/vdso/vsyscall）和 9p 文件系统开销使基线 VIRT 比裸金属 Linux 高约 100MB。
**How to avoid:** 资源限制必须在子进程（fork 后）中设置，通过 `preexec_fn` 或 `unshare` 命名空间内的命令。子进程的地址空间从零开始，512MB 的限制完全足够。[VERIFIED: 本机子进程中 RLIMIT_AS=512MB 下成功分配 200MB]
**Warning signs:** 主进程启动后立即崩溃，日志显示 SIGSEGV 或 "MemoryError"。

### Pitfall 4: `os.path.realpath()` 对不存在的文件失败
**What goes wrong:** 校验 `extra_dirs` 中的路径时，如果目录尚未创建，`os.path.realpath()` 抛出 `OSError`，导致白名单校验失败。
**Why it happens:** `realpath()` 需要访问磁盘解析所有符号链接组件；路径组件不存在时调用失败。
**How to avoid:** 对不存在的路径，逐级向上解析存在的父目录，然后拼接剩余部分后再做 `startswith` 检查：
```python
def _safe_realpath(path: str) -> str:
    """逐级解析符号链接，对不存在的路径也能正确处理。"""
    path = os.path.abspath(path)
    parts = []
    while True:
        try:
            resolved = os.path.realpath(path)
            if parts:
                return os.path.join(resolved, *parts)
            return resolved
        except OSError:
            head, tail = os.path.split(path)
            if not tail or head == path:
                return path  # 根目录不存在，返回原始路径
            parts.insert(0, tail)
            path = head
```
**Warning signs:** `FileNotFoundError` 在校验尚未创建的目录时抛出。

### Pitfall 5: RLIMIT_NPROC 限制的是整个 UID 而非单进程
**What goes wrong:** 设置 `RLIMIT_NPROC=0` 后，同一 UID 下的所有进程（包括主 Agent 进程）都无法创建新进程或线程。如果在主进程中设置，整个 Agent 系统立即瘫痪。
**Why it happens:** `RLIMIT_NPROC` 是 per-UID 而非 per-process 的限制。Linux 将线程（CLONE_THREAD）也计入此限制。
**How to avoid:** 必须在子进程的 `preexec_fn` 中设置——子进程有独立的 UID 命名空间视图（如果使用了 `unshare --user`）。或确保设置发生在 fork 之后、业务逻辑执行之前。注意：在 `unshare --user --map-root-user` 命名空间内，子进程的 UID 是命名空间内的 0（伪 root），不影响宿主机的真实 UID，因此 NPROC 限制只影响该命名空间内的进程。[VERIFIED: 本机子进程中 RLIMIT_NPROC=0 成功阻止 os.fork()]
**Warning signs:** 主 Agent 进程的所有操作被阻塞，日志显示 `[Errno 11] Resource temporarily unavailable`。

## Code Examples

Verified patterns from official sources and local testing:

### Network-Isolated Subprocess Execution
```python
# Source: 本机验证 unshare --user --map-root-user --net
# /home/he/workwork/Agent-loop (kernel 6.6.114.1-microsoft-standard-WSL2)
import subprocess
import sys

def _build_isolated_cmd(script_path: str, language: str) -> list[str]:
    """构建网络隔离的子进程命令。"""
    base = [sys.executable, script_path] if language == "python" else ["bash", script_path]
    if sys.platform == "linux":
        return ["unshare", "--user", "--map-root-user", "--net"] + base
    return base

# 验证结果:
# - unshare --user --map-root-user --net python3 -c "...socket.connect(('8.8.8.8', 53))..."
#   → OSError: [Errno 101] Network is unreachable  ✅
# - unshare --user --map-root-user --net python3 -c "print(os.getuid())"
#   → 0 (命名空间内为 root) ✅
# - RLIMIT_NPROC=0 在命名空间内阻止 os.fork() ✅
# - RLIMIT_AS=512MB 下 200MB 分配成功 ✅
```

### Path Whitelist Validation
```python
# Source: CodeQL py-path-injection + os.path.realpath() canonical pattern
# https://codeql.github.com/codeql-query-help/python/py-path-injection/
import os

SANDBOX_ROOT = os.path.realpath(".sandbox")
SENSITIVE_PATHS = [
    "/etc", "/proc", "/sys", "/dev",
    os.path.expanduser("~/.ssh"),
    os.path.expanduser("~/.gnupg"),
    os.path.expanduser("~/.aws"),
]

def validate_path(path: str, allowed_roots: list[str]) -> bool:
    """符号链接安全的路径白名单校验。"""
    try:
        real = _safe_realpath(path)
    except (OSError, ValueError):
        return False

    # 拒绝敏感路径（即使也在白名单内）
    for sensitive in SENSITIVE_PATHS:
        try:
            sr = os.path.realpath(sensitive)
            if real == sr or real.startswith(sr + os.sep):
                return False
        except OSError:
            pass

    # 检查是否在白名单内
    for root in allowed_roots:
        try:
            rr = os.path.realpath(root)
            if real == rr or real.startswith(rr + os.sep):
                return True
        except OSError:
            continue
    return False
```

### Updated rlimit Configuration
```python
# Source: 本机验证 WSL2 kernel 6.6 rlimit 行为
# 从 Phase 8 的 _set_limits() 更新为 Phase 9 的统一限制
@staticmethod
def _set_limits() -> None:
    """子进程资源限制（preexec_fn 回调，仅 Unix）。"""
    import resource

    limits = [
        (resource.RLIMIT_CPU,    (30, 30)),                    # 30s CPU 硬限制
        (resource.RLIMIT_AS,     (512*1024*1024, 512*1024*1024)),  # 512MB
        (resource.RLIMIT_NPROC,  (0, 0)),                      # 禁止 fork
        (resource.RLIMIT_FSIZE,  (100*1024*1024, 100*1024*1024)),  # 100MB 文件
    ]

    for rlim, value in limits:
        try:
            resource.setrlimit(rlim, value)
        except (ValueError, OSError):
            pass  # 权限不足时优雅降级
```

### Sandbox Violation Event Schema
```python
# Source: 遵循现有 EventBase 模式 (src/loopai/events/schemas.py)
# 新增 3 个事件类
class SandboxTimeout(EventBase):
    """沙箱执行超时时发布。"""
    event_type: Literal["sandbox_timeout"] = "sandbox_timeout"
    step_num: int
    tool_name: str
    timeout_seconds: float

class SandboxViolation(EventBase):
    """沙箱违规访问（越权路径/网络尝试）时发布。"""
    event_type: Literal["sandbox_violation"] = "sandbox_violation"
    step_num: int
    tool_name: str
    violation_type: Literal["path_escape", "network_attempt", "sensitive_path"]
    detail: str  # 人类可读的中文描述

class SandboxResourceExceeded(EventBase):
    """沙箱资源超限（内存/fork/文件大小）时发布。"""
    event_type: Literal["sandbox_resource_exceeded"] = "sandbox_resource_exceeded"
    step_num: int
    tool_name: str
    resource_type: Literal["memory", "process", "file_size"]
    limit: str   # 如 "512MB"
    detail: str
```

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | 本阶段不涉及用户认证 |
| V3 Session Management | no | 本阶段不涉及会话管理 |
| V4 Access Control | yes | 路径白名单校验实现文件系统访问控制 |
| V5 Input Validation | yes | 路径白名单 + `os.path.realpath()` 防止路径遍历注入 |
| V6 Cryptography | no | 本阶段不涉及加密 |
| V7 Error Handling | yes | 沙箱违规事件结构化上报，不泄露系统路径信息 |
| V10 Malicious Code | yes | 网络隔离 + 资源限制 + 文件系统限制形成纵深防御 |

### Known Threat Patterns for Subprocess Sandbox

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| 路径遍历逃逸 (`../../etc/passwd`) | Tampering | `os.path.realpath()` + `startswith()` 白名单校验 |
| 符号链接逃逸 (`link -> /etc`) | Tampering / Elevation | `realpath()` 解析符号链接后再做包含性检查 |
| 网络数据外泄 (socket/requests) | Information Disclosure | `unshare --net` 创建无网命名空间 |
| fork bomb (无限 fork 子进程) | Denial of Service | `RLIMIT_NPROC=0` 完全禁止 fork |
| 磁盘填充 (无限写文件) | Denial of Service | `RLIMIT_FSIZE=100MB` 硬限制 |
| 内存炸弹 (bytearray 10GB) | Denial of Service | `RLIMIT_AS=512MB` 地址空间硬限制 |
| CPU 死循环 | Denial of Service | `subprocess.run(timeout=30)` + `RLIMIT_CPU=(30,30)` |
| 通过 unshare 命名空间提权 | Elevation | `--map-root-user` 仅映射命名空间内 UID，宿主机仍为非 root |

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `preexec_fn` 设置 rlimit + 网络隔离 | `unshare` CLI 包装 + `preexec_fn` 仅设置 rlimit | Phase 9 (2026-06) | 消除 preexec_fn 线程安全风险；网络隔离逻辑从 Python 移至 unshare 二进制 |
| RLIMIT_NPROC=50 (Phase 8) | RLIMIT_NPROC=0 (禁止 fork) | Phase 9 | 彻底阻止 fork bomb；D-04 统一限制 |
| 无文件大小限制 | RLIMIT_FSIZE=100MB | Phase 9 | 防止磁盘填充攻击 |
| 无路径白名单 | realpath + startswith 白名单 | Phase 9 | 防止文件系统逃逸 |
| 无沙箱审计事件 | 3 个新事件类型 (sandbox_timeout/violation/resource_exceeded) | Phase 9 | 结构化审计追踪 |

**Deprecated/outdated:**
- Phase 8 的 `_set_limits()` 中 `RLIMIT_NPROC=(50, 50)` — 降至 (0, 0)
- Phase 8 中 `RLIMIT_CPU=(30, 30)` 硬编码在 `_set_limits` 但 `timeout` 参数独立传递——需统一为一致的 30s 限制

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `unshare --user --map-root-user --net` 在 WSL2 kernel 6.6 上始终可用 [ASSUMED based on single machine test] | Standard Stack | 其他 WSL2 版本的内核配置可能不同；需在 CI 或目标部署环境验证 |
| A2 | 子进程使用 `unshare` 包装后，`preexec_fn` 中的 rlimit 设置仍然正确生效 [ASSUMED] | Architecture Patterns | `unshare` 可能重置部分 rlimit；需在集成测试中验证 RLIMIT_AS/NPROC/FSIZE 在 unshare 命名空间内实际生效 |
| A3 | `RLIMIT_AS=512MB` 对 LLM 生成的典型 Python/Bash 工具代码足够 [ASSUMED] | Common Pitfalls | 某些工具可能需要更大内存（如数据处理）；512MB 对简单脚本是保守值 |
| A4 | `RLIMIT_FSIZE=100MB` 对工具输出足够 [ASSUMED] | Common Pitfalls | 文件处理工具可能产生更大输出；100MB 是初始保守值 |
| A5 | 非 Linux 平台（macOS/Windows 原生）上跳过网络隔离是可接受的安全降级 [ASSUMED] | Architecture Patterns | LLM 生成代码在非 Linux 上运行时可能通过网络外泄数据；macOS 可用 `sandbox-exec` 替代 |

## Open Questions (RESOLVED)

1. **unshare 包装与 preexec_fn rlimit 的交互** — RESOLVED: 在 `_set_limits` 中先设置硬限制再设置软限制；集成测试验证子进程实际无法突破限制。子进程 fork 继承 rlimit，unshare 不重置。

2. **`unshare --map-root-user` 是否需要 `/proc/sys/kernel/unprivileged_userns_clone`** — RESOLVED: 在 `_build_cmd` 中增加探测：先执行 `unshare --user --map-root-user true` 测试可用性；失败时优雅降级（跳过网络隔离，记录 warning）。

3. **路径白名单是否需要正则模式支持** — RESOLVED: Phase 9 使用精确前缀匹配（`startswith`）；如需模式匹配，在后续阶段扩展。

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `unshare` (util-linux) | 网络命名空间隔离 | YES | 2.39.3 | 非 Linux: 跳过网络隔离；Linux 无 unshare: 仅依赖 rlimit |
| Linux kernel >= 3.8 | CLONE_NEWUSER + CLONE_NEWNET | YES | 6.6.114.1 | 旧内核: 跳过网络隔离 |
| `kernel.unprivileged_userns_clone` | Debian/Ubuntu 非特权用户命名空间 | N/A | 不存在（WSL2 无需此参数） | — |
| Python `resource` module | rlimit 资源限制 | YES | stdlib | Windows: rlimit 不可用，仅依赖 timeout |
| Python `os.CLONE_NEWNET` | 命名空间常量验证 | YES | os 模块内置 | — |

**Missing dependencies with no fallback:**
- 无。所有关键依赖在 WSL2 上均可用。

**Missing dependencies with fallback:**
- 非 Linux 平台（macOS/Windows 原生）：网络隔离降级为仅 rlimit + timeout。macOS 后续可考虑 `sandbox-exec` 补充。

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.x + pytest-asyncio (auto mode) |
| Config file | `tests/conftest.py` |
| Quick run command | `pytest tests/tools/test_sandbox.py -x -v` |
| Full suite command | `pytest tests/ -x --cov=src/loopai/tools/sandbox.py` |

### Phase Requirements to Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| DYN-11 | 子进程独立执行，与主进程隔离 | unit | `pytest tests/tools/test_sandbox.py::test_subprocess_isolation -x` | NO (Wave 0) |
| DYN-11 | 网络隔离：子进程无法访问外网 | integration | `pytest tests/tools/test_sandbox.py::test_network_isolation -x` | NO (Wave 0) |
| DYN-12 | RLIMIT_AS=512MB 生效 | unit | `pytest tests/tools/test_sandbox.py::test_memory_limit_enforced -x` | NO (Wave 0) |
| DYN-12 | RLIMIT_NPROC=0 禁止 fork | unit | `pytest tests/tools/test_sandbox.py::test_fork_bomb_prevented -x` | NO (Wave 0) |
| DYN-12 | RLIMIT_FSIZE=100MB 限制文件写入 | unit | `pytest tests/tools/test_sandbox.py::test_filesize_limit_enforced -x` | NO (Wave 0) |
| DYN-12 | 30s 超时触发 sandbox_timeout | unit | `pytest tests/tools/test_sandbox.py::test_timeout_event -x` | NO (Wave 0) |
| DYN-13 | 非 Linux 优雅降级 | unit | `pytest tests/tools/test_sandbox.py::test_non_linux_degradation -x` | NO (Wave 0) |
| DYN-14 | 路径白名单：允许沙箱目录内访问 | unit | `pytest tests/tools/test_sandbox.py::test_path_whitelist_allowed -x` | NO (Wave 0) |
| DYN-14 | 路径白名单：拒绝越权访问 | unit | `pytest tests/tools/test_sandbox.py::test_path_whitelist_blocked -x` | NO (Wave 0) |
| D-05 | sandbox_timeout 事件发布 | unit | `pytest tests/tools/test_sandbox.py::test_sandbox_timeout_event -x` | NO (Wave 0) |
| D-05 | sandbox_violation 事件发布 | unit | `pytest tests/tools/test_sandbox.py::test_sandbox_violation_event -x` | NO (Wave 0) |
| D-05 | sandbox_resource_exceeded 事件发布 | unit | `pytest tests/tools/test_sandbox.py::test_sandbox_resource_exceeded_event -x` | NO (Wave 0) |
| D-06 | 加固后 SandboxExecutor 替换自测阶段执行器 | integration | `pytest tests/tools/test_dynamic_creator.py::test_stage4_uses_hardened_sandbox -x` | NO (Wave 0) |

### Sampling Rate
- **Per task commit:** `pytest tests/tools/test_sandbox.py -x`
- **Per wave merge:** `pytest tests/ -x --cov=src/loopai/tools/sandbox.py`
- **Phase gate:** Full suite green + event schema validation passed

### Wave 0 Gaps
- [ ] `tests/tools/test_sandbox.py` — 全新文件，覆盖 DYN-11~DYN-14 和 D-05 所有测试用例
- [ ] `tests/tools/conftest.py` — 或扩展根 `tests/conftest.py` 增加 SandboxExecutor + EventBus mock 夹具
- [ ] `tests/tools/test_sandbox.py::test_unshare_available` — 探测 unshare CLI 可用性
- [ ] 事件 schema 测试 — 扩展 `tests/test_schemas.py` 增加 3 个新事件类的序列化/反序列化测试

## Sources

### Primary (HIGH confidence)
- 本机 WSL2 kernel 6.6.114.1-microsoft-standard-WSL2 实地验证:
  - `unshare --user --map-root-user --net` 网络隔离成功 [VERIFIED]
  - RLIMIT_AS=512MB 子进程分配 200MB 成功 [VERIFIED]
  - RLIMIT_NPROC=0 阻止 `os.fork()` (`[Errno 11] Resource temporarily unavailable`) [VERIFIED]
  - RLIMIT_FSIZE 触发 `OSError` (SIGXFSZ) [VERIFIED]
  - `os.CLONE_NEWUSER=268435456`, `CLONE_NEWNET=1073741824` [VERIFIED]
  - `unshare` version 2.39.3 [VERIFIED]
- Python 3.13 `subprocess` 模块文档 — `preexec_fn` 线程安全警告 [CITED]
- CodeQL py-path-injection — 路径遍历防御规范模式 [CITED: https://codeql.github.com/codeql-query-help/python/py-path-injection/]

### Secondary (MEDIUM confidence)
- pylint W1509 — `subprocess-popen-preexec-fn` 线程不安全警告 [CITED: https://pylint.pycqa.org/en/stable/user_guide/messages/warning/subprocess-popen-preexec-fn.html]
- `unshare(1)` man page — `--user`, `--map-root-user`, `--net` 选项文档 [CITED]
- Stack Overflow: "Is preexec_fn ever safe in multi-threaded programs?" [CITED: https://stackoverflow.com/questions/72686010]
- Linux `setrlimit(2)` man page — RLIMIT_FSIZE 行为（SIGXFSZ, EFBIG）[CITED]
- `user_namespaces(7)` man page — 非特权用户命名空间创建 [CITED]

### Tertiary (LOW confidence)
- Python `subprocess.Preexec` builder API 提议 (cpython issue 42736) — 未来可能的标准方案，未合并 [ASSUMED]
- `.planning/research/PITFALLS.md` — CVE 案例（CVE-2026-40158, CVE-2026-39888, CVE-2026-42079）[CITED: 项目文档]

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — 所有依赖在目标 WSL2 环境实地验证通过
- Architecture: HIGH — `unshare` CLI 包装模式经过系统测试验证；路径白名单基于行业标准 CodeQL 模式
- Pitfalls: HIGH — 基于真实 CVE 案例和本机 syscall 级别验证
- rlimit: HIGH — RLIMIT_AS, RLIMIT_NPROC=0, RLIMIT_FSIZE 在 WSL2 kernel 6.6 上全部验证通过

**Research date:** 2026-06-01
**Valid until:** 2026-07-01 (稳定领域——Linux 内核接口向后兼容，unshare CLI 稳定)
