# Phase 8: 动态工具创建核心 (MVP) - Research

**Researched:** 2026-05-31
**Domain:** Agent 动态工具创建 -- LLM 生成 Python/Bash 代码，经管道式验证后注册为可调用工具
**Confidence:** HIGH (基于现有代码库精确集成点分析 + 先期研究文档 + 实时版本验证)

## Summary

Phase 8 实现动态工具创建的完整最小闭环：Agent 通过 `generate_tool` 内置工具提交代码 -> 串行语法检查 + 危险扫描 -> EventBus 发布确认事件 -> 前端 ToolCreationDialog 弹窗等待用户操作 -> Agent 自测代码在沙箱执行 -> 三级持久化注册到 ToolRegistry。

**关键约束：零新增 Python 依赖。** 所有动态代码加载（`importlib.util`）、安全扫描（`ast.NodeVisitor`）、沙箱执行（`subprocess` + `resource.setrlimit`）、临时目录（`tempfile.mkdtemp`）均使用 Python 3.13 stdlib。前端唯一新增依赖为 `@monaco-editor/react`（代码展示 + 语法高亮）。

**架构模式：管道式创建，非子 Agent 循环。** `generate_tool` 是 `@tool` 装饰的内置工具（Built-in-Tool 模式），内部执行 6 阶段串行管道（语法检查 -> 危险扫描 -> 用户确认 -> 沙箱自测 -> 持久化 -> 注册），而非启动独立 ReAct 子循环。这比 AgentTool 模式更轻量，完全复用主 EventBus 和现有 ToolExecutor 管道。

**Primary recommendation:** 通过 `ToolRegistry.register_meta()` 复用已有注册接口；通过 EventBus + `asyncio.Event` 暂停机制复用已有 ConfirmationRequired 模式；新建独立的 `DynamicToolCreator` 类封装 6 阶段管道，与现有 BashTool/disk_tools 同级放在 `src/loopai/tools/` 目录。

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| generate_tool 内置工具注册与执行 | API / Backend | -- | ToolRegistry + ToolExecutor 管道，Agent 调用时触发 |
| Python/Bash 语法检查 (ast.parse / bash -n) | API / Backend | -- | 纯后端处理，无外部依赖 |
| 危险模块/命令扫描 (DangerousModuleScanner) | API / Backend | -- | AST NodeVisitor 扫描，完全在 Python 进程内 |
| 确认事件发布与等待 (tool_creation_requested) | API / Backend | Frontend Server (SSE) | EventBus 发布 + SSE 推送到前端 + asyncio.Event 阻塞等待 |
| 工具创建确认弹窗 (ToolCreationDialog) | Browser / Client | API / Backend | React 组件渲染，通过 REST confirm-tool-creation 端点回传 |
| Agent 自测执行 (SandboxExecutor) | API / Backend | -- | subprocess 子进程隔离执行，Phase 9 加固 |
| 三级持久化 (会话/沙箱/项目) | API / Backend | Database / Storage | 内存 dict + .sandbox/tools/ 文件系统 + src/loopai/tools/dynamic/ |
| ToolRegistry register_meta() 注册 | API / Backend | -- | 复用已有接口，构造 ToolMetadata 直接注册 |
| Monaco Editor 代码展示（只读 + 语法高亮） | Browser / Client | -- | @monaco-editor/react Editor 组件，前端独立渲染 |
| SSE 事件流推送 | Frontend Server (SSR) | API / Backend | 已有 SSE Bridge 复用 |
| 持久化级别选择 + 目录权限配置 | Browser / Client | -- | shadcn/ui Select + Input 组件 |

## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Agent 调用 `generate_tool` 时传完整参数：`name`（工具名）、`description`（描述）、`code`（Python/Bash 代码）、`test_code`（测试用例代码）、`language`（"python"\|"bash"）。系统验证后使用 Agent 提供的名称和描述。
- **D-02:** Agent 显式提供 JSON Schema（`param_schema` 字段），系统验证格式后直接使用。不做代码自动提取类型提示。
- **D-03:** 新建独立的 `ToolCreationDialog` 组件，不复用/不扩展现有 `ConfirmationDialog`。功能差异大——需要代码展示（Monaco Editor 语法高亮）、持久化级别选择、目录权限配置。
- **D-04:** 确认弹窗无超时，一直等待用户操作。Agent 处于 WAITING 状态直到用户响应。
- **D-05:** 流程：语法检查 → 危险扫描 → 前端确认弹窗（用户看到代码+风险标记+自测代码）→ 用户确认后在沙箱中执行 Agent 提供的测试用例 → 测试结果（通过/失败/输出）展示 → 测试通过则注册工具。
- **D-06:** 分级别处理：确认后工具立即注册到内存（ToolRegistry）。会话级永远留在内存。沙箱级和项目级在工具**首次执行成功**后才写入文件系统。
- **D-07:** 持久化路径：沙箱级 `.sandbox/tools/{tool_name}/`，项目级 `src/loopai/tools/dynamic/{tool_name}.py`。
- **D-08:** 串行执行：先 `ast.parse()`（Python）或 `bash -n`（Bash）语法检查 → 通过后才执行危险模块/命令扫描 → 两项都通过才发布 `tool_creation_requested` 事件。任一失败返回结构化错误给 Agent。
- **D-09:** 动态工具以 `dynamic.{name}` 命名空间注册到 ToolRegistry，与静态工具（`bash.*`、`disk.*`）隔离。使用 `ToolRegistry.register_meta()` 直接注册（复用 Phase 6 AgentTool 模式）。

### Claude's Discretion

无。全部决策由用户确认。

### Deferred Ideas (OUT OF SCOPE)

无。讨论保持在阶段范围内。

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| DYN-01 | Agent 通过 `generate_tool` 内置工具提交 Python 或 Bash 代码 | Built-in-Tool 模式 -- @tool 装饰注册，ToolExecutor 管道执行 |
| DYN-02 | 系统自动执行语法检查（`ast.parse()` / `bash -n`），失败时返回结构化错误给 Agent | Python 3.13 stdlib `ast` 模块（稳定，支持 match/case）；`bash -n` 通过 subprocess 执行 |
| DYN-03 | 危险模块/命令扫描（覆盖 30+ 入口如 `os`、`subprocess`、`ctypes`、`socket`、`eval`、`exec` 等），扫描结果标记在确认弹窗中 | PITFALLS.md 全量 DANGEROUS_MODULES 列表（35+ 模块）；ast.NodeVisitor 访问者模式 |
| DYN-04 | 自动从代码中提取工具元数据（名称、描述、参数 schema），以 `dynamic.{hash[:8]}_{name}` 命名空间注册 | Agent 显式提供全部元数据（D-02）；系统用 `dynamic.` 前缀 + hash 后缀构造全限定名 |
| DYN-05 | ToolCreationDialog 展示代码（Monaco Editor 语法高亮，只读模式） | @monaco-editor/react v4.8.0-rc.3 (React 19)；Editor 组件 readOnly + syntax highlighting |
| DYN-06 | 用户选择持久化级别：会话级 / 沙箱级 / 项目级 | shadcn/ui RadioGroup + Select；ToolPersistenceManager 三级存储 |
| DYN-07 | 用户可指定额外目录权限（默认仅访问工具专用沙箱子目录） | shadcn/ui Input + Badge 标签列表；传递给 SandboxExecutor working_dir 配置 |
| DYN-08 | 用户确认或拒绝后，结果通过 EventBus 事件回传给 Agent | tool_creation_confirmed / tool_creation_rejected 事件；复用 ConfirmationResponse 模式 |
| DYN-09 | 语法检查通过后，Agent 在隔离沙箱中执行自测用例，验证工具能正常调用并返回预期结果 | SandboxExecutor (subprocess + tempfile.mkdtemp)；子进程隔离执行 |
| DYN-10 | 自测结果（通过/失败/输出日志）展示在确认弹窗中供用户审查 | TestResult 数据结构 (status + output + error)；ToolCreationDialog 展示区域 |
| DYN-24 | 会话级——工具仅在内存中注册，会话结束自动清理 | 内存 dict；ToolRegistry 移除注册；Session.on_close 钩子触发清理 |
| DYN-25 | 沙箱级——工具保存到 `.sandbox/tools/{tool_name}/`，后续会话启动时自动加载 | ToolPersistenceManager.save() + .sandbox/tools/ 目录；启动时扫描加载 |
| DYN-26 | 项目级——工具保存为 `src/loopai/tools/dynamic/{tool_name}.py`，可 git 提交 | ToolPersistenceManager.save_project()；importlib.util.spec_from_file_location() 加载 |

## Standard Stack

### Core (Python Backend -- Zero New PyPI Dependencies)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| **ast** | (stdlib 3.12+) | Python 代码语法检查 + 危险模块扫描 | `ast.parse()` 结构化语法验证；`ast.NodeVisitor` 遍历检测禁止的 import/call/attribute 模式。零依赖，3.12+ 稳定支持 match/case 新语法节点 [VERIFIED: Python 3.13.13 stlib import] |
| **importlib.util** | (stdlib 3.4+) | 项目级动态工具模块加载 | `spec_from_file_location()` -> `module_from_spec()` -> `exec_module()` 三步法。取代已废弃的 `imp.load_source()`（3.12 已移除）。支持正确的 `__name__`/`__package__` 语义 [CITED: docs.python.org/3/library/importlib.html] |
| **subprocess** | (stdlib 3.12+) | Bash 语法检查 + Agent 自测隔离执行 | `subprocess.run(args_list, shell=False, timeout=N, capture_output=True, cwd=sandbox_dir)`。与已有 BashTool 安全模式一致 [VERIFIED: 现有代码 src/loopai/tools/bash.py] |
| **resource** | (stdlib, Unix) | 子进程资源硬限制 | `setrlimit(RLIMIT_CPU, RLIMIT_AS, RLIMIT_FSIZE, RLIMIT_NPROC)`。WSL2 完全支持。Phase 8 做基础限制，Phase 9 加固 [VERIFIED: import resource succeeded on Python 3.13.13] |
| **tempfile** | (stdlib) | 沙箱子目录创建 | `tempfile.mkdtemp(prefix="tool_sandbox_")` 每次执行创建独立临时目录 [VERIFIED: import tempfile succeeded] |
| **shlex** | (stdlib) | Bash 语法检查 `bash -n` 参数安全拼接 | 已有依赖。用于 `shlex.quote(filepath)` 安全传递 Bash 文件路径 [VERIFIED: 现有代码 src/loopai/tools/bash.py] |
| **json** | (stdlib) | JSON Schema 验证（param_schema 字段） | `json.loads()` 验证 Agent 提供的 param_schema 是合法 JSON [VERIFIED: 现有代码] |

### Core (Frontend -- One New Dependency)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| **@monaco-editor/react** | 4.8.0-rc.3 (React 19) | 代码展示 + 语法高亮（只读 Editor） | VS Code 内核，Python/Bash 语法高亮开箱即用。单依赖覆盖代码展示需求。Phase 10 可升级使用 DiffEditor [VERIFIED: npm view @monaco-editor/react@next -> 4.8.0-rc.3] |
| **@monaco-editor/react** (fallback) | 4.7.0 (stable) | 同上，React 16-18 稳定版 | 如果 4.8.0-rc.3 不稳定，降级方案 [VERIFIED: npm view @monaco-editor/react -> 4.7.0] |

### Supporting (Existing Stack -- No Changes)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| **shadcn/ui** | CLI v4 | ToolCreationDialog 组件构建 (Card, Dialog, Select, RadioGroup, Alert, Badge, Input, Button, ScrollArea) | 所有弹窗 UI 元素 [VERIFIED: frontend/package.json shadcn ^4.8.2] |
| **zustand** | 5.x | uiStore 扩展 pendingToolCreation 状态管理 | 已有 uiStore，添加 toolCreationDialog 相关状态 [VERIFIED: frontend/package.json zustand ^5.0.14] |
| **lucide-react** | 1.x | 工具创建相关图标 (Hammer, ShieldAlert, Code2, TestTube, HardDrive) | ToolCreationDialog 内图标元素 [VERIFIED: frontend/package.json lucide-react ^1.17.0] |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| **ast (stdlib)** | **RestrictedPython 8.1** | RestrictedPython 太受限——动态工具需要文件 I/O 和 subprocess 调用系统命令。且已有多起 CVE 绕过。在"LLM 生成 + 人工审核"安全模型下是过度工程 [CITED: .planning/research/STACK.md] |
| **@monaco-editor/react** | **@uiw/react-codemirror v4.25 + @codemirror/merge v6.12** | CodeMirror 更轻量 (~300KB vs Monaco ~5MB) 且 React 19 兼容性更好。但代码展示品质不如 Monaco。作为 Monaco 不稳定时的降级方案 [CITED: .planning/research/STACK.md] |
| **subprocess + resource** | **Docker / gVisor** | CLAUDE.md 明确声明 "Docker adds operational complexity before the core logic is solid"。Phase 8 仅需基础隔离，Phase 9 加固 [CITED: CLAUDE.md, .planning/research/STACK.md] |
| **独立 ToolCreationDialog** | **复用 ConfirmationDialog** | 用户决定 D-03：ToolCreationDialog 功能差异大（代码展示、持久化级别、目录权限），必须独立实现 [CITED: 08-CONTEXT.md D-03] |

**Installation:**

```bash
# Python 后端 -- 无新增 PyPI 依赖！
# ast, importlib.util, subprocess, resource, tempfile, shlex 全部是 Python 3.12+ stdlib

# 前端 -- 唯一新增依赖
cd frontend

# React 19 兼容版（推荐，项目使用 React 19.2.6）
pnpm add @monaco-editor/react@next

# 稳定版降级方案
# pnpm add @monaco-editor/react@4.7.0
```

**Version verification:** `@monaco-editor/react` 4.7.0 (stable) published 2025-07; 4.8.0-rc.3 published 2026-Q1. Python 3.13.13 stdlib modules all confirmed importable [VERIFIED: 2026-05-31].

## Architecture Patterns

### System Architecture Diagram

```
Agent LLM 调用 generate_tool(name, description, code, test_code, language, param_schema)
        │
        ▼
┌── ToolExecutor (已有) ───────────────────────────────────────────────────────┐
│  识别 tool_name == "generate_tool" → 正常参数校验 → 调用 func_ref           │
└──────────────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌── DynamicToolCreator.generate_tool() (新增) ─────────────────────────────────┐
│                                                                              │
│  [Stage 1: 语法检查]                                                         │
│    ├─ Python: ast.parse(code) → SyntaxError? → 返回结构化错误给 Agent        │
│    └─ Bash: tempfile + bash -n → 非零退出? → 返回结构化错误给 Agent           │
│                                                                              │
│  [Stage 2: 危险扫描]                                                         │
│    ├─ Python: DangerousModuleScanner(ast.NodeVisitor).scan(code)              │
│    │   → 检测禁止 import/call/attribute 模式 → 返回风险标记列表               │
│    └─ Bash: 危险命令正则扫描 (rm -rf, dd, mkfs, curl|wget pipe, etc.)        │
│                                                                              │
│  [Stage 3: 用户确认 -- EventBus 暂停]                                        │
│    ├─ tool_id = "dynamic.{hash[:8]}_{name}"                                  │
│    ├─ await bus.publish("tool_creation_requested", {                         │
│    │     confirmation_id, tool_id, name, code, language,                     │
│    │     risk_flags, test_code, param_schema                                │
│    │   })                                                                    │
│    └─ await asyncio.Event().wait()  ← 无超时（D-04）                         │
│        ├─ 用户拒绝 → 返回 "用户拒绝创建工具"                                   │
│        └─ 用户确认 → 继续                                                     │
│                                                                              │
│  [Stage 4: 沙箱自测]                                                         │
│    ├─ SandboxExecutor.execute(test_code + code, cwd=sandbox_dir)             │
│    ├─ 将 test_result (status + output + error) 发布到 EventBus               │
│    └─ 自测失败 → 返回结构化错误 + 测试输出给 Agent                            │
│                                                                              │
│  [Stage 5: 持久化]                                                           │
│    ├─ 会话级: 跳过文件写入（仅内存注册）                                       │
│    ├─ 沙箱级: ToolPersistenceManager.save_to_sandbox()                       │
│    └─ 项目级: ToolPersistenceManager.save_to_project()                       │
│                                                                              │
│  [Stage 6: 注册]                                                             │
│    └─ registry.register_meta(meta) → ToolMetadata 构造                       │
│                                                                              │
│  返回 ToolResult.success("工具 dynamic.a1b2c3d4_my_tool 已创建并注册")        │
└──────────────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌── EventBus → SSE Bridge → Frontend (Stage 3 确认数据流) ────────────────────┐
│                                                                              │
│  SSE event: tool_creation_requested                                          │
│    ├─ eventStore.appendEvent() → 存储事件                                    │
│    └─ uiStore.setPendingToolCreation(event) → 触发 UI 状态                   │
│                                                                              │
│  ToolCreationDialog 渲染:                                                    │
│    ├─ Monaco Editor (readOnly, language="python"|"shell")                    │
│    ├─ 危险模块 Badge 列表 (risk_flags 映射为 badge 颜色 + 标签)               │
│    ├─ 自测代码预览 (collapsible 区域)                                         │
│    ├─ 持久化级别 RadioGroup: 会话级 / 沙箱级 / 项目级                          │
│    ├─ 目录权限 Input + Badge 标签列表                                         │
│    └─ [批准] [拒绝] 按钮                                                      │
│                                                                              │
│  用户点击批准:                                                                │
│    POST /api/sessions/{session_id}/confirm-tool-creation                     │
│      body: { confirmation_id, approved: true, persistence, extra_dirs }     │
│    ├─ control.confirm_tool_creation() → DynamicToolCreator.respond()         │
│    └─ asyncio.Event.set() → Stage 4 解除阻塞                                 │
│                                                                              │
│  自测结果 SSE 事件 (Stage 4 完成):                                            │
│    tool_creation_test_result → Dialog 内展示                                 │
│                                                                              │
│  工具创建成功 SSE 事件 (Stage 6 完成):                                         │
│    tool_created → Dialog 关闭 + AgentTimeline 显示成功卡片                    │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Recommended Project Structure

```
src/loopai/
├── tools/
│   ├── dynamic_creator.py     # DynamicToolCreator (新增) -- generate_tool 内置工具
│   ├── sandbox.py              # SandboxExecutor + DangerousModuleScanner (新增)
│   ├── tool_persistence.py     # ToolPersistenceManager (新增) -- 三级持久化读写
│   ├── dynamic/                # 项目级持久化工具存放目录 (新增)
│   │   └── .gitkeep
│   ├── executor.py             # (修改: _execute_once 中检测 tool_type=="dynamic"→路由沙箱)
│   ├── registry.py             # (修改: 命名空间分区 _static / _dynamic)
│   ├── types.py                # (修改: ToolMetadata 添加 tool_type, is_dynamic 字段)
│   └── prompt_builder.py       # (修改: build_system_prompt 追加动态工具说明)
├── events/
│   └── schemas.py              # (修改: 添加 6 个新事件模型 + 更新 Event 联合类型)
├── api/
│   ├── routes/
│   │   ├── control.py          # (修改: 添加 confirm_tool_creation 端点)
│   │   └── tools.py            # (新增: GET/DELETE /tools/dynamic)
│   └── schemas.py              # (修改: 添加 ConfirmToolCreationRequest, ToolSummary 等)
├── state_machine/
│   └── fsm.py                  # (修改: WAITING 状态处理工具创建暂停——或无需修改)
├── main.py                     # (修改: create_agent_components 注册 generate_tool)
└── .sandbox/
    └── tools/                  # 沙箱级持久化工具目录
        └── .gitignore

frontend/src/
├── components/
│   ├── ToolCreationDialog.tsx  # (新增) -- 工具创建确认弹窗
│   └── ToolDetail.tsx          # (修改: 区分静态/动态工具展示)
├── stores/
│   ├── uiStore.ts              # (修改: 添加 pendingToolCreation 等状态)
│   └── eventStore.ts           # (修改: 处理新事件类型更新工具调用列表)
├── lib/
│   ├── eventTypes.ts           # (修改: 添加 6 个新事件接口 + 更新 Event 联合类型)
│   └── api.ts                  # (修改: 添加 confirmToolCreation, fetchDynamicTools API)
└── hooks/
    └── useSSE.ts               # (无需修改 -- 已有 SSE 事件路由)
```

### Pattern 1: Built-in-Tool 管道模式 (非 AgentTool 子循环)

**What:** `generate_tool` 是 `@tool` 装饰的内置工具，LLM 调用它时 ToolExecutor 正常执行，内部完成 6 阶段串行管道后返回 ToolResult。与 Agent-as-Tool 模式的关键区别：不启动独立 ReAct 循环，不创建子 Session。

**When to use:** 当操作需要 LLM 作为触发者但实际执行不需要独立推理循环时——工具创建是确定性步骤（语法检查 -> 确认 -> 注册），不需要子 Agent 循环。

**Example:**
```python
# 通过 @tool 装饰器将 generate_tool 注册为内置工具
# Source: 现有 AgentTool 模式 (src/loopai/agents/tool.py) + CONTEXT.md D-09

class DynamicToolCreator:
    """Agent 调用的 generate_tool 内置工具 -- 管道式创建。"""

    async def generate_tool(
        self,
        name: str,
        description: str,
        code: str,
        test_code: str,
        language: str,
        param_schema: dict,
    ) -> ToolResult:
        """6 阶段串行管道：语法检查 -> 危险扫描 -> 用户确认 -> 沙箱自测 -> 持久化 -> 注册"""
        start = time.time()

        # Stage 1: 语法检查
        syntax_result = await self._check_syntax(code, language)
        if syntax_result.is_error:
            return syntax_result

        # Stage 2: 危险扫描
        risk_flags = await self._scan_danger(code, language)

        # Stage 3: 用户确认 (EventBus 暂停)
        approved, config = await self._request_user_confirmation(
            name, code, language, risk_flags, test_code, param_schema
        )
        if not approved:
            return ToolResult.error("用户拒绝创建工具", ...)

        # Stage 4: 沙箱自测
        test_result = await self._run_self_test(code, test_code, language, config)
        if test_result.is_error:
            return test_result

        # Stage 5: 持久化
        await self._persist(code, name, config.persistence_level)

        # Stage 6: 注册
        meta = self._build_metadata(name, description, code, language, param_schema, config)
        self._registry.register_meta(meta)

        return ToolResult.success(
            data=f"工具 dynamic.{name} 已创建并注册",
            duration_ms=(time.time() - start) * 1000,
        )
```

### Pattern 2: 事件驱动确认暂停 (复用 ConfirmationRequired 模式)

**What:** DynamicToolCreator 通过 EventBus 发布确认事件到前端，通过 `asyncio.Event` 阻塞等待用户响应。这与 v1.0 的 PermissionGuard -> ConfirmationRequired -> ConfirmationResponse 模式完全相同。

**When to use:** DynamicToolCreator 的 Stage 3 用户确认——展示代码 + 风险 + 自测 + 配置选项，等待用户批准或拒绝。

**Key differences from existing ConfirmationRequired:**
- 事件 payload 更丰富：`code`（完整源代码）、`risk_flags`（危险标记列表）、`test_code`（自测代码）、`param_schema`（参数 schema）
- 无超时（D-04）：`await event.wait()` 不使用 `asyncio.wait_for`
- 响应 payload 包含 `persistence` 和 `extra_dirs` 等配置字段
- 前端独立 ToolCreationDialog 组件（不复用 ConfirmationDialog）

### Pattern 3: AST NodeVisitor 安全扫描器

**What:** 通过 `ast.NodeVisitor` 子类遍历 Python AST，检测禁止的 import、函数调用和属性访问模式。不做代码执行，仅做静态结构分析。

**When to use:** Stage 2 危险扫描——在代码执行前快速拦截明显危险模式。不做信任边界（PITFALLS.md Pitfall 1），仅做第一道防线。

**Example:**
```python
# Source: .planning/research/STACK.md + PITFALLS.md DANGEROUS_MODULES list
class DangerousModuleScanner(ast.NodeVisitor):
    FORBIDDEN_IMPORTS = {
        "os", "subprocess", "sys", "ctypes", "cffi", "mmap",
        "gc", "code", "types", "marshal", "pickle", "imp",
        "importlib", "pdb", "bdb", "inspect", "multiprocessing",
        "socket", "requests", "httpx", "urllib", "http",
        "signal", "tracemalloc", "faulthandler", "traceback",
    }
    FORBIDDEN_CALLS = {"eval", "exec", "compile", "__import__", "breakpoint", "open"}
    BYPASS_PATTERNS = {"__subclasses__", "__bases__", "__globals__",
                       "__code__", "__traceback__", "tb_frame", "f_back"}

    def __init__(self):
        self.issues: list[dict] = []  # [{type, line, message, severity}]

    def visit_Import(self, node): ...
    def visit_ImportFrom(self, node): ...
    def visit_Call(self, node): ...
    def visit_Attribute(self, node): ...
```

### Pattern 4: 三级持久化策略模式

**What:** ToolPersistenceManager 根据持久化级别执行不同的存储逻辑。会话级仅内存注册（不做文件写入），沙箱级写入 `.sandbox/tools/{name}/`，项目级写入 `src/loopai/tools/dynamic/{name}.py` 并使用 `importlib.util` 加载。

**When to use:** Stage 5 持久化 + Stage 6 注册。会话级和沙箱级在首次执行成功后才写文件（D-06）。

### Anti-Patterns to Avoid

- **动态工具与静态工具共享扁平命名空间:** 导致命名冲突、工具毒化、LLM 误选。必须使用 ToolRegistry 分区存储（`_static` + `_dynamic`）[CITED: PITFALLS.md Pitfall 4]
- **AST-only 安全扫描作为唯一防线:** Python 内省机制（`().__class__.__bases__[0].__subclasses__()`）可绕过所有源码级检查。AST 扫描仅做第一道快筛，必须配合用户确认 + Phase 9 外部沙箱隔离 [CITED: PITFALLS.md Pitfall 1]
- **用 AgentTool 模式实现 generate_tool:** 工具创建是确定性步骤，不需要独立 ReAct 循环。启动子 Agent 增加延迟和复杂度 [CITED: ARCHITECTURE.md Anti-Pattern 5]
- **自动批准 Agent 自测通过的工具:** LLM 可生成刻意回避危险路径的自测用例。必须经过人工确认（D-04 无超时）[CITED: PITFALLS.md Pitfall 7]
- **确认弹窗复用 ConfirmationDialog:** D-03 明确要求独立 ToolCreationDialog——功能差异大（代码展示、持久化级别、目录权限）[CITED: 08-CONTEXT.md D-03]

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Python 代码语法验证 | 自定义正则解析器 | `ast.parse()` (stdlib) | 正则无法正确处理字符串内嵌代码、注释、装饰器、f-string、match/case。ast 模块是 Python 规范的标准实现 [VERIFIED: Python 3.13 stdlib] |
| Python 代码危险模式检测 | grep/regex 关键词匹配 | `ast.NodeVisitor` 结构化遍历 | 正则匹配 `import os` 但会被 `import\\nos`、变量赋值、字符串内嵌绕过。AST 结构化分析无歧义 [CITED: PITFALLS.md Pitfall 1] |
| 动态加载 .py 文件 | `exec()` 或手动 import | `importlib.util.spec_from_file_location()` | exec() 无模块语义（无 `__name__`/`__package__`），无法被 `sys.modules` 缓存。importlib.util 是 Python 3.4+ 推荐的动态加载方式 [CITED: docs.python.org] |
| Web 代码编辑器（语法高亮） | 手写 textarea + Prism/highlight.js | `@monaco-editor/react` Editor (readOnly) | Monaco 内建 Python/Bash 语法高亮、行号、缩进辅助、Bracket matching。手写编辑器在这些场景无法达到 VS Code 品质 [VERIFIED: npm @monaco-editor/react] |
| Bash 语法检查 | 自定义 Bash parser | `bash -n` (subprocess 执行) | Bash 语法有复杂的上下文敏感规则（here-doc、嵌套命令替换、数组语法）。`bash -n` 是唯一权威的语法检查方式 [CITED: .planning/research/STACK.md] |
| 临时目录管理 | `os.mkdir()` + 手动清理 | `tempfile.mkdtemp()` (stdlib) | mkdtemp 提供唯一随机名称、原子创建、系统默认 temp 位置。手动管理易产生命名冲突和安全漏洞 [VERIFIED: Python 3.13 stdlib] |
| 确认流程暂停/恢复 | `time.sleep()` 轮询 | EventBus + `asyncio.Event` | 已有 ConfirmationRequired 模式——PermissionGuard 通过 EventBus 发布事件 + asyncio.Event.wait() 暂停，前端 REST 端点恢复 [VERIFIED: 现有代码 src/loopai/api/routes/control.py] |
| 工具元数据构造与注册 | 手写 register() 或修改 @tool 装饰器 | `ToolRegistry.register_meta()` | 已有接口——AgentTool (Phase 6) 已通过此方法注册，DynamicToolCreator 复用同一接口 [VERIFIED: 现有代码 src/loopai/tools/registry.py] |

**Key insight:** Phase 8 的核心挑战不是"写什么代码"，而是"如何安全地集成到我已有的 Agent 基础设施中"。所有关键机制（工具注册、事件驱动确认、管道执行）都已有成熟模式——DynamicToolCreator 只需要将它们串接成 6 阶段管道。

## Runtime State Inventory

> Phase 8 是绿色功能开发阶段（非 rename/refactor/migration），不需要 Runtime State Inventory 章节。本阶段新建组件，不修改任何运行时的存储数据、服务配置、OS 注册状态或构建产物。

## Common Pitfalls

### Pitfall 1: ToolRegistry 扁平命名空间导致工具毒化

**What goes wrong:** 动态工具以 `disk_cleaner` 注册到扁平 Registry，与静态工具 `disk.cleaner` 或后续动态工具同名。LLM 无法区分来源，可能误选恶意动态工具替代安全静态工具。

**Why it happens:** 现有 ToolRegistry 使用单一 `_tools: dict[str, ToolMetadata]`（扁平命名空间）。CONTEXT.md D-09 要求 `dynamic.` 命名空间前缀，但需要 Registry 端严格执行分区。

**How to avoid:** 修改 ToolRegistry 为分区存储——`_static_tools` + `_dynamic_tools`。动态工具注册时强制加 `dynamic.` 前缀 + 8 位 hash 后缀（如 `dynamic.a1b2c3d4_cleanup`）。查找时跨分区查询，优先返回静态工具。`_static_tools` 不可被动态工具覆盖。

**Warning signs:** 动态工具名以 `bash.` 或 `disk.` 开头；LLM 倾向选择动态工具替代静态工具。

### Pitfall 2: 确认弹窗数据过大拖慢 SSE

**What goes wrong:** `tool_creation_requested` 事件 payload 包含完整源代码（可能 10KB+），通过 SSE 推送到前端。如果代码过大，SSE 消息可能被拆分为多个 chunk，导致 JSON 解析失败或前端渲染延迟。

**Why it happens:** SSE 在传输层有消息大小限制（部分代理服务器限制 64KB），且前端 JSON 解析大字符串有性能开销。当前确认事件 `confirmation_required` payload 很小（~200 字节），`tool_creation_requested` 可能达到 50KB。

**How to avoid:** SSE 事件中仅传代码摘要 + `code_hash` + 前 500 字符预览。完整代码通过 REST 端点获取：`GET /api/tools/dynamic/{tool_id}/preview`。前端 Dialog 打开时异步加载完整代码。

**Warning signs:** SSE 事件 JSON 大小 > 16KB；前端接收到不完整的 JSON 字符串。

### Pitfall 3: 动态工具 func_ref 持有主 Session 引用导致内存泄漏

**What goes wrong:** DynamicToolCreator 构造 ToolMetadata 时，`func_ref` 闭包捕获了 `self`（DynamicToolCreator 实例）或主 Session 对象。导致工具注册后 DynamicToolCreator 无法释放，Session 关闭后工具仍持有引用。

**Why it happens:** Python 闭包自动捕获外部作用域变量。构造 `func_ref` 时如果使用 lambda/内部函数引用 `self`，会导致循环引用。

**How to avoid:** `func_ref` 应该是独立的 async 函数，仅接收参数 + 内部调用 SandboxExecutor，不持有 DynamicToolCreator 或 Session 引用。使用 standalone async function 而非 method binding。

**Warning signs:** 多次创建删除动态工具后内存持续增长；`sys.getrefcount()` 显示 Session 对象引用计数 > 预期。

### Pitfall 4: 沙箱自测定时失败误杀正常工具

**What goes wrong:** SandboxExecutor 自测超时设置过短（如 5s），而合法工具（如遍历大目录）需要 15-20 秒。导致功能正常的工具因超时被拒绝注册。

**Why it happens:** Agent 无法准确估计工具执行时间。固定超时无法适应所有工具类型。

**How to avoid:** 沙箱自测使用与工具注册超时相同的配置（默认 30s，可调至 120s）。Agent 在 `generate_tool` 中可以指定 `self_test_timeout` 参数。超时后在确认弹窗中显示"自测超时（N秒）"而非标记为"失败"。

**Warning signs:** 多个工具因超时被拒；Agent 生成的测试用例涉及大文件扫描或网络操作。

### Pitfall 5: 前端 Dialog 组件未处理 SSE 断连状态

**What goes wrong:** ToolCreationDialog 打开时 SSE 连接断开（网络波动或后端重启）。用户点击"批准"后 POST 请求成功但 SSE 已失效，后续 `tool_created` 事件无法推送，Dialog 永远不关闭。

**Why it happens:** ToolCreationDialog 依赖 SSE 事件流（`tool_created`、`tool_creation_test_result`）更新 UI 状态。SSE 断连时没有超时机制。

**How to avoid:** POST `/confirm-tool-creation` 后，前端启动一个轮询超时（如 60s），定期 GET session status。如果超时未收到 SSE 事件，前端主动查询工具注册状态。"批准"按钮点击后变为 loading 状态，禁止重复点击。

**Warning signs:** 用户点击批准后 Dialog 一直显示 loading；SSE 重连后 Dialog 状态不一致。

## Code Examples

### DynamicToolCreator: 6 阶段管道核心

```python
# Source: ARCHITECTURE.md pipeline pattern + CONTEXT.md D-05/D-08
class DynamicToolCreator:
    """Agent 调用的 generate_tool 内置工具 -- 6 阶段管道式创建。"""

    def __init__(
        self,
        registry: ToolRegistry,
        bus: EventBus,
        session_id: str,
        sandbox: SandboxExecutor,
        persistence: ToolPersistenceManager,
    ):
        self._registry = registry
        self._bus = bus
        self._session_id = session_id
        self._sandbox = sandbox
        self._persistence = persistence
        self._pending_confirmations: dict[str, tuple[asyncio.Event, dict]] = {}

    async def generate_tool(
        self,
        name: str,
        description: str,
        code: str,
        test_code: str,
        language: str,
        param_schema: dict,
    ) -> ToolResult:
        """LLM 调用此工具的入口点。"""
        start = time.time()
        tool_id = self._make_tool_id(name)

        # Stage 1: 语法检查
        syntax_ok, syntax_error = await self._check_syntax(code, language)
        if not syntax_ok:
            return ToolResult.error(
                f"语法检查失败 ({language}): {syntax_error}",
                duration_ms=(time.time() - start) * 1000,
            )

        # Stage 2: 危险扫描
        risk_flags = await self._scan_danger(code, language)

        # Stage 3: 用户确认 (EventBus 暂停, 无超时 -- D-04)
        approved, config = await self._request_user_confirmation(
            confirmation_id=tool_id,
            tool_name=name,
            tool_id=tool_id,
            code=code,
            language=language,
            risk_flags=risk_flags,
            test_code=test_code,
            param_schema=param_schema,
        )
        if not approved:
            return ToolResult.error("用户拒绝创建工具", ...)

        # Stage 4: 沙箱自测
        test_ok, test_output = await self._run_self_test(
            code, test_code, language, config.extra_dirs
        )
        # 发布自测结果到 EventBus
        await self._bus.publish("tool_creation_test_result", {
            "event_type": "tool_creation_test_result",
            "session_id": self._session_id,
            "tool_name": name,
            "status": "passed" if test_ok else "failed",
            "output": test_output,
        })

        if not test_ok:
            return ToolResult.error(f"自测失败: {test_output}", ...)

        # Stage 5 & 6: 持久化 + 注册
        await self._persist_and_register(
            tool_id=tool_id,
            name=name,
            description=description,
            code=code,
            language=language,
            param_schema=param_schema,
            persistence_level=config.persistence_level,
            extra_dirs=config.extra_dirs,
        )

        return ToolResult.success(
            data=f"工具 {tool_id} 已创建并注册 ({config.persistence_level}级持久化)",
            duration_ms=(time.time() - start) * 1000,
        )
```

### 确认暂停/恢复机制

```python
# Source: 现有 PermissionGuard 模式 (src/loopai/api/routes/control.py confirm_session)
async def _request_user_confirmation(self, ...):
    """发布确认事件并等待用户响应 -- 无超时 (D-04)"""
    confirmation_id = str(uuid.uuid4())[:8]
    wait_event = asyncio.Event()
    self._pending_confirmations[confirmation_id] = (wait_event, None)

    await self._bus.publish("tool_creation_requested", {
        "event_type": "tool_creation_requested",
        "session_id": self._session_id,
        "confirmation_id": confirmation_id,
        "tool_name": tool_name,
        "tool_id": tool_id,
        "code": code,
        "language": language,
        "risk_flags": risk_flags,
        "test_code": test_code,
        "param_schema": param_schema,
    })

    # 无超时 -- D-04
    await wait_event.wait()

    _, config = self._pending_confirmations.pop(confirmation_id, (None, None))
    return config is not None and config.get("approved", False), config

def respond(self, confirmation_id: str, approved: bool, config: dict):
    """由 confirm-tool-creation 端点调用"""
    if confirmation_id in self._pending_confirmations:
        event, _ = self._pending_confirmations[confirmation_id]
        self._pending_confirmations[confirmation_id] = (event, config)
        event.set()
```

### Confirm API 端点

```python
# Source: 现有 confirm_session 端点 (src/loopai/api/routes/control.py)
@router.post("/sessions/{session_id}/confirm-tool-creation")
async def confirm_tool_creation(
    session_id: str,
    body: ConfirmToolCreationRequest,
    request: Request,
) -> dict:
    """响应待处理的工具创建确认请求。"""
    active_sessions = request.app.state.active_sessions

    if session_id not in active_sessions:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    entry = active_sessions[session_id]
    dynamic_creator = entry.get("dynamic_creator")
    if dynamic_creator is None:
        raise HTTPException(status_code=404, detail="No dynamic tool creator for session")

    if body.confirmation_id not in dynamic_creator._pending_confirmations:
        raise HTTPException(status_code=404, detail="Confirmation not found or already responded")

    dynamic_creator.respond(
        body.confirmation_id,
        body.approved,
        {"persistence_level": body.persistence, "extra_dirs": body.extra_dirs},
    )

    return {"confirmation_id": body.confirmation_id, "approved": body.approved, "responded": True}
```

### Frontend ToolCreationDialog (核心结构)

```typescript
// Source: 独立组件 -- D-03; 参考现有 ConfirmationDialog + uiStore 模式
interface ToolCreationDialogProps {
  event: ToolCreationRequestedEvent;
  onApprove: (config: ToolCreationConfig) => Promise<void>;
  onReject: (confirmationId: string) => Promise<void>;
}

// uiStore 扩展
interface UIState {
  pendingToolCreation: ToolCreationRequestedEvent | null;
  // ... existing fields
}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| 仅静态工具（@tool 装饰器） | 静态 + 动态工具并存 | Phase 8 | Agent 可自主扩展工具体系 |
| 扁平 ToolRegistry | 分区存储 (_static + _dynamic) | Phase 8 | 防命名冲突和工具毒化 |
| 仅危险命令确认弹窗 | 新增 ToolCreationDialog | Phase 8 | 代码展示、持久化配置、风险标记 |
| AST 扫描做信任边界 | AST 扫描仅做快筛 + 人工确认做最终安全门 | Phase 8 (PITFALLS.md) | 降低逃逸风险，Phase 9 加固 |
| 无动态代码执行 | subprocess 子进程隔离执行 | Phase 8 基础 / Phase 9 加固 | 安全执行 LLM 生成代码 |

**Deprecated/outdated:**
- `imp.load_source()`: Python 3.12 已移除。使用 `importlib.util.spec_from_file_location()` 替代。
- `SourceFileLoader.load_module()`: 已废弃。使用 `module_from_spec()` + `exec_module()` 替代。

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `@monaco-editor/react@next` (4.8.0-rc.3) 与 React 19.2.6 兼容且在开发期间稳定 | Standard Stack | 需降级到 CodeMirror 方案 (@uiw/react-codemirror + @codemirror/merge)，包体积更小但 diff 展示不如 Monaco 精致 |
| A2 | `resource.setrlimit()` 在 WSL2 中完全可用 | Standard Stack | STATE.md 记录 WSL2 外部沙箱兼容性待验证。如果部分 RLIMIT_* 常量不可用，需在 Phase 9 中降级到仅 subprocess 超时控制 |
| A3 | 用户确认后 `activate_sessions[session_id]["dynamic_creator"]` 可正常访问 | Code Examples | 如果 create_agent_components 未正确传递 dynamic_creator 到 active_sessions，API 端点将 404 |
| A4 | ToolMetadata 的 `is_dynamic` / `tool_type` 字段不会破坏现有序列化逻辑 | Architecture Patterns | JSONL 日志和 OpenAI schema 序列化使用 `model_dump()` + `exclude`，新字段默认值向后兼容 |

## Open Questions

1. **generate_tool 的 ToolMetadata 如何构建 `func_ref`（动态工具的实际可调用对象）?**
   - What we know: `func_ref` 需要是一个接受参数并返回结果的 async callable。动态工具的 func_ref 内部调用 SandboxExecutor.execute() 而非直接执行代码
   - What's unclear: 如何将动态工具的 code + param_schema 映射为可调用的 Python 对象。选项 A: 用 `exec()` 在受限命名空间执行代码提取函数（会话级）。选项 B: 始终通过 SandboxExecutor 子进程执行（项目级/沙箱级）
   - Recommendation: 使用选项 B（始终子进程执行）——安全性一致，避免 exec() 在进程内执行带来的逃逸风险。func_ref 是一个包装函数，负责：参数序列化 -> subprocess 调用 -> 结果反序列化

2. **DYN-04 命名空间 `dynamic.{hash[:8]}_{name}` 的 hash 计算输入是什么?**
   - What we know: CONTEXT.md 要求 hash[:8] 后缀
   - What's unclear: hash 基于什么计算？(code 内容? timestamp? random?)
   - Recommendation: 使用 code 内容的 SHA256 前 8 位——相同代码生成相同 hash，便于 Agent 识别"我已经创建过这个工具"。格式：`dynamic.{sha256(code)[:8]}_{name}`

3. **确认弹窗展示自测代码 + 用户确认后执行自测——是否需要二次确认?**
   - What we know: D-05 说用户确认后在沙箱中执行自测。用户确认时看到代码+风险+自测代码
   - What's unclear: 自测失败后是否需要用户再次确认（如"自测失败，仍要注册吗?"），还是自动拒绝
   - Recommendation: 自测失败自动拒绝并返回错误给 Agent（Agent 可修改代码重试）。不增加二次确认——如果有问题 Agent 修好后重新走完整管道

4. **沙箱级和项目级工具"首次执行成功"的判定时机是什么?**
   - What we know: D-06 要求首次执行成功后才写文件
   - What's unclear: "首次执行"指 Agent 自测（Stage 4）还是用户创建后第一次真实调用？
   - Recommendation: 指 Stage 4 沙箱自测成功。如果自测通过则立即持久化 + 注册。如果自测失败则不持久化，等待 Agent 修改代码后重试。这符合 D-05 的流程（测试通过则注册）

5. **`build_system_prompt` 如何注入动态工具列表?**
   - What we know: DYN-22 要求启动时扫描持久化工具并注入 system prompt。Phase 8 不包含 DYN-22（Phase 10 实现），但系统提示注入是 Phase 8 创建工具后立即可用的前提
   - What's unclear: Phase 8 是否需要在 `build_system_prompt` 中追加已注册的动态工具列表
   - Recommendation: 是。`build_system_prompt` 追加 "## 动态工具" 段落，列出当前会话中已注册的动态工具（名称 + 描述）。否则 Agent 创建工具后不知道如何调用。仅追加会话级已注册的动态工具——沙箱级和项目级由 Phase 10 的启动扫描处理

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.13 | 后端所有 stdlib 模块 | Yes | 3.13.13 | -- |
| ast module | Stage 1 语法检查 + Stage 2 危险扫描 | Yes | stdlib 3.13 | -- |
| importlib.util | Stage 6 项目级工具加载 | Yes | stdlib 3.13 | -- |
| subprocess | Stage 1 bash -n + Stage 4 沙箱自测 | Yes | stdlib 3.13 | -- |
| resource.setrlimit | Stage 4 资源限制 | Yes (Unix/WSL2) | stdlib 3.13 | -- |
| tempfile | Stage 4 沙箱子目录 | Yes | stdlib 3.13 | -- |
| bash | Stage 1 Bash 语法检查 | Yes | WSL2 bash | -- |
| Node.js 22+ | 前端 Vite 8 | Yes | LTS | -- |
| pnpm | 前端依赖管理 | Yes | -- | npm |
| @monaco-editor/react | ToolCreationDialog 代码展示 | -- | 4.7.0 (stable) | @uiw/react-codemirror + @codemirror/merge |

**Missing dependencies with no fallback:**
- None. 所有依赖均可满足。

**Missing dependencies with fallback:**
- @monaco-editor/react 4.8.0-rc.3: 如不稳定，降级到 CodeMirror (@uiw/react-codemirror 4.25 + @codemirror/merge 6.12)

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.x + pytest-asyncio |
| Config file | `pyproject.toml` (`[tool.pytest.ini_options]`) |
| Quick run command | `pytest tests/test_dynamic_creator.py -x -v` |
| Full suite command | `pytest tests/ -x -v --timeout=30` |

### Phase Requirements -> Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| DYN-01 | generate_tool 作为内置工具注册到 ToolRegistry，LLM 可调用 | unit | `pytest tests/test_dynamic_creator.py::test_generate_tool_registered -x` | No (Wave 0) |
| DYN-02 | Python ast.parse() 语法错误返回结构化错误；bash -n 非零退出返回错误 | unit | `pytest tests/test_dynamic_creator.py::test_syntax_check_python_error -x` | No (Wave 0) |
| DYN-02 | 语法正确代码通过检查 | unit | `pytest tests/test_dynamic_creator.py::test_syntax_check_python_ok -x` | No (Wave 0) |
| DYN-03 | DangerousModuleScanner 检测 os/subprocess/ctypes/eval/exec 等 30+ 入口 | unit | `pytest tests/test_sandbox.py::test_dangerous_scan_30plus -x` | No (Wave 0) |
| DYN-03 | 安全代码（math/json/datetime import）不触发扫描告警 | unit | `pytest tests/test_sandbox.py::test_dangerous_scan_clean -x` | No (Wave 0) |
| DYN-04 | 工具元数据构造正确 -- dynamic.{hash[:8]}_{name} 命名空间 | unit | `pytest tests/test_dynamic_creator.py::test_metadata_namespace -x` | No (Wave 0) |
| DYN-05 | tool_creation_requested 事件 payload 包含完整字段 (code, language, risk_flags, test_code, param_schema) | unit | `pytest tests/test_dynamic_creator.py::test_creation_event_payload -x` | No (Wave 0) |
| DYN-06 | 确认弹窗 payload 包含 persistence_level 字段 | integration | `pytest tests/test_api_tools.py::test_confirm_persistence_level -x` | No (Wave 0) |
| DYN-07 | 用户可在确认弹窗中指定额外目录 | integration | `pytest tests/test_api_tools.py::test_confirm_extra_dirs -x` | No (Wave 0) |
| DYN-08 | 用户确认后 asyncio.Event 解除阻塞，tool_creation_confirmed 事件发布 | unit | `pytest tests/test_dynamic_creator.py::test_confirmation_flow -x` | No (Wave 0) |
| DYN-09 | SandboxExecutor 在隔离子进程中执行自测代码 | unit | `pytest tests/test_sandbox.py::test_self_test_execution -x` | No (Wave 0) |
| DYN-10 | 自测结果 event payload 包含 status + output + error | unit | `pytest tests/test_dynamic_creator.py::test_self_test_result_event -x` | No (Wave 0) |
| DYN-24 | 会话级工具在 Session 关闭时从 Registry 移除 | unit | `pytest tests/test_dynamic_creator.py::test_session_level_cleanup -x` | No (Wave 0) |
| DYN-25 | 沙箱级工具写入 .sandbox/tools/{tool_name}/ 目录 | unit | `pytest tests/test_tool_persistence.py::test_sandbox_persist -x` | No (Wave 0) |
| DYN-26 | 项目级工具写入 src/loopai/tools/dynamic/{tool_name}.py | unit | `pytest tests/test_tool_persistence.py::test_project_persist -x` | No (Wave 0) |

### Sampling Rate

- **Per task commit:** `pytest tests/test_dynamic_creator.py tests/test_sandbox.py tests/test_tool_persistence.py -x`
- **Per wave merge:** `pytest tests/ -x --timeout=30`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps

- [ ] `tests/test_dynamic_creator.py` -- 覆盖 DYN-01/02/04/05/08/10/24 (DynamicToolCreator 管道)
- [ ] `tests/test_sandbox.py` -- 覆盖 DYN-03/09 (DangerousModuleScanner + SandboxExecutor)
- [ ] `tests/test_tool_persistence.py` -- 覆盖 DYN-25/26 (三级持久化读写)
- [ ] `tests/test_api_tools.py` -- 覆盖 DYN-06/07/08 (API 确认端点 + 工具管理)
- [ ] `tests/conftest.py` -- 添加 fixture: `dynamic_creator`, `sandbox`, `persistence_manager`
- [ ] Framework install: `pip install pytest pytest-asyncio` -- verified installed (`pyproject.toml` dev deps)

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Phase 8 是本地工具创建，无认证需求 |
| V3 Session Management | no | Session 管理已有机制（Session 生命周期） |
| V4 Access Control | yes | 动态工具最低 PermissionLevel.MODERATE，永不 SAFE；命名空间 `dynamic.` 前缀隔离；用户确认门作为访问控制点 |
| V5 Input Validation | yes | `ast.parse()` 语法验证；`json.loads()` 验证 param_schema；Agent 提供参数经 ToolMetadata validation_model 校验 |
| V6 Cryptography | no | Phase 8 无加解密需求 |
| V7 Error Handling | yes | 结构化错误返回给 Agent（阶段 + 原因 + 建议）；错误不泄露系统内部信息 |

### Known Threat Patterns for Dynamic Tool Creation

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Python 内省绕过 AST 扫描 (`().__class__.__bases__[0].__subclasses__()`) | Elevation of Privilege | ast.NodeVisitor 检测 BYPASS_PATTERNS (`__subclasses__`, `__bases__`, `__globals__` 等)；用户确认作最终安全门；Phase 9 外部沙箱隔离 |
| 代码注入污染工具集 (`os.environ` 读取 API Key 外传) | Information Disclosure | 危险模块扫描封堵 `os`, `requests`, `socket` 等网络/I/O 模块；dynamic. 命名空间隔离；自测在子进程沙箱执行 |
| 资源耗尽 (`while True`, `"x" * 10**12`) | Denial of Service | resource.setrlimit 限制 CPU/内存；subprocess timeout 限制执行时间；AST 扫描 `while True` 和大字面量 |
| 工具名称冲突劫持 Agent 调用 | Spoofing | `dynamic.` 前缀 + hash 后缀强制唯一；ToolRegistry 分区存储；拒绝覆盖静态工具 |
| 间接提示注入通过工具描述 | Elevation of Privilege | 工具描述截断（max 500 字符）；扫描指令性语言（"你应该"、"忽略之前指令"）；固定模板包装 |
| 确认 API 未验证 session 归属 | Elevation of Privilege | API 端点验证 session_id in active_sessions；confirmation_id 验证存在且未过期 |

## Sources

### Primary (HIGH confidence)

- 现有代码库: `src/loopai/tools/registry.py` (register_meta 接口), `src/loopai/tools/types.py` (ToolMetadata 模型), `src/loopai/events/schemas.py` (Event 联合类型 + ConfirmationRequired 模式), `src/loopai/api/routes/control.py` (确认端点模式), `src/loopai/main.py` (create_agent_components 工厂), `src/loopai/api/schemas.py` (API 模型), `frontend/src/stores/uiStore.ts` (pendingConfirmation 模式), `frontend/src/lib/eventTypes.ts` (TypeScript 事件类型), `frontend/package.json` (依赖版本), `pyproject.toml` (测试配置) -- HIGH 置信度 (实际检查代码)
- `.planning/research/ARCHITECTURE.md` -- 管道架构设计、集成点映射、Data Flow 图 [HIGH: 基于现有代码精确对接]
- `.planning/research/STACK.md` -- 零新增 Python 依赖方案、Monaco Editor 选择、降级备选 [HIGH: 版本号经 npm/PyPI 验证]
- `.planning/research/PITFALLS.md` -- 8 个关键陷阱、CVE 案例、封堵策略 [HIGH: 基于 15+ 真实 CVE 披露]
- Context7: @monaco-editor/react npm registry -- version 4.7.0 (stable), 4.8.0-rc.3 (next) [VERIFIED: npm view]
- Python 3.13.13 stdlib -- ast, importlib.util, subprocess, resource, tempfile, shlex all importable [VERIFIED: local Python environment]

### Secondary (MEDIUM confidence)

- Python importlib 官方文档 -- spec_from_file_location 用法 [CITED: docs.python.org]
- shadcn/ui CLI v4 changelog -- Tailwind v4 支持 [CITED: ui.shadcn.com]
- @monaco-editor/react DeepWiki -- 项目文档聚合 [CITED: deepwiki.com]

### Tertiary (LOW confidence)

- 无。所有关键主张都通过代码审查或 npm/PyPI 验证。

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- 所有 Python stdlib 模块经实际 import 验证；`@monaco-editor/react` 版本经 npm view 确认；降级方案明确
- Architecture: HIGH -- 基于现有代码库精确集成点分析；pipe-and-filter 模式在已有 ConfirmationRequired 中有成熟实现
- Pitfalls: HIGH -- PITFALLS.md 基于 2025-2026 年 15+ 真实 CVE 披露和安全审计报告

**Research date:** 2026-05-31
**Valid until:** 2026-06-14 (稳定栈，30 天有效期)
