# Phase 9: 安全加固与沙箱隔离 - Context

**Gathered:** 2026-05-31
**Status:** Ready for planning

## Phase Boundary

本阶段将 Phase 8 的基础 SandboxExecutor 升级为真正的安全边界。在现有 subprocess + rlimit 基础上增量增加：网络隔离（网络命名空间）、文件系统白名单校验、沙箱违规独立审计事件。不改动 SandboxExecutor 的公开接口，所有加固在内部透明实现。

## Implementation Decisions

### 加固方式
- **D-01:** 增量增强现有 SandboxExecutor，不创建新类。子进程隔离、rlimit 已存在，本阶段叠加网络隔离、文件校验、审计事件。

### 网络隔离
- **D-02:** 使用 Linux network namespace（`unshare(CLONE_NEWNET)`）创建无网子进程。WSL2 内核支持 namespace。非 Linux 平台优雅降级（跳过网络隔离，记录 warning）。

### 文件系统隔离
- **D-03:** 路径白名单模式。子进程 cwd 设为沙箱专用目录，read/write 操作前校验目标路径在白名单内（默认仅工具专用目录 + 用户确认时授予的额外目录）。拒绝访问 `/etc`、`/proc`、`~/.ssh` 等敏感路径。

### 资源限制
- **D-04:** 所有动态工具统一限制：30s 超时、512MB 内存（RLIMIT_AS）、RLIMIT_NPROC=0（禁止 fork）、RLIMIT_FSIZE=100MB。用户确认时不提供自定义选项。

### 审计日志
- **D-05:** 新增 3 个沙箱违规事件类型：`sandbox_timeout`、`sandbox_violation`（越权访问/网络尝试）、`sandbox_resource_exceeded`。每个事件通过 EventBus 发布并写入 JSONL 审计日志。

### 与 Phase 8 的关系
- **D-06:** Phase 8 的 `_stage4_self_test`（自测阶段）使用未经加固的 SandboxExecutor。Phase 9 加固后的 SandboxExecutor 替换自测阶段的执行器，确保自测也在安全环境中运行。

## Canonical References

### 项目文档
- `.planning/PROJECT.md` — v1.1 里程碑目标
- `.planning/REQUIREMENTS.md` — DYN-11~DYN-14 需求定义
- `.planning/ROADMAP.md` — 阶段 9 详细定义

### 现有代码
- `src/loopai/tools/sandbox.py` — SandboxExecutor（加固目标，Phase 8 创建）
- `src/loopai/tools/dynamic_creator.py` — DynamicToolCreator._stage4_self_test()（调用 SandboxExecutor）
- `src/loopai/events/schemas.py` — EventBus 事件类型（需新增 3 个沙箱事件）
- `frontend/src/lib/eventTypes.ts` — 前端事件类型（需同步新增）

### 研究参考
- `.planning/research/PITFALLS.md` — CVE 案例：进程内沙箱绕过
- `.planning/research/ARCHITECTURE.md` — 沙箱执行器架构集成点

## Existing Code Insights

### Reusable Assets
- **SandboxExecutor** — 已有 `execute(code, language)` → dict 接口，`preexec_fn` 设置 rlimit。加固不改接口。
- **DangerousModuleScanner** — 39 入口静态扫描，Phase 9 可增加 `socket`、`requests` 等网络模块到禁止列表。
- **EventBus schemas** — 已有 ToolCreationRequested 等事件模式，新增 3 个沙箱事件复用相同结构。

### Integration Points
- **SandboxExecutor.execute()** — 在 `preexec_fn` 中增加 network namespace 创建
- **DynamicToolCreator._stage4_self_test()** — 替换为加固后的 SandboxExecutor
- **EventBus** — 新增 `sandbox_timeout`、`sandbox_violation`、`sandbox_resource_exceeded` 事件

## Specific Ideas

- network namespace 隔离后的子进程：`lo` 接口存在但无外网路由，`ping 8.8.8.8` 失败
- 路径白名单校验：所有文件操作（open/write/read）检查路径是否以白名单目录开头
- 沙箱违规前端展示：在 ToolCreationDialog 自测结果区域标红显示违规详情

## Deferred Ideas

无。讨论保持在阶段范围内。

---

*Phase: 9-security-hardening*
*Context gathered: 2026-05-31*
