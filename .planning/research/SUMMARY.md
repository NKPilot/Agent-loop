# Research Summary: Agent 动态工具创建系统 (v1.1)

**Project:** loopAI
**Milestone:** Agent 动态工具创建系统
**Date:** 2026-05-31
**Synthesized from:** STACK.md, FEATURES.md, ARCHITECTURE.md, PITFALLS.md

---

## Executive Summary

本次研究定义了一个"Agent 动态工具创建系统"——让 LLM Agent 在运行时自主生成 Python/Bash 代码，经安全校验和用户人工确认后，动态注册为可调用的工具。这不是一个独立的子系统，而是深度集成到现有 v1.0 ReAct Agent 架构的增强方案。

推荐的构建方法遵循"管道式创建 + 三层防御 + 人工确认门"模式。六阶段管道（语法检查 → 危险模块扫描 → 用户确认 → 沙箱自测 → 持久化 → ToolRegistry 注册）将 LLM 生成代码的风险面逐步收窄。Python 后端零新增 PyPI 依赖——所有沙箱隔离能力（`ast`、`subprocess`、`resource`、`importlib.util`、`tempfile`）均由 Python 3.12+ stdlib 提供。前端仅新增 `@monaco-editor/react` 一个依赖，覆盖代码展示和 diff 对比两个 UI 需求。

最大的风险来自安全领域。2025-2026 年至少 15 个公开 CVE 证明了进程内 Python 沙箱根本不可靠（CVSS 最高 10.0）。我们的防御策略是：AST 扫描做第一道快筛（不做信任边界），`subprocess` 子进程 + `resource.setrlimit` 硬限制做第二道隔离，用户人工确认做第三道也是唯一的安全门。动态工具永不获得 `PermissionLevel.SAFE`，永不可覆盖静态工具，描述必须经净化后才注入 system prompt。

---

## Key Findings

### 1. Stack — 零新增 Python 依赖，前端单依赖覆盖双需求

**核心发现：** 动态代码加载、安全扫描、沙箱隔离全部是 Python 3.12+ stdlib。这是刻意选择——RestrictedPython 太受限（禁 `open`/`subprocess`，动态工具需要这些能力），Docker 太重（学习项目不需要容器编排），而 stdlib 三层防御恰好匹配"LLM 生成 + 人工审核"的安全模型。

| 技术 | 来源 | 用途 | 关键决策 |
|------|------|------|----------|
| `ast.NodeVisitor` | stdlib 3.12+ | 预执行代码安全扫描——检测危险模块导入、危险函数调用、间接绕过模式 | 结果作为"风险提示"展示在前端，不做硬阻断 |
| `importlib.util` | stdlib 3.12+ | 项目级持久化工具的模块加载（三步法：spec→module→exec_module） | 替代已废弃的 `imp.load_source()`（3.12 已移除） |
| `subprocess` + `resource` | stdlib（Unix） | MODERATE/DANGEROUS 级别工具的隔离执行 + 内核级资源硬限制 | `preexec_fn` 设置 rlimit，子进程无法绕过 |
| `@monaco-editor/react` | npm (4.8.0-rc.3) | 代码展示（只读 Editor）+ diff 对比（DiffEditor） | React 19 用 `@next` tag；降级方案：@uiw/react-codemirror + @codemirror/merge |

**三种执行隔离策略：**

| 权限级别 | 执行方式 | 隔离措施 | 超时 |
|---------|---------|---------|------|
| SAFE | 当前进程 `exec()` + 受限 globals | `__builtins__` 替换为安全子集 | 30s |
| MODERATE | `subprocess` 子进程 | `preexec_fn` resource limits + `chdir` 沙箱目录 | 60s |
| DANGEROUS | `subprocess` 子进程 + 前端确认 | resource limits + 沙箱目录 + 网络禁用 + 用户确认弹窗 | 120s |

**来源：** STACK.md（置信度 HIGH——所有版本号经 npm/PyPI 验证，stdlib 模块经实际 import 验证）

### 2. Features — 9 项 MVP 必须，4 项 v1.1.x 验证后追加

**Table Stakes（缺失则不可用）：**

1. 代码语法校验（`ast.parse()` / `bash -n`）
2. 沙箱隔离执行（子进程 + 子目录 + 禁网）
3. 用户确认弹窗（代码展示 + 持久化级别选择 + 超时自动拒绝）
4. 工具持久化（文件系统存储，与现有 JSONL 范式一致）
5. `list_tools` 工具发现（system prompt 轻量概要 + 内置工具返回完整 Schema）
6. 运行时错误不崩溃（复用现有 ToolExecutor 4 层恢复管道）
7. 工具可禁用/删除（前端管理面板 + API 端点）

**核心 Differentiators（使系统从"能用"变"好用"）：**

1. **工具自测验证** — Agent 写 pytest 用例 → 沙箱执行 → 最多 3 轮迭代修复。这是 Replit Agent 3 的"独立验证 Agent"模式，显著降低用户审查负担
2. **三级持久化作用域** — 会话级（session 内可用）/ 沙箱级（同项目所有 session）/ 项目级（跨项目可用）。多数框架只有全局持久化
3. **diff 更新 + 命名冲突处理** — Agent 修改已有工具时展示新旧代码 diff，用户选择覆盖/重命名/拒绝
4. **复用现有 @tool 基础设施** — 动态工具使用相同的 `ToolMetadata` + `ToolRegistry` + `ToolExecutor` + `EventBus` 管道，是一等公民而非二等公民
5. **危险模块扫描** — AST 遍历检测危险 import，标记为 DANGEROUS 强制用户确认

**明确拒绝的 Anti-Features：**

- Agent 自主安装 pip 包（供应链风险）
- 无确认自动创建工具（= 任意代码执行）
- AST 黑名单进程内沙箱（CVE-2026-47392 已证明不可靠）
- 动态工具允许网络访问（数据外泄通道）
- Agent 修改系统级 @tool 工具（破坏系统完整性）
- 自动重试修复失败工具（不可控的代码演化）

**来源：** FEATURES.md（置信度 HIGH——基于 8 个竞品框架的对比分析 + 现有代码库分析）

### 3. Architecture — 事件驱动确认暂停 + 内置工具模式 + 管道式创建

**四种架构模式：**

1. **事件驱动确认暂停**（复用已有 ConfirmationRequired 模式）— Agent 循环在工具创建敏感点暂停，通过 EventBus 发布确认请求到前端，`asyncio.Event` 等待用户响应。与 v1.0 危险命令确认完全相同的模式。

2. **内置工具模式**（非 AgentTool）— `generate_tool` 是 `@tool` 装饰的普通 async 函数，不是子 Agent。LLM 调用它 → ToolExecutor 执行 → 内部管道完成确认暂停→注册流程。比 Agent-as-Tool 更轻量——不需要独立 EventBus、独立 Session、独立 FSM 子循环。

3. **六阶段管道** — DynamicToolCreator 内部实现有明确 gate 的多阶段流程：
   ```
   语法检查 → 危险模块扫描 → 用户确认(EventBus暂停) → 沙箱自测 → 持久化 → ToolRegistry注册
   ```
   每个阶段不通过则中止并返回结构化错误给 LLM。

4. **策略模式沙箱隔离** — SandboxExecutor 支持多种隔离策略（子进程 vs Docker），通过策略接口切换。v1.1 使用子进程策略。

**集成点——与现有组件对接精确：**

| 现有组件 | 修改级别 | 具体变更 |
|---------|---------|---------|
| `tools/registry.py` | **无需修改** | `register_meta()` 已支持动态注册 |
| `state_machine/fsm.py` | **无需修改** | generate_tool 是普通工具，通过已有管道执行 |
| `events/schemas.py` | 轻量 | 添加 6 个新事件模型 |
| `tools/types.py` | 轻量 | ToolMetadata 添加 `tool_type` 字段 |
| `tools/executor.py` | 轻量 | `_execute_once` 中增加 dynamic tool 路由 |
| `api/routes/control.py` | 轻量 | 添加 2 个确认端点 |
| 前端 `eventTypes.ts` | 轻量 | 添加 6 个新事件类型 |
| 前端 `uiStore.ts` | 中等 | 添加 `pendingToolCreation`、`toolCreationTab` 等状态 |
| `api/routes/tools.py` | **新增** | 工具管理 CRUD |
| `tools/dynamic_creator.py` | **新增** | DynamicToolCreator 核心 |
| `tools/sandbox.py` | **新增** | SandboxExecutor + DangerousModuleScanner |
| `tools/tool_persistence.py` | **新增** | ToolPersistenceManager |

**关键设计原则：** 动态工具使用 `dynamic.` 命名空间前缀 + 随机哈希后缀（如 `dynamic.a1b2c3d4_cleanup_cache`），防止与静态工具命名冲突。ToolRegistry 分区存储（`_static` / `_dynamic`），查询时优先返回静态工具。

**来源：** ARCHITECTURE.md（置信度 HIGH——基于现有代码库的精确对接点分析 + 竞品模式参考）

### 4. Pitfalls — 8 个关键陷阱，映射到不同开发阶段

| # | 陷阱 | 严重度 | 核心预防 | 处理阶段 |
|---|------|--------|----------|----------|
| P1 | AST/Regex 过滤被 Python 内省绕过 | CRITICAL | 永不信任进程内沙箱；外部隔离（子进程 + rlimit）为第二道防线 | Phase 1 + Phase 2 |
| P2 | Agent 生成包含漏洞的代码污染工具集 | CRITICAL | 7 步审计管线（语法→危险名称→I/O→环境变量→网络→子进程→自测）+ 用户人工确认 | Phase 1 → Phase 3 |
| P3 | 资源耗尽（死循环/内存炸弹/磁盘炸弹） | CRITICAL | `resource.setrlimit` 硬限制 + 独立进程 + 硬超时 SIGKILL | Phase 2 |
| P4 | 工具毒化——恶意工具污染 ToolRegistry 劫持 Agent | HIGH | 命名空间分离（`dynamic.` 前缀 + 哈希后缀）+ 描述净化 + 动态工具最低 MODERATE 级别 | Phase 1 → Phase 3 |
| P5 | 子进程沙箱逃逸（ctypes/sys.modules 传递访问） | HIGH | 危险模块全量列表（30+ 入口）+ import hook 植入 + 外部沙箱隔离 | Phase 1 → Phase 2 |
| P6 | 动态工具与静态工具集成冲突 | HIGH | ToolRegistry 分区存储 + EventBus 新事件类型 + PermissionGuard 分级确认 + CircuitBreaker 豁免 | Phase 1 → Phase 3 |
| P7 | 用户确认门被 LLM 绕过 | HIGH | 三阶段确认（系统检查→Agent 自测→人工确认）；永不自动放行；注册后观察期（前 5 次执行标记为"观察中"） | Phase 2 → Phase 3 |
| P8 | 持久化级别生命周期混淆 | MEDIUM | 清理合约（会话级关 hook 清理、沙箱级迁移通知、项目级版本化存储 + 永不自动删除） | Phase 2 → Phase 3 |

**关键安全原则（贯穿所有陷阱）：**
- 进程内 Python 沙箱从根本上不可靠（2026 年安全共识）。AST 扫描只做快筛，外部隔离做真正防御，用户确认做安全门。
- 动态工具永不可获得 `PermissionLevel.SAFE`。最低为 MODERATE。
- `ctypes`、`cffi` 及所有 C 接口必须在危险模块列表中。
- 工具描述在注入 system prompt 前必须净化（截断 500 字符 + 指令语言扫描 + 模板包装）。

**来源：** PITFALLS.md（置信度 HIGH——基于 2025-2026 年 15+ 真实 CVE 披露、代码审计报告和框架安全公告）

---

## Implications for Roadmap

### Suggested Phase Structure

基于依赖关系、风险面和复杂度，建议分 4 个阶段构建：

#### Phase 1: 动态工具创建核心（MVP）

**交付物：** Agent 能提议工具 → 语法检查 + 危险扫描 → 用户前端确认 → 注册到 ToolRegistry → Agent 可调用

**包含功能：**
- ToolMetadata 扩展（`is_dynamic`, `source_code`, `persistence_scope`, `enabled`）
- 代码语法校验（`ast.parse()` + `bash -n`）
- DangerousModuleScanner（AST 全量危险名称扫描——30+ 入口的完整列表）
- DynamicToolCreator（管道阶段 1-3、5-6；阶段 4 沙箱自测推迟到 Phase 2）
- `create_tool` 内置工具（Agent 结构化入口）
- ToolRegistry 分区存储（`_static` / `_dynamic` + `register_dynamic()` 专用方法）
- 6 个新事件类型扩展到 EventBus
- 前端 ToolCreationDialog（代码展示 + 持久化级别 + 审批/拒绝）
- 基础工具持久化（沙箱级 `.sandbox/tools/` + 项目级扫描加载）
- `list_tools` 工具 + system prompt 动态工具概要注入
- 工具可禁用/删除（API + 前端基础管理）

**必须在此阶段处理的陷阱：** P1（AST 扫描 + 完整封堵列表）、P2（审计管线阶段 1-4）、P4（命名空间分离 + 冲突检测）、P5（全量危险模块扫描）、P6（分区存储 + EventBus 扩展）

**可推迟：** 沙箱自测（Phase 2）、三级持久化（Phase 2）、外部沙箱隔离（Phase 2 开始）、资源硬限制（Phase 2）

**需要研究：** 此阶段有非常完善的现有模式参考（已有 ConfirmationRequired 模式可复用）和详尽的架构设计文档。**可以跳过 `/gsd-research-phase` 直接进入 plan。**

---

#### Phase 2: 安全加固 + 沙箱隔离

**交付物：** 子进程隔离执行 + 硬资源限制（rlimit）+ 超时控制 + 沙箱自测验证

**包含功能：**
- SandboxExecutor（子进程 + 沙箱子目录 + 网络禁止）
- `resource.setrlimit` 硬限制（CPU 5s/10s、内存 256MB/512MB、进程数 50/100、文件大小 10MB/50MB）
- 独立超时控制（`signal.SIGALRM` + 硬超时 SIGKILL）
- AST 级资源防护（`while True` 检测、深度递归检测、大常量检测、最大节点数 500）
- import hook 植入（沙箱内拦截危险模块 + 子模块传递访问检查）
- 工具自测验证——Agent 写 pytest 用例 → 沙箱执行 → 最多 3 轮迭代修复
- CircuitBreaker 前 3 次执行豁免动态工具
- 持久化版本存储 + 清理合约

**必须在此阶段处理的陷阱：** P1（外部沙箱隔离）、P3（资源硬限制）、P5（import hook + 外部隔离使 Python 级绕过变为无效）、P7（三阶段确认流程 + 注册后观察期）、P8（清理合约 + 版本存储）

**需要研究：** 外部沙箱隔离（seccomp-bpf / Landlock / nsjail）的具体 Linux 配置。如果 WSL2 限制某些特性，可能需要降级方案。**建议在 plan 阶段对此做 `/gsd-research-phase`。**

---

#### Phase 3: 用户体验 + 工具管理

**交付物：** 完整的前端工具管理面板 + 三级持久化 + diff 更新 + 动态工具与静态工具完整 UI 区分

**包含功能：**
- 前端 ToolManager Tab——集中管理所有动态工具（查看代码、启用/禁用、删除、导出）
- 三级持久化完整实现（会话级内存 + 沙箱级文件 + 项目级文件）
- 工具更新 + diff 展示（Monaco DiffEditor side-by-side 对比）
- PermissionGuard 适配动态工具确认（payload 含代码预览、持久化级别、沙箱范围）
- 注册后观察期 UI（前 5 次执行高亮展示）
- 前端持久化级别视觉标签（会话/沙箱/项目用不同 Badge 区分）
- 软删除 + 回收站（24h 内可恢复）
- 实时命名冲突检测（前端即时反馈）
- 工具执行失败的结构化错误展示

**必须在此阶段处理的陷阱：** P6（PermissionGuard 分级确认 + 前端差异化 UI）、P7（观察期高亮展示）、P8（前端持久化级别标注 + 迁移提示）

**标准模式：** 此阶段主要是 UI 实现和现有模式的扩展，有 shadcn/ui 组件库和已有前端模式参考。**可以跳过 deep research，直接 plan。**

---

#### Phase 4: 集成验证 + 性能优化 + 异常恢复

**交付物：** 端到端验证 + 工具发现优化 + 恢复策略 + 评分系统

**包含功能：**
- 端到端集成测试（静态/动态工具并存场景全覆盖）
- "Looks Done But Isn't" 清单逐项验证
- 工具发现优化（索引文件 `tool_index.json` + 内存缓存，解决 50+ 工具时的扫描性能）
- 工具执行记录缓存（避免每次执行前重复安全扫描）
- 动态工具代码长度计入 token 统计（CostGuard 扩展）
- JSONL 日志区分 `dynamic_tool_created` 和 `dynamic_tool_executed` 两条事件
- Checkpoint/Recovery 同步（项目级工具纳入检查点）
- 会话关闭强制清理链验证（包括 `kill -9` 场景）
- 工具评分/使用统计（调用次数、成功率、平均延迟），自动建议禁用低质量工具

**需要研究：** Checkpoint/Recovery 与动态工具的集成细节。**可能需要 `/gsd-research-phase`。**

---

### Phase Dependencies

```
Phase 1 (核心创建)
  ├──→ Phase 2 (安全加固) — Phase 2 依赖 Phase 1 的动态工具注册和使用流程
  ├──→ Phase 3 (UX/管理) — Phase 3 依赖 Phase 1 的基本确认和注册
  └──→ Phase 4 (验证/优化) — Phase 4 依赖所有前置阶段
```

Phase 2 和 Phase 3 可以并行开发——两者都依赖 Phase 1 完成，但彼此独立。

---

## Research Flags

### Needs `/gsd-research-phase` during planning

| Phase | Research Topic | Why |
|-------|---------------|-----|
| **Phase 2** | WSL2 环境下的外部沙箱隔离方案（seccomp-bpf / Landlock / nsjail 的 Linux 配置和 WSL2 兼容性） | 当前设计基于 Unix 通用假设，WSL2 可能有特定限制。需要实际验证 syscall 过滤在 WSL2 内核上的可用性 |
| **Phase 2** | Python 3.13 的 `preexec_fn` 与 `resource.setrlimit` 在子进程中的交互行为 | 3.13 引入实验性 io_uring 后端，需要验证是否影响 fork 后的 rlimit 设置时机 |
| **Phase 4** | Checkpoint/Recovery 与动态工具的集成 | 项目级工具需要纳入检查点，会话级工具需要从检查点排除。需要研究现有 Checkpoint 机制的具体实现 |

### Can skip research (well-documented patterns)

| Phase | Why Skip |
|-------|----------|
| **Phase 1** | 管道式确认模式完全复用 v1.0 的 ConfirmationRequired → ConfirmationResponse 机制；AST 扫描有详尽代码示例（SecurityVisitor 类）；Monaco Editor 在 Vite 8 中零配置 |
| **Phase 3** | 前端 UI 模式完全基于 shadcn/ui 组件库和已有 ConfirmationDialog 模式；diff 展示是 Monaco DiffEditor 的标准用法 |

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| **Stack** | **HIGH** | 零新增 Python 依赖（全部 stdlib，已验证 import）；前端单依赖版本号经 `npm view` 验证；React 19 兼容性有明确降级方案（@uiw/react-codemirror） |
| **Features** | **HIGH** | 基于 8 个竞品框架（Anvil SDK, Meta-Tools, AutoLearn, Koda, mini_claw, Pydantic AI, OpenAI Agents SDK, smolagents）的对比分析；MVP 定义有明确的 P1/P2/P3 优先级矩阵 |
| **Architecture** | **HIGH** | 基于现有代码库的精确对接点分析（已读取 `registry.py`, `executor.py`, `fsm.py`, `schemas.py`, `control.py`, `main.py`, `guards.py`, `bash.py`, `command_classifier.py`）；4 种架构模式有详细代码示例和与现有 AgentTool 模式的对比 |
| **Pitfalls** | **HIGH** | 基于 2025-2026 年 15+ 真实 CVE（CVE-2026-40158, CVE-2026-39888, CVE-2026-42079, CVE-2026-27952, CVE-2026-30856, CVE-2026-44339 等）、安全审计报告（Fox-IT, Datadog, DryRun Security）和框架安全公告（PraisonAI, smolagents, PPTAgent, Agenta） |

### Gaps to Address During Planning

1. **WSL2 外部沙箱兼容性：** `resource` 模块在 WSL2 上已确认可用，但 `seccomp-bpf` / `Landlock` 等更高级的 syscall 过滤需要实际验证。Phase 2 的 plan 阶段需调研 WSL2 内核版本对 Landlock 的支持状态。

2. **Monaco Editor React 19 兼容性：** `@monaco-editor/react@next` (4.8.0-rc.3) 是 release candidate。如果遇到稳定性问题，降级到 `@uiw/react-codemirror@4.25.10` + `@codemirror/merge@6.12.1`。Phase 1 的 plan 阶段应选定最终方案。

3. **大规模工具场景的性能边界：** 50+ 项目级工具时的启动扫描性能、100+ 工具时 system prompt 膨胀问题。当前已设计了索引缓存和 tool 发现分离策略，但未做实际性能基准测试。

4. **CLI 模式下的确认交互：** 当前确认流程假设 Web 前端可用。CLI 模式（Rich 终端）需要适配文本版确认流程。Phase 1 plan 阶段需决定是否 MVP 仅支持 Web 模式，CLI 支持推迟。

---

## Sources

### 现有代码库（主源，HIGH confidence）
- `src/loopai/tools/registry.py` — ToolRegistry.register_meta() 接口
- `src/loopai/tools/executor.py` — ToolExecutor 4 层恢复管道
- `src/loopai/state_machine/fsm.py` — ReActFSM._handle_act 工具管道
- `src/loopai/state_machine/guards.py` — GuardPipeline（BudgetGuard, LoopDetector, PermissionGuard 等）
- `src/loopai/tools/bash.py` — Bash 工具安全模式（shell=False + shlex + 元字符扫描）
- `src/loopai/tools/command_classifier.py` — CommandClassifier（白名单/黑名单 + 路径感知）
- `src/loopai/events/schemas.py` — 13 个事件模型 + Event 联合类型
- `src/loopai/api/routes/control.py` — 确认端点模式
- `src/loopai/main.py` — create_agent_components 工厂
- `src/loopai/agents/tool.py` — AgentTool 桥接模式
- `src/loopai/resilience/circuit_breaker.py` — CircuitBreaker 熔断

### 竞品框架分析（MEDIUM-HIGH confidence）
- Anvil SDK — JIT tool generation from intent (PyPI)
- Meta-Tools-and-Agents — dynamic tool loading + editor pattern (GitHub)
- AutoLearn MCP — natural language to Python skill (PyPI)
- Koda — DiscoverTools lazy loading pattern (GitHub)
- mini_claw — list_tools() for prompt injection (docs.rs)
- Pydantic AI — Tool constructor for dynamic registration (official docs)
- OpenAI Agents SDK — @function_tool decorator (official GitHub)
- Replit Agent 3 — dual-agent self-testing pattern (blog)
- Microsoft Agent Framework + CodeAct + Hyperlight microVM (official devblog)

### 安全研究（HIGH confidence — 真实 CVE + 安全审计）
- CVE-2026-40158, CVE-2026-39888 — PraisonAI AST/sandbox 绕过
- CVE-2026-42079 — PPTAgent eval() 直接执行
- CVE-2026-27952 — Agenta RestrictedPython + numpy 沙箱逃逸
- CVE-2026-30856 — Tencent WeKnora 工具名遮盖 + 间接提示注入
- CVE-2026-44339 — PraisonAI globals()/__main__ 回退
- Fox-IT — smolagents CodeAgent 不安全 import 白名单
- Datadog Security Labs — 动态上下文 shell 执行绕过
- DryRun Security — 87% AI agent PR 含漏洞
- CoSAI OASIS — Tool Registry Poisoning (TRP) 风险定义

### 沙箱架构（MEDIUM confidence — 技术博客和实践指南）
- Execution Sandboxes for AI Agents (sourcetrail.com)
- How to Sandbox AI Agents in 2026 (dev.to)
- Notes on Sandboxing Untrusted Code (GitHub gist)
- MCP Security Patterns 2026: gVisor vs Firecracker (dev.to)
- Awesome Agent Runtime Security (GitHub)

---

*Research synthesized: 2026-05-31*
*Ready for: `/gsd-roadmap` or Phase 1 planning*
