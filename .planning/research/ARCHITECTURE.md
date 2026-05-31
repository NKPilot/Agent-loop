# Architecture Research: Agent 动态工具创建系统

**Domain:** Agent 动态工具创建 -- 集成到现有 ReAct Agent 架构
**Researched:** 2026-05-31
**Confidence:** HIGH (基于现有代码库的精确对接点分析 + 生态系统中其他动态工具框架的模式参考)

## System Overview -- 现有架构 + 新增组件集成

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          Frontend (React + Zustand)                          │
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌───────────────┐  ┌──────────────────────┐  ┌─────────────────────────┐  │
│  │ ToolManager   │  │ ToolCreationDialog    │  │ ConfirmationDialog      │  │
│  │ Tab (新增)     │  │ (新增)                │  │ (已有, 复用)             │  │
│  └───────┬───────┘  └──────────┬───────────┘  └───────────┬─────────────┘  │
│          │                     │                          │                 │
│  ┌───────┴─────────────────────┴──────────────────────────┴─────────────┐  │
│  │                    Zustand Stores (扩展)                              │  │
│  │  uiStore: + pendingToolCreation, toolCreationTab                      │  │
│  │  eventStore: 处理 tool_creation_* 事件                                │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
├─────────────────────────────────────────────────────────────────────────────┤
│                           SSE Bridge (已有)                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                          FastAPI REST API                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌──────────────────────────────────┐  ┌──────────────────────────────────┐ │
│  │ Control Routes (扩展)             │  │ New: Tool Management Routes     │ │
│  │ POST confirm_tool_creation (新增) │  │ GET  /tools/dynamic             │ │
│  │ POST confirm_tool_update (新增)   │  │ PUT  /tools/dynamic/{name}      │ │
│  │ POST confirm (已有, 复用)          │  │ DELETE /tools/dynamic/{name}    │ │
│  └──────────────────────────────────┘  └──────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────────────────────┤
│                            EventBus (已有)                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │ 新增事件:                                                             │   │
│  │ tool_creation_requested, tool_creation_confirmed, tool_created,       │   │
│  │ tool_creation_failed, tool_update_requested, tool_update_confirmed    │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────────────────────────────┤
│                     ReActFSM (扩展 ACT 状态处理)                             │
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌───────────────┐  ┌───────────────────┐  ┌────────────────────────────┐  │
│  │ 已有: ToolReg  │  │ 新增: DynamicTool │  │ 已有: ToolExecutor          │  │
│  │   istry       │  │  Creator          │  │                             │  │
│  │               │  │ (generate_tool →  │  │ execute() → 动态工具        │  │
│  │ register_meta │  │  语法检查 →       │  │                             │  │
│  │ ()            │  │  EventBus →等待)  │  │                             │  │
│  └───────────────┘  └───────────────────┘  └────────────────────────────┘  │
├─────────────────────────────────────────────────────────────────────────────┤
│                       沙箱层 (新增)                                          │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  SandboxExecutor: subprocess + 子目录隔离 + 网络禁止 + 独立超时       │   │
│  │  DangerousModuleScanner: AST 扫描禁止的 import (os.system, subprocess │   │
│  │   , socket, ctypes, importlib, builtins.__import__)                   │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────────────────────────────┤
│                     持久化层 (新增)                                          │
│  ┌──────────────┐  ┌──────────────────┐  ┌─────────────────────────────┐  │
│  │ 会话级        │  │ 沙箱级            │  │ 项目级                       │  │
│  │ (内存 dict)   │  │ (.sandbox/       │  │ (src/loopai/tools/dynamic/  │  │
│  │ session结束   │  │  tools/*.py)     │  │  *.py, 持久化)              │  │
│  │ 即消失        │  │ session结束保留  │  │                              │  │
│  └──────────────┘  └──────────────────┘  └─────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Component Responsibilities

| Component | Responsibility | Implementation |
|-----------|---------------|----------------|
| **DynamicToolCreator** (新增) | Agent 调用的 generate_tool 内置工具；接收代码字符串 → 语法检查 → 发布事件 → 等待确认 → 注册到 ToolRegistry | `loopai/tools/dynamic_creator.py` |
| **SandboxExecutor** (新增) | 子目录隔离执行 Python/Bash 代码；禁止网络、文件系统限制、独立超时 | `loopai/tools/sandbox.py` |
| **DangerousModuleScanner** (新增) | AST 扫描 Python 代码中的危险 import/调用 | `loopai/tools/sandbox.py` 内嵌 |
| **ToolPersistenceManager** (新增) | 三级持久化（会话/沙箱/项目）的读写操作 | `loopai/tools/tool_persistence.py` |
| **ToolRegistry** (修改) | 已有 `register_meta()` -- 无需修改，动态工具通过相同接口注册 | 已存在 |
| **ToolExecutor** (修改) | 识别 `tool_type == "dynamic"` 时路由到 SandboxExecutor 而非直接执行 | 轻量修改 |
| **ReActFSM** (修改) | `_handle_act` 中为动态工具创建流程添加暂停/恢复逻辑 | 轻量修改 |
| **EventBus schemas** (修改) | 添加 6 个新事件类型 | `loopai/events/schemas.py` |
| **API routes** (修改) | 新增 `confirm_tool_creation`、`confirm_tool_update` 端点 + 工具管理 CRUD | `loopai/api/routes/control.py`, `loopai/api/routes/tools.py` |
| **create_agent_components** (修改) | 工厂函数注册 generate_tool 内置工具 | `loopai/main.py` |
| **uiStore** (修改) | 添加 `pendingToolCreation`, `toolCreationTab` 状态 | `frontend/src/stores/uiStore.ts` |
| **eventStore** (修改) | 处理 6 个新事件类型 | `frontend/src/stores/eventStore.ts` |
| **eventTypes** (修改) | 添加 6 个新事件类型的 TypeScript 定义 | `frontend/src/lib/eventTypes.ts` |
| **ToolCreationDialog** (新增) | 前端确认弹窗：代码展示 + 持久化级别 + 目录权限配置 | `frontend/src/components/ToolCreationDialog.tsx` |
| **ToolManager** (新增) | 前端工具管理 Tab：查看代码/禁用/启用/删除动态工具 | `frontend/src/components/ToolManager.tsx` |
| **api.ts** (修改) | 添加工具管理 API 调用函数 | `frontend/src/lib/api.ts` |

## Recommended Project Structure

```
src/loopai/
├── tools/
│   ├── dynamic_creator.py    # DynamicToolCreator (新增)
│   ├── sandbox.py             # SandboxExecutor + DangerousModuleScanner (新增)
│   ├── tool_persistence.py    # ToolPersistenceManager (新增)
│   ├── dynamic/               # 项目级持久化工具存放目录 (新增)
│   │   └── .gitkeep
│   ├── executor.py            # (修改: dynamic tool 路由)
│   ├── registry.py            # (无需修改: 已有 register_meta)
│   ├── types.py               # (修改: 添加 tool_type 字段到 ToolMetadata)
│   ├── decorator.py           # (无需修改)
│   └── ...
├── events/
│   └── schemas.py             # (修改: 添加 6 个新事件模型)
├── api/
│   ├── routes/
│   │   ├── control.py         # (修改: 添加 confirm_tool_creation/update 端点)
│   │   └── tools.py           # (新增: GET/PUT/DELETE /tools/dynamic)
│   └── schemas.py             # (修改: 添加工具管理 API 模型)
├── state_machine/
│   └── fsm.py                 # (修改: _handle_act 添加动态工具创建暂停/恢复)
├── main.py                    # (修改: create_agent_components 注册 generate_tool)
└── .sandbox/
    └── tools/                 # 沙箱级持久化工具目录
        └── .gitignore

frontend/src/
├── components/
│   ├── ToolCreationDialog.tsx # (新增: 工具创建确认弹窗)
│   ├── ToolManager.tsx        # (新增: 动态工具管理 Tab)
│   └── ToolDetail.tsx         # (修改: 区分静态/动态工具体验)
├── stores/
│   ├── uiStore.ts             # (修改: 添加 pendingToolCreation 等状态)
│   └── eventStore.ts          # (修改: 处理新事件类型)
├── lib/
│   ├── eventTypes.ts          # (修改: 添加新事件类型定义)
│   └── api.ts                 # (修改: 添加工具管理 API)
└── ...
```

### Structure Rationale

- **`tools/dynamic_creator.py`:** DynamicToolCreator 是 generate_tool 内置工具的具体实现，属于工具系统范畴。与 bash.py/disk_tools.py 同级。
- **`tools/sandbox.py`:** 沙箱执行器和危险模块扫描器紧密耦合——扫描后执行，放到同一文件。
- **`tools/tool_persistence.py`:** 三级持久化是独立关注点，有自己的文件系统操作和序列化逻辑。
- **`tools/dynamic/`:** 项目级持久化工具存放为实际的 `.py` 文件，可被 Python import。初始化时扫描此目录自动注册。
- **`.sandbox/tools/`:** 沙箱级持久化工具存放在 `.sandbox/` 下（已有 `.sandbox/overflow/` 目录），与项目保持一致。
- **`api/routes/tools.py`:** 工具管理 CRUD 是新 API 领域，独立路由文件保持 control.py 简洁。

## Architectural Patterns

### Pattern 1: 事件驱动的确认暂停 (复用已有 ConfirmationRequired 模式)

**What:** Agent 循环在工具创建的敏感点暂停，通过 EventBus 发布确认请求到前端，等待用户响应后继续执行。这与 v1.0 已有的危险命令确认 (PermissionGuard → ConfirmationRequired → ConfirmationResponse) 完全相同的模式。

**When to use:** DynamicToolCreator 的两阶段确认流程——代码语法检查完成后暂停等待用户审查、Agent 自测完成后暂停等待用户确认注册。

**Trade-offs:**
- 优点：复用已有 EventBus + asyncio.Event 暂停机制，后端无需新增状态机状态
- 缺点：用户必须在前端响应，CLI 模式下需要 CLI 消费者支持确认交互（已有范例）

**Example (后端——DynamicToolCreator 内部确认暂停):**
```python
# DynamicToolCreator._request_user_confirmation()
async def _request_user_confirmation(
    self, tool_name: str, code: str, persistence: str, working_dir: str
) -> bool:
    """发布确认事件并等待用户响应。"""
    import uuid
    confirmation_id = str(uuid.uuid4())[:8]
    wait_event = asyncio.Event()
    approved_value = False

    # 存储等待状态
    self._pending_confirmations[confirmation_id] = (wait_event, "approved")

    # 发布确认事件到 EventBus
    await self._bus.publish("tool_creation_requested", {
        "event_type": "tool_creation_requested",
        "session_id": self._session_id,
        "step_num": self._current_step,
        "confirmation_id": confirmation_id,
        "tool_name": tool_name,
        "code": code,
        "persistence": persistence,
        "working_dir": working_dir,
    })

    # 等待用户响应（带超时）
    try:
        await asyncio.wait_for(wait_event.wait(), timeout=120.0)
        approved_value = self._pending_confirmations[confirmation_id][1]
    except asyncio.TimeoutError:
        pass
    finally:
        self._pending_confirmations.pop(confirmation_id, None)

    return approved_value
```

### Pattern 2: Agent-as-Tool 桥接的变体 -- Built-in-Tool 模式

**What:** DynamicToolCreator 不是 AgentTool（不是启动子 Agent），而是一个内置工具（built-in tool），通过 `@tool` 装饰器注册到 ToolRegistry。LLM 调用它 → ToolExecutor 执行 → 返回结果。内部包含完整的确认暂停→注册流程。

**When to use:** 当一个操作需要 LLM 作为触发者但实际执行不需要独立 Agent 循环时——内置工具模式比 Agent-as-Tool 更轻量。

**与 AgentTool 模式的对比:**

| 维度 | AgentTool (已有) | DynamicToolCreator (新增) |
|------|------------------|---------------------------|
| 触发方式 | LLM 调用 tool | LLM 调用 generate_tool |
| 执行模式 | 启动独立 FSM 子循环 | 同步管道（语法检查→确认→沙箱测试→注册） |
| 需要独立 EventBus | 是 | 否（使用主 EventBus） |
| 需要独立 Session | 是 | 否 |
| 确认暂停 | 子 Agent 内部（如需要） | 主 EventBus + await asyncio.Event |

### Pattern 3: 管道式工具创建流程 (Pipeline Pattern)

**What:** DynamicToolCreator 内部实现一个多阶段管道，每个阶段有明确的 gate（通过/不通过），不通过则中止并返回结构化错误给 LLM。

**Pipeline stages:**
```
generate_tool(code, name, persistence, working_dir) → ToolResult
  1. 语法检查 (ast.parse / bash -n)        → 不通过: 返回错误 + 语法问题描述
  2. 危险模块扫描 (DangerousModuleScanner)   → 不通过: 返回错误 + 禁止的 import 列表
  3. 用户确认 (EventBus + asyncio.Event)     → 不通过: 返回 "用户拒绝"
  4. 沙箱自测 (SandboxExecutor)             → 不通过: 返回错误 + 自测失败详情
  5. 持久化 (ToolPersistenceManager)         → 总是成功
  6. 注册到 ToolRegistry                    → 总是成功
```

**When to use:** 任何需要多阶段验证的操作，特别是涉及安全和用户确认的流程。

### Pattern 4: 策略模式的沙箱隔离 (Sandbox Strategy)

**What:** SandboxExecutor 支持多种隔离策略（子进程 + 文件系统限制 vs. AST 重写 vs. Docker），通过策略接口切换。v1.1 使用子进程 + 文件系统限制（最简单可靠）。

**Why not Docker:** 遵循 CLAUDE.md 决策——"Learn first, containerize later." 子进程隔离足够满足 v1.1 学习需求。

**Example:**
```python
class SandboxExecutor:
    def __init__(self, strategy: SandboxStrategy = SubprocessSandboxStrategy()):
        self._strategy = strategy

    async def execute(self, code: str, working_dir: str, timeout: float) -> ToolResult:
        return await self._strategy.run(code, working_dir, timeout)

class SubprocessSandboxStrategy:
    async def run(self, code: str, working_dir: str, timeout: float) -> ToolResult:
        # subprocess.run 在隔离子目录中执行
        # 写入临时 .py 文件 → subprocess 执行 → 捕获输出
        ...
```

## Data Flow

### 完整的动态工具创建流程

```
Agent LLM 决定创建工具
        │
        ▼
LLM 调用 generate_tool(name="disk.check_inodes", code="...", persistence="sandbox")
        │
        ▼
┌─────────────────────────────────────────────────────────────────────┐
│ DynamicToolCreator.execute()                                        │
│                                                                     │
│  [阶段 1: 语法检查]                                                  │
│    ast.parse(code) 或 bash -n                                      │
│    └─ 失败 → 返回 ToolResult.error("语法错误: line 3...")           │
│    └─ 成功 → 继续                                                   │
│                                                                     │
│  [阶段 2: 危险模块扫描]                                              │
│    DangerousModuleScanner.scan(code)                                │
│    └─ 检测到危险模块 → 返回 ToolResult.error("禁止 import os.system") │
│    └─ 安全 → 继续                                                   │
│                                                                     │
│  [阶段 3: 用户确认 - EventBus 暂停]                                   │
│    await bus.publish("tool_creation_requested", {...})  ─────────┐  │
│    await asyncio.wait_for(event.wait(), timeout=120)             │  │
│    └─ 用户拒绝或超时 → 返回 ToolResult.error("用户拒绝")          │  │
│    └─ 用户确认 → 继续                                            │  │
│                                                                  │  │
│  [阶段 4: 沙箱自测]                                              │  │
│    SandboxExecutor.execute(code + test_code)                     │  │
│    └─ 自测失败 → 返回 ToolResult.error("自测失败: ...")          │  │
│    └─ 成功 → 继续                                                │  │
│                                                                  │  │
│  [阶段 5: 持久化]                                                │  │
│    ToolPersistenceManager.save(code, name, persistence_level)    │  │
│                                                                  │  │
│  [阶段 6: 注册]                                                  │  │
│    registry.register_meta(meta)  使用已有的 register_meta 接口   │  │
│                                                                  │  │
│  返回 ToolResult.success(data="工具 'disk.check_inodes' 已创建")  │  │
└─────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────────┐
│ 前端数据流 (阶段 3 确认 - 通过 SSE)                                   │
│                                                                     │
│ SSE event: tool_creation_requested ─────────────────────────────┐   │
│    │                                                             │   │
│    ▼                                                             │   │
│ eventStore.appendEvent() → 存储事件                               │   │
│    │                                                             │   │
│    ▼                                                             │   │
│ uiStore.setPendingToolCreation(event) → 触发 UI 状态              │   │
│    │                                                             │   │
│    ▼                                                             │   │
│ ToolCreationDialog 渲染:                                          │   │
│   - 代码语法高亮展示 (复用 ToolDetail 的 JsonHighlight 模式)      │   │
│   - 持久化级别选择 (会话/沙箱/项目)                                │   │
│   - 工作目录配置                                                  │   │
│   - 批准 / 拒绝 / 修改并批准 按钮                                 │   │
│    │                                                             │   │
│    ▼ (用户点击批准)                                               │   │
│ POST /api/sessions/{id}/confirm-tool-creation                     │   │
│   → control.confirm_tool_creation()                               │   │
│   → DynamicToolCreator.respond(confirmation_id, approved=True)    │   │
│   → asyncio.Event.set() → wait() 解除阻塞                         │   │
│   → 管道继续到阶段 4                                              │   │
└─────────────────────────────────────────────────────────────────────┘
```

### 工具更新流程 (Merge/Overwrite)

```
Agent LLM 调用 generate_tool(name="disk.check_inodes", code="新代码...")
        │
        ▼
DynamicToolCreator 检测到 tool_name 已存在于 registry
        │
        ▼
发布 tool_update_requested 事件 (包含 diff: 旧代码 vs 新代码)
        │
        ▼
前端 ToolCreationDialog 以 "更新模式" 渲染:
  - 并排 diff 展示 (old ↔ new)
  - 选项: 覆盖 / 拒绝 / 保存为新名称
        │
        ▼
覆盖: registry.unregister(old) → register_meta(new)
新名称: 自动追加后缀 (如 disk.check_inodes_v2)
拒绝: 返回 ToolResult.error("更新被拒绝")
```

### 工具发现流程

```
Session 启动时:
  create_agent_components()
    → 扫描 .sandbox/tools/*.py + src/loopai/tools/dynamic/*.py
    → ToolPersistenceManager.load_all()
    → registry.register_meta() 逐个注册

System prompt 注入:
  build_system_prompt() 在已有工具描述后追加:
    "## 可用的动态工具"
    "以下工具由 Agent 动态创建，可以在运行时调用:"
    "- disk.check_inodes: 检查 inode 使用情况 (沙箱级, 1 天前创建)"
    "- ..."

Agent 运行时发现:
  LLM 调用 list_dynamic_tools 内置工具 → 返回所有动态工具的详细信息
```

## Integration Points -- 精确对接点

### 1. DynamicToolCreator ↔ ToolRegistry

**对接方式:** `registry.register_meta(meta)` -- 使用已有的 `register_meta` 接口，无需修改 ToolRegistry。

**关键点:** DynamicToolCreator 构造 ToolMetadata 时需要设置:
- `name`: 用户指定的工具名
- `description`: LLM 提供的描述
- `permission_level`: 始终为 SAFE（沙箱内执行）
- `timeout`: 用户可配置，默认 30s
- `func_ref`: 包装函数——调用 SandboxExecutor.execute() 的 async 函数
- `param_schema`: LLM 提供的 JSON Schema
- `tags`: 自动添加 `["dynamic", f"persistence:{level}"]`

### 2. DynamicToolCreator ↔ EventBus

**对接方式:** 使用已有 `EventBus.publish(event_type, event_data)` 方法。

**新增事件类型:**

| 事件类型 | 触发时机 | 携带数据 |
|---------|---------|---------|
| `tool_creation_requested` | 语法检查通过后，等待用户确认 | confirmation_id, tool_name, code, persistence, working_dir |
| `tool_creation_confirmed` | 用户确认后 | confirmation_id, tool_name, approved, modified_code(可选) |
| `tool_created` | 工具成功注册后 | tool_name, persistence, timestamp |
| `tool_creation_failed` | 创建流程任何阶段失败 | tool_name, stage, error_message |
| `tool_update_requested` | 检测到名称冲突时 | confirmation_id, tool_name, old_code, new_code, diff |
| `tool_update_confirmed` | 用户确认更新后 | confirmation_id, tool_name, action(overwrite/rename/reject) |

### 3. DynamicToolCreator ↔ API Routes

**对接方式:** 复用已有 `control.py` 中确认端点的模式——通过 `app.state.active_sessions[session_id]["dynamic_creator"]` 获取实例。

**新增端点:**
```python
# 复用已有 active_sessions 字典存储 DynamicToolCreator 引用
POST /api/sessions/{session_id}/confirm-tool-creation
  body: { confirmation_id, approved, modified_code? }
  → 查找 dynamic_creator → 调用 respond(confirmation_id, approved, modified_code)

POST /api/sessions/{session_id}/confirm-tool-update
  body: { confirmation_id, action: "overwrite"|"rename"|"reject", new_name? }
  → 查找 dynamic_creator → 调用 respond_update(confirmation_id, action, new_name)

# 新增独立路由文件
GET    /api/tools/dynamic                    → 列出所有动态工具及状态
PUT    /api/tools/dynamic/{name}/toggle      → 启用/禁用工具
DELETE /api/tools/dynamic/{name}             → 删除工具（及其持久化文件）
```

### 4. DynamicToolCreator ↔ ReActFSM

**对接方式:** ReActFSM 不需要感知 DynamicToolCreator 的存在。generate_tool 是注册到 ToolRegistry 的普通工具——LLM 调用它时，`_handle_act` 中已有的工具管道 (LoopDetector → Registry lookup → PermissionGuard → ToolExecutor.execute) 完全适用。

**无需修改 `_handle_act` 的原因:**
- generate_tool 是 `@tool` 装饰的普通工具，tool_type 为 SAFE
- PermissionGuard 检查动态工具创建？不需要——这不是危险 Bash 命令，是代码生成
- ToolExecutor 正常执行 generate_tool，内部流程自行处理确认暂停

**唯一潜在修改点:** 如果工具创建确认超时需要 FSM 感知（当前 120s 超时在 DynamicToolCreator 内部处理）

### 5. DynamicToolCreator ↔ create_agent_components

**对接方式:** 在 `create_agent_components()` 中实例化 DynamicToolCreator 并注册 generate_tool。

```python
# 在 create_agent_components() 中添加:
dynamic_creator = DynamicToolCreator(
    registry=registry,
    bus=bus,
    sandbox=SandboxExecutor(),
    persistence=ToolPersistenceManager(),
)
registry.register(dynamic_creator.generate_tool)
registry.register(dynamic_creator.list_dynamic_tools)

return {
    ...existing keys...,
    "dynamic_creator": dynamic_creator,  # 供 API 确认端点使用
}
```

### 6. 前端 ↔ 后端 (SSE + REST)

**SSE 事件流:**
```
tool_creation_requested → ToolCreationDialog 弹出
tool_created → ToolManager Tab 刷新 + Timeline 显示成功
tool_creation_failed → Timeline 显示失败详情
```

**REST API 调用:**
```
confirmToolCreation(sessionId, confirmationId, approved, modifiedCode?)
fetchDynamicTools() → list of dynamic tools for ToolManager
toggleDynamicTool(name, enabled) → enable/disable
deleteDynamicTool(name) → delete
```

## Scalability Considerations

| Scale | Architecture Adjustments |
|-------|--------------------------|
| 1-10 动态工具/会话 | 会话级内存 dict -- 简单直接 |
| 10-100 动态工具/会话 | 沙箱级文件存储 + 启动时预加载 -- 当前设计已支持 |
| 100+ 动态工具总计 | 项目级持久化文件扫描可能变慢 → 添加文件系统缓存 (mtime-based) |
| 多用户并发 | 每个会话独立 SandboxExecutor 子目录 → 自然隔离 |

### Scaling Priorities

1. **First bottleneck:** 项目级 `dynamic/` 目录文件数量增长 → 启动扫描时间线性增长。解决: mtime 缓存 + 增量加载。
2. **Second bottleneck:** 单个工具代码过大 (>10KB) → 确认事件数据过大拖慢 SSE。解决: 事件中只传代码哈希 + 摘要，前端通过 REST 获取完整代码。

## Anti-Patterns

### Anti-Pattern 1: 动态工具直接调用 os.system/subprocess

**What people do:** LLM 生成的工具代码中包含 `os.system("rm -rf /")` 等危险操作。
**Why it's wrong:** 动态工具执行在没有沙箱隔离时等价于给 LLM shell 访问权限。
**Do this instead:** SandboxExecutor 在隔离子目录中执行 + DangerousModuleScanner 扫描 AST 阻止危险模块。

### Anti-Pattern 2: 跳过用户确认直接注册

**What people do:** Agent 生成代码 → 自动注册为工具 → 立即执行，无人工审查。
**Why it's wrong:** LLM 可能生成有 bug、安全漏洞或不符合预期的代码。用户确认是唯一的安全边界。
**Do this instead:** 必须经过用户确认（阶段 3）才能进入沙箱自测和注册（阶段 4-6）。不能跳过。

### Anti-Pattern 3: 动态工具与静态工具混用同一命名空间

**What people do:** LLM 创建名为 `bash.df` 的工具覆盖已有的静态工具。
**Why it's wrong:** 覆盖静态工具可能导致 Agent 行为不可预测。
**Do this instead:** 动态工具使用 `dynamic.` 命名空间前缀（如 `dynamic.disk_check_inodes`）；注册前检查冲突，已有同名静态工具时拒绝覆盖并提示 Agent 换名。

### Anti-Pattern 4: 持久化到项目级但无代码审查

**What people do:** 用户轻易批准项目级持久化，恶意或低质量代码进入项目源码树。
**Why it's wrong:** 项目级持久化的工具会在每次启动时自动加载——buggy 或恶意代码成为持久威胁。
**Do this instead:** 项目级持久化默认禁用；需要用户在配置中显式启用 `allow_project_persistence: true`；前端在项目级选项旁显示警告。

### Anti-Pattern 5: 用 AgentTool 模式实现 generate_tool

**What people do:** 把 generate_tool 实现为子 Agent（类似 `disk_analyzer` 的 Agent-as-Tool 模式）。
**Why it's wrong:** 工具创建是一系列确定性步骤（语法检查→确认→注册），不需要独立的 ReAct 循环。启动子 Agent 增加延迟和复杂度。
**Do this instead:** 使用内置工具模式（Built-in-Tool）——`@tool` 装饰的 async 函数，内部管道式执行。

## 与已有组件的修改清单

| 组件 | 修改级别 | 具体修改 |
|------|---------|---------|
| `events/schemas.py` | 轻量 | 添加 6 个新事件 Pydantic 模型 + 更新 Event 联合类型 |
| `tools/types.py` | 轻量 | ToolMetadata 添加 `tool_type: Literal["static", "dynamic"]` 字段 |
| `tools/registry.py` | 无需修改 | `register_meta()` 已支持动态注册 |
| `tools/executor.py` | 轻量 | `_execute_once` 中检测 `tool_type == "dynamic"` → 路由到 SandboxExecutor |
| `state_machine/fsm.py` | 无需修改 | generate_tool 通过已有工具管道执行 |
| `api/routes/control.py` | 轻量 | 添加 2 个确认端点 |
| `api/routes/tools.py` | 新增 | 工具管理 CRUD |
| `api/schemas.py` | 轻量 | 添加 ConfirmToolCreationRequest, ToolSummary 等模型 |
| `main.py` | 轻量 | create_agent_components 注册 generate_tool |
| 前端 `eventTypes.ts` | 轻量 | 添加 6 个新事件接口 + 更新 Event 联合类型 |
| 前端 `uiStore.ts` | 中等 | 添加 pendingToolCreation, toolCreationTab, dynamicTools |
| 前端 `eventStore.ts` | 轻量 | 扩展 updateToolCalls 处理新事件类型 |
| 前端 `api.ts` | 轻量 | 添加 confirmToolCreation, fetchDynamicTools 等 API 函数 |

## Sources

- 现有代码库: `src/loopai/events/schemas.py` (13 个事件模型 + Event 联合类型), `src/loopai/tools/registry.py` (register_meta 接口), `src/loopai/tools/executor.py` (4 层恢复管道), `src/loopai/state_machine/fsm.py` (_handle_act 工具管道), `src/loopai/agents/tool.py` (AgentTool 桥接模式), `src/loopai/api/routes/control.py` (确认端点模式), `src/loopai/main.py` (create_agent_components 工厂) -- HIGH confidence
- isA Agent SDK Dynamic Tool Creation Proposal: https://github.com/xenoISA/isA_Agent_SDK/issues/378 -- MEDIUM confidence (sandbox 模块白名单设计参考)
- Anvil SDK JIT Code Generation: https://pypi.org/project/anvil-agent/ -- MEDIUM confidence (JIT 工具生成管道设计参考)
- Tool Forge: https://github.com/nextmoca/tool-forge -- MEDIUM confidence (沙箱验证管道参考)
- Microsoft Agent Framework Hyperlight/CodeAct: https://github.com/microsoft/agent-framework/discussions/5328 -- MEDIUM confidence (沙箱执行模式参考)

---
*Architecture research for: Agent 动态工具创建系统*
*Researched: 2026-05-31*
