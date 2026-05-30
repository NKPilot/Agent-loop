# Phase 6: Agent-as-Tool — 多 Agent 协作 - Research

**研究日期:** 2026-05-30
**领域:** 多 Agent 协作框架、Agent 封装为 Tool、子 Agent Session 隔离
**总体置信度:** HIGH

## 摘要

本阶段实现 Agent-as-Tool 多 Agent 协作框架：将 Agent 封装为可被主 Agent 调用的 Tool，子 Agent 拥有独立的 Session 和工具集，完成后结构化回传结果。核心挑战在于复用既有的 `@tool` 装饰器和 `ToolRegistry` 模式来构建 `@agent` 装饰器和 `AgentRegistry`，同时确保子 Agent 的 FSM 执行上下文完全隔离。

**关键洞见：** `AgentTool` 是架构的枢纽——它在外部表现为一个普通 Tool（可注册进主 Agent 的 `ToolRegistry`），内部则负责创建子 Agent 的完整组件（Session、ToolRegistry、FSM 等）。由于现有的 `ToolExecutor.execute()` 已经支持通过 `ToolMetadata.func_ref` 调用任意函数，`AgentTool.execute()` 只需返回 `ToolResult` 即可无缝接入现有工具执行管道。

**主要建议:** 创建 `src/loopai/agents/` 新模块，复用 `decorator.py` 和 `registry.py` 的全部模式。子 Agent 使用同一个 EventBus 但不同的 session_id，通过新的 `agent_call_start`/`agent_call_end` 事件桥接父子 Agent 的可观测性。

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** @agent 装饰器——类似 @tool，定义子 Agent 的 system prompt、工具集、预算。调用时内部启动独立 ReActFSM session，完成后返回结构化结果。对外表现为普通 Tool。
- **D-02:** 子 Agent 通过 AgentRegistry 注册，与 ToolRegistry 独立管理。AgentTool 桥接两者——它既是 Tool（可被 ToolRegistry 注册），内部又调用 Agent。
- **D-03:** 独立工具集——每个子 Agent 有自己独立的 ToolRegistry。
- **D-04:** 子 Agent 的 Bash 工作目录继承自主 Agent 配置。
- **D-05:** 结构化摘要——子 Agent 完成后返回 `{summary, tool_calls, token_usage, steps, session_id}`。

### Claude's Discretion
- @agent 装饰器的具体参数设计
- AgentTool 内部的 FSM 创建和 Session 生命周期管理
- 子 Agent 结果摘要的生成方式（最终回复 vs LLM 再摘要）
- 前端多 Agent 调用链的 UI 布局

### Deferred Ideas (OUT OF SCOPE)
- 子 Agent 并行执行（多个子 Agent 同时跑）— v2.1
- Agent-to-Agent 直接通信（不经过主 Agent）— v2.2
- 子 Agent 结果缓存（相同输入不重复跑）— v2.1
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| AGT-01 | AgentTool——将任意 Agent 封装为 @tool | @tool 装饰器模式完整可用，AgentTool 复用 ToolMetadata + func_ref |
| AGT-02 | 子 Agent Session 隔离——独立 Session，不污染主 Agent | Session 是独立 dataclass，每个子调用 new Session() |
| AGT-03 | 结果回传——结构化返回含摘要、工具调用、token 消耗 | ToolResult 已支持结构化返回，AgentTool 在 FSM 完成后构建摘要 dict |
| AGT-04 | 超时和预算控制——子 Agent 独立 step budget 和超时 | BudgetGuard 参数化 max_steps，asyncio.wait_for 包裹 FSM.run() |
| AGT-05 | 子 Agent 工具集——可配置每个 Agent 的工具范围 | ToolRegistry 实例独立，AgentTool 从父 registry 按 name 筛选 |
| BIZ-03 | 磁盘诊断多 Agent 演示——委托分析 Agent + 清理 Agent | disk_analyzer（只读：df/du/find）+ disk_cleaner（rm 需确认） |
| WEB-01 | 多 Agent 调用链可视化——Dashboard 展示嵌套调用关系 | 新 event types: agent_call_start/agent_call_end，前端新建 AgentCallCard |
| WEB-02 | 子 Agent 会话可展开——点击查看完整时间线 | 前端打开子 session SSE 流或 REST 获取子事件列表 |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| @agent 装饰器 | Backend (Python) | — | 类似 @tool，纯后端装饰器模式 |
| AgentRegistry | Backend (Python) | — | 类似 ToolRegistry，独立管理 Agent 元数据 |
| AgentTool 桥接 | Backend (Python) | — | 既是 Tool 又是 Agent 创建工厂 |
| 子 Agent FSM 执行 | Backend (Python) | — | 内部创建独立 ReActFSM 实例并运行 |
| 子 Agent Session 隔离 | Backend (Python) | — | 每次调用 new Session() |
| 子 Agent 工具隔离 | Backend (Python) | — | 每个 Agent 独立 ToolRegistry |
| 调用链事件发布 | Backend (Python) | EventBus | agent_call_start/agent_call_end 事件 |
| 多 Agent 调用链展示 | Browser (React) | — | 新 AgentCallCard 组件，嵌套在 StepCard 中 |
| 子会话展开查看 | Browser (React) | API (REST/SSE) | 展开后通过 REST 获取子会话事件 |

## Standard Stack

### Core (复用既有的模块)
| 库/模块 | 用途 | 为何标准 |
|---------|------|---------|
| `loopai.tools.decorator.tool` | @agent 装饰器参考模板 | 装饰器 + 类型校验 + JSON Schema 的完整模式 [VERIFIED: 代码分析] |
| `loopai.tools.registry.ToolRegistry` | AgentRegistry 参考模板 | 实例隔离 + namespace 查找的完整模式 [VERIFIED: 代码分析] |
| `loopai.state_machine.fsm.ReActFSM` | 子 Agent 执行引擎 | 从父 Agent 逻辑中已解耦，可复用，不需要改动 [VERIFIED: 代码分析] |
| `loopai.session.context.Session` | 子 Agent Session 容器 | 独立 dataclass，每次 new Session() 即可 [VERIFIED: 代码分析] |
| `loopai.events.bus.EventBus` | 父子 Agent 事件发布 | 共享同一个 Bus，通过 session_id 区分 [VERIFIED: 代码分析] |
| `loopai.llm.client.LLMClient` | 子 Agent LLM 调用 | 无状态客户端，可与父 Agent 共享 [VERIFIED: 代码分析] |
| `loopai.tools.executor.ToolExecutor` | 子 Agent 工具执行 | 与 ToolRegistry 解耦，每次新建即可 [VERIFIED: 代码分析] |
| `loopai.state_machine.guards.BudgetGuard` | 子 Agent 预算控制 | 参数化 max_steps，每个子 Agent 独立实例 [VERIFIED: 代码分析] |

### 新增模块
| 模块 | 用途 | 依赖关系 |
|------|------|---------|
| `loopai.agents.types` | AgentMetadata 类型定义 | 依赖 ToolMetadata 模式 |
| `loopai.agents.decorator` | @agent 装饰器 | 依赖 types, tools.decorator |
| `loopai.agents.registry` | AgentRegistry | 依赖 types |
| `loopai.agents.tool` | AgentTool 桥接 | 依赖 registry, fsm, session, 各种 guards |

### Alternatives Considered
| 不采用 | 替代方案 | 取舍 |
|--------|---------|------|
| 子 Agent 复用父 Agent 的全部 guards | 子 Agent 创建精简版 guards | 父 Agent 有全量的 guards（checkpoint, circuit_breaker 等），子 Agent MVP 不需要 |
| 子 Agent 共享父 Agent 的 ToolRegistry | 子 Agent 独立 ToolRegistry | D-03 锁定了独立工具集，且可避免工具名冲突 |
| 子 Agent 使用独立 EventBus | 共享同一个 EventBus | 共享 Bus + session_id 过滤即可实现隔离，且 SSE 桥接不需要修改 |

### 安装
无新依赖需要安装。所有依赖复用现有项目：
```bash
pip install pydantic  # 已安装，用于 AgentMetadata
```

## Architecture Patterns

### 系统架构图

```
┌─────────────────────────────────────────────────────────────────────┐
│                       主 Agent 执行流程                               │
│                                                                      │
│  User Prompt                                                        │
│       │                                                             │
│       ▼                                                             │
│  ┌────────────────────────────────────┐                              │
│  │      ReActFSM (主 Agent)           │                              │
│  │  REASON → ACT → OBSERVE → ...     │                              │
│  │                                    │                              │
│  │  ToolRegistry:                     │                              │
│  │  ├─ bash (普通工具)                │                              │
│  │  ├─ disk_df (普通工具)             │                              │
│  │  ├─ disk_du (普通工具)             │                              │
│  │  ├─ AgentTool(disk_analyzer)  ◄────┼── ToolExecutor.execute()    │
│  │  └─ AgentTool(disk_cleaner)        │                              │
│  └────────────────────────────────────┘                              │
│           │                                                          │
│           │ AgentTool.execute() 被调用                                │
│           ▼                                                          │
│  ┌────────────────────────────────────┐                              │
│  │      AgentTool.execute()           │                              │
│  │  1. 发布 agent_call_start 事件    │                              │
│  │  2. 创建子 Agent 完整组件          │                              │
│  │     ├─ Session (新 session_id)     │                              │
│  │     ├─ ToolRegistry (子集)         │                              │
│  │     ├─ BudgetGuard (子预算)         │                              │
│  │     ├─ Guard (精简版)              │                              │
│  │     └─ ReActFSM (新实例)           │                              │
│  │  3. 运行 子 ReActFSM.run()        │                              │
│  │  4. 收集结果 → 结构化摘要          │                              │
│  │  5. 发布 agent_call_end 事件       │                              │
│  │  6. 返回 ToolResult(summary)       │                              │
│  └────────────────────────────────────┘                              │
│           │                                                          │
│           │ ToolResult 返回主 FSM                                    │
│           ▼                                                          │
│  主 Agent OBSERVE → 看到摘要 → 继续 REASON                           │
│                                                                      │
│  EventBus (全局共享)                                                 │
│  ├─ 主 session_id 事件: step_start, llm_token, ...                  │
│  │   agent_call_start, agent_call_end, tool_result                  │
│  └─ 子 session_id 事件: step_start, llm_token, ..., session_end     │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     Web 前端展示                                      │
│                                                                      │
│  AgentTimeline (主 Agent)                                            │
│  ├─ Step 1: REASON — "分析磁盘..."                                  │
│  ├─ Step 2: ACT — 调用 tool=disk_analyzer(param=".sandbox")         │
│  │   └─ AgentCallCard (可展开)                                       │
│  │       ├─ 子 Agent "disk_analyzer" 时间线                          │
│  │       │  ├─ Step 1: REASON — "诊断..."                           │
│  │       │  ├─ Step 2: ACT — disk_df → ...                          │
│  │       │  └─ ...                                                  │
│  │       └─ 摘要: {steps:3, tools:[disk_df, disk_du], ...}         │
│  └─ Step 3: REASON — "分析完成，开始清理..."                         │
└─────────────────────────────────────────────────────────────────────┘
```

### 文件结构
```
src/loopai/agents/           # 新模块
├── __init__.py
├── types.py                 # AgentMetadata, AgentToolResult
├── decorator.py             # @agent 装饰器
├── registry.py              # AgentRegistry
└── tool.py                  # AgentTool 桥接实现

前端新增:
frontend/src/components/
├── AgentCallCard.tsx         # 子 Agent 调用卡片（可展开）
└── AgentCallTimeline.tsx     # 子 Agent 内部时间线（展开后显示）
```

### 模式 1: @agent 装饰器模式

**用途:** 定义子 Agent 的元数据，类似 @tool 定义工具元数据。

```python
# Source: 复用 loopai.tools.decorator.tool 模式
# 文件: src/loopai/agents/decorator.py

_AGENT_META_ATTR = "__agent_meta__"

def agent(
    name: str | None = None,
    description: str | None = None,
    system_prompt: str | None = None,
    tool_names: list[str] | None = None,
    max_steps: int = 5,
    timeout: float = 120.0,
):
    """装饰器工厂——将函数注册为 Agent 定义 (D-01)。

    函数签名决定 AgentTool 的参数 schema（同 @tool）。
    docstring 第一行为 description（未指定时）。
    函数体即子 Agent 的初始 user 消息模板。
    """
    def decorator(func: Callable) -> Callable:
        agent_name = name or func.__name__
        agent_desc = description or inspect.cleandoc(func.__doc__ or "").split("\n")[0]
        if tool_names is None:
            tool_names = []

        # 复用 @tool 的参数 schema 构建逻辑
        validation_model = _build_validation_model(func)
        param_schema = _build_param_schema(func)

        meta = AgentMetadata(
            name=agent_name,
            description=agent_desc,
            system_prompt=system_prompt or "",
            tool_names=list(tool_names),
            max_steps=max_steps,
            timeout=timeout,
            param_schema=param_schema,
            func_ref=func,
            validation_model=validation_model,
        )
        setattr(func, _AGENT_META_ATTR, meta)
        return func
    return decorator
```

**使用时:**
```python
from loopai.agents.decorator import agent

@agent(
    name="disk_analyzer",
    description="诊断磁盘使用情况，找出大文件和目录",
    system_prompt="你是磁盘分析专家，专注于诊断磁盘使用情况。",
    tool_names=["disk_df", "disk_du", "disk_find"],
    max_steps=5,
)
async def disk_analyzer(directory: str) -> str:
    """诊断指定目录的磁盘使用情况。"""
    return f"请分析目录 {directory} 的磁盘使用情况，找出占用空间最大的文件和目录。"
```

### 模式 2: AgentTool 执行模式

**用途:** AgentTool 在外部是 Tool（可被 ToolRegistry 注册、ToolExecutor 调用），内部创建并运行子 Agent。

```python
# Source: 设计模式从 D-02 推演
# 文件: src/loopai/agents/tool.py

class AgentTool:
    """桥接 Agent 和 Tool — 外部表现为 Tool，内部运行子 Agent (D-02)。

    生命周期:
    1. 创建: 由 AgentRegistry 和 ToolRegistry 对接时实例化
    2. 注册: 注册进主 Agent 的 ToolRegistry（被主 LLM 看到）
    3. 执行: ToolExecutor 调用 execute() → 内部创建子 Agent 组件
    """

    def __init__(self, agent_meta: AgentMetadata,
                 parent_registry: ToolRegistry,
                 llm_client: LLMClient,
                 parent_bus: EventBus,
                 config: AgentConfig):
        self._meta = agent_meta
        self._parent_registry = parent_registry
        self._llm_client = llm_client
        self._bus = parent_bus
        self._config = config

    @property
    def __tool_meta__(self) -> ToolMetadata:
        """对外表现为 Tool — LLM 看到的是普通工具 schema。"""
        return ToolMetadata(
            name=self._meta.name,
            description=self._meta.description,
            permission_level=PermissionLevel.SAFE,  # Agent 调用本身是安全的
            timeout=self._meta.timeout,
            param_schema=self._meta.param_schema,
            func_ref=self.execute,  # 关键: func_ref 指向 execute
        )

    async def execute(self, **kwargs) -> str:
        """执行子 Agent (对外作为 tool 的 func_ref)。

        流程:
        1. 从 func_ref 获取 task 模板，用 kwargs 格式化
        2. 发布 agent_call_start 事件
        3. 创建子 Agent 组件 (Session, ToolRegistry, FSM)
        4. 运行 FSM
        5. 构建结构化摘要
        6. 发布 agent_call_end 事件
        7. 返回摘要 JSON 字符串
        """
        # Step 1: 构建 task prompt
        task = self._meta.func_ref(**kwargs)

        # Step 2: 发布 agent_call_start
        child_session_id = str(uuid.uuid4())
        await self._bus.publish("agent_call_start", {
            "event_type": "agent_call_start",
            "session_id": self._current_session_id,  # 父 session_id
            "agent_name": self._meta.name,
            "child_session_id": child_session_id,
        })

        # Step 3: 创建子 Agent 组件 (细节见下文)
        result_summary = await self._run_sub_agent(task, child_session_id)

        # Step 6: 发布 agent_call_end
        await self._bus.publish("agent_call_end", {
            "event_type": "agent_call_end",
            "session_id": self._current_session_id,
            "agent_name": self._meta.name,
            "child_session_id": child_session_id,
            "summary": result_summary,
        })

        # Step 7: 返回 JSON
        return json.dumps(result_summary, ensure_ascii=False)
```

### 模式 3: 子 Agent 组件工厂

**用途:** AgentTool 内部创建子 Agent 的完整组件栈（Session、ToolRegistry、FSM 等）。

```python
# Source: 复用 create_agent_components() 模式 (main.py)

async def _run_sub_agent(self, task: str, child_session_id: str) -> dict:
    """创建并运行子 Agent，返回结构化摘要。"""

    # 1. 子 Agent Session（完全独立）
    child_session = Session(config=self._config)
    child_session.session_id = child_session_id  # 使用工具生成的 ID
    child_session.add_message("system", self._meta.system_prompt)
    child_session.add_message("user", task)

    # 2. 子 Agent ToolRegistry（只包含指定工具）
    child_registry = ToolRegistry()
    for tool_name in self._meta.tool_names:
        meta = self._parent_registry.get(tool_name)
        if meta and meta.func_ref:
            child_registry.register(meta.func_ref)

    # 3. 子 Agent 执行基础设施
    executor = ToolExecutor(child_registry)
    permission_guard = PermissionGuard(
        self._bus,
        confirmation_timeout=self._config.confirmation_timeout,
    )

    # 4. 子 Agent Guards（精简版）
    child_fsm = ReActFSM(
        client=self._llm_client,
        bus=self._bus,
        budget_guard=BudgetGuard(max_steps=self._meta.max_steps),
        loop_detector=LoopDetector(),
        message_validator=MessageValidator(),
        registry=child_registry,
        executor=executor,
        permission_guard=permission_guard,
        # 可选: token_guard, compressor
        # 跳过: checkpoint_manager, circuit_breaker, failure_registry
    )

    # 5. 执行（带超时保护）
    try:
        child_session = await asyncio.wait_for(
            child_fsm.run(child_session),
            timeout=self._meta.timeout,
        )
    except asyncio.TimeoutError:
        child_session.state = AgentState.ERROR

    # 6. 构建摘要 (D-05)
    summary_text = self._extract_summary(child_session)
    tool_calls = self._extract_tool_calls(child_session)

    return {
        "summary": summary_text,
        "tool_calls": tool_calls,
        "token_usage": None,  # 可以跟踪子 Agent 的 token
        "steps": child_session.step_count,
        "session_id": child_session.session_id,
        "final_state": child_session.state.value,
    }
```

### 模式 4: 前端嵌套调用链展示

**用途:** AgentTimeline 在 StepCard 中检测到 `agent_call_start` 事件时，渲染 `AgentCallCard` 替代普通工具调用卡片。

```tsx
// AgentCallCard.tsx — 在 StepCard 内部渲染
function AgentCallCard({ event, childEvents, onExpand }: Props) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="border-l-2 border-l-purple-400 ml-4 pl-3">
      <button onClick={() => setExpanded(!expanded)} className="...">
        <span>Agent: {event.agent_name}</span>
        <span>{event.child_session_id}</span>
        <ChevronDown />
      </button>

      {expanded && childEvents.length > 0 && (
        <div className="ml-3 border-l-2 border-l-purple-200 pl-3">
          {/* 嵌套的子 Agent 时间线 */}
          <AgentCallTimeline events={childEvents} />
        </div>
      )}
    </div>
  );
}
```

### 反模式警告
- **子 Agent 共享同个 Session 对象:** 每次调用必须 new Session()，不能复用。D-02 明确要求"独立 Session"。
- **子 Agent 使用父 Agent 的 ToolRegistry:** D-03 要求独立工具集。直接从父 registry 按名 fetch 然后注册到子 registry。
- **子 Agent FSM 跑在主事件循环中阻塞:** AgentTool.execute() 必须是 async 函数，子 FSM.run() 用 `asyncio.create_task` 或直接 await（取决于是否需要并行）。

## Don't Hand-Roll

| 问题 | 不要造 | 使用 | 原因 |
|------|--------|------|------|
| 参数校验和 JSON Schema 生成 | 手动 inspect 参数+写 schema | 复用 `_build_param_schema()` 和 `_build_validation_model()` | @tool 已有完整的类型→schema 映射，包括 Optional、Union、Literal、Enum [VERIFIED: decorator.py] |
| 工具查找和管理 | 自定义 Agent 工具字典 | 复用 `ToolRegistry` | 已经有 namespace 查找、schema 导出、get/list 方法 [VERIFIED: registry.py] |
| 子 Agent 执行引擎 | 自写 while 循环 | 复用 `ReActFSM` | 已有完整的 REASON→ACT→OBSERVE 循环 + guard 集成 [VERIFIED: fsm.py] |
| 事件发布 | 自写 pub/sub | 复用 `EventBus` | 已有 topic 订阅、历史回放、SSE 桥接 [VERIFIED: events/bus.py] |
| 子 Agent 工具执行 | 自写 execute 逻辑 | 复用 `ToolExecutor` | 已有参数校验、超时、重试、overflow 文件写入 [VERIFIED: tools/executor.py] |

**关键洞见:** 本阶段"新增"代码主要是"编排"代码——将既有组件以新的方式组合起来，而不是重新实现既有功能。@agent 装饰器本质上是 @tool 装饰器的变体，AgentRegistry 是 ToolRegistry 的变体，AgentTool 是编排器。核心的 FSM、ToolExecutor、EventBus 等组件完全不需要修改。

## 常见陷阱

### 陷阱 1: 子 Agent 事件污染父 Agent SSE 流
**问题:** 子 Agent 的事件（step_start, llm_token 等）使用子 Agent 的 session_id 发布，但父 Agent 的 SSE 流按 `session_id` 过滤，不会收到子事件。父 SSE 流只能看到 `agent_call_start`/`agent_call_end` 两个桥接事件。
**根因:** SSE bridge (`sse_bridge.py`) 使用 `event.get("session_id") == session_id` 过滤，父子 session_id 不同。
**避免方法:** 这是正确的行为——父 SSE 流不应接收子 Agent 的内部事件。前端可通过以下方式获取子事件：
- REST API: `GET /api/sessions/{child_session_id}` 获取全部事件
- 子 SSE 流: 打开第二个 `EventSource` 连接到 `/api/sessions/{child_session_id}/stream`
**警告信号:** 子 Agent 事件出现在父 SSE 流中 → 说明 session_id 传递有误。

### 陷阱 2: @agent 装饰器中 func_ref 的用途两个
**问题:** `@agent` 装饰的函数既用于参数 schema（同 @tool），又作为子 Agent 的任务模板（函数体返回值）。这与 @tool 不同——@tool 的 func_ref 是实际执行函数。
**根因:** 设计决定 D-01 要求 @agent 对外表现为 Tool，但函数体不直接执行，而是用作子 Agent 的 user message。
**避免方法:** AgentTool.execute() 中调用 `self._meta.func_ref(**kwargs)` 获取 task 字符串（不是执行工具），然后将该字符串作为子 Agent 的 user message。
**警告信号:** 子 Agent 收到空 task 或参数未被模板化 → func_ref 调用结果未作为 user message。

### 陷阱 3: PermissionGuard 跨 Session 混淆
**问题:** 子 Agent 的 PermissionGuard 创建独立实例，但发布到同一个 EventBus。父 Agent 的 ConfirmationDialog 可能收到子 Agent 的 `confirmation_required` 事件。
**根因:** `confirmation_required` 事件包含 `session_id` 字段，ConfirmationDialog 当前可能不按 session_id 过滤。
**避免方法:** 前端 ConfirmationDialog 增加 session_id 过滤，只处理当前活跃 session 的确认请求。子 Agent 的确认事件 session_id=子 session_id，会被正确忽略。
**警告信号:** 父 Agent 的确认弹窗显示了子 Agent 的危险命令。

### 陷阱 4: 子 Agent JSONL 日志未写入
**问题:** 子 Agent 创建了独立的 JSONLLogger 实例，但未调用 `logger.start(bus)` 和 `logger.stop()`，导致子 Agent 的完整执行记录不写入磁盘。
**根因:** 子 Agent 的组件创建在 AgentTool.execute() 中，容易被简化忽略日志。
**避免方法:** 在创建子 Agent 组件时必须包含 JSONLLogger 的 start/stop 生命周期。如果不需要持久化子会话日志，至少在 `agent_call_end` 中打包子 Agent 的关键事件。
**警告信号:** 查看 logs/sessions/ 目录，子 session_id 的日志文件不存在。

## 代码示例

### @agent 装饰器用法（磁盘诊断演示）

```python
# 文件: src/loopai/agents/disk_agents.py

from loopai.agents.decorator import agent

@agent(
    name="disk_analyzer",
    description="诊断磁盘使用情况：分析指定目录，找出大文件和目录",
    system_prompt=(
        "你是磁盘分析专家。你的任务是分析指定目录的磁盘使用情况。\n"
        "1. 使用 disk_df 获取磁盘整体使用概览\n"
        "2. 使用 disk_du 分析各子目录大小\n"
        "3. 使用 disk_find 找出大于 10MB 的大文件\n"
        "4. 总结：总大小、最大文件、建议清理项\n\n"
        "完成后返回包含关键指标的结构化报告。"
    ),
    tool_names=["disk_df", "disk_du", "disk_find"],
    max_steps=5,
)
async def disk_analyzer(directory: str = ".sandbox") -> str:
    """诊断 {directory} 目录的磁盘使用情况。"""
    return f"请分析目录 {directory} 的磁盘使用情况。"
```

```python
@agent(
    name="disk_cleaner",
    description="清理磁盘：删除指定的大文件或目录",
    system_prompt=(
        "你是磁盘清理专家。你的任务是根据分析结果清理大文件。\n"
        "1. 用户会告诉你需要删除哪些文件\n"
        "2. 使用 disk_rm 执行删除（需要用户确认）\n"
        "3. 报告删除结果\n\n"
        "不要随意删除文件——只删除用户明确指定的文件。"
    ),
    tool_names=["disk_rm"],
    max_steps=3,
)
async def disk_cleaner(target: str) -> str:
    """清理大文件: {target}。"""
    return f"请清理以下文件/目录: {target}"
```

### AgentTool 在主 Agent 中的注册

```python
# 文件: src/loopai/main.py (修改 create_agent_components)

def create_agent_components(config, prompt, bus, ...):
    # ... 既有代码: 创建 registry, 注册 bash_tool, disk_tools ...

    # === Phase 6: 注册 AgentTools ===
    from loopai.agents.registry import AgentRegistry
    from loopai.agents.tool import AgentTool
    from loopai.agents.disk_agents import disk_analyzer, disk_cleaner

    agent_registry = AgentRegistry()
    agent_registry.register(disk_analyzer)
    agent_registry.register(disk_cleaner)

    # 为每个 Agent 定义创建 AgentTool，注册到主 ToolRegistry
    for agent_meta in agent_registry.list_all():
        agent_tool = AgentTool(
            agent_meta=agent_meta,
            parent_registry=registry,
            llm_client=client,
            parent_bus=bus,
            config=config,
        )
        # AgentTool 通过 __tool_meta__ 伪装为 Tool
        registry.register_tool_meta(agent_tool.__tool_meta__)
    # ===========================

    # ... 既有代码: 继续创建 FSM ...
```

### 前端 EventStore 新增事件处理

```typescript
// 更新 frontend/src/lib/eventTypes.ts

export interface AgentCallStartEvent extends EventBase {
  event_type: "agent_call_start";
  step_num: number;
  agent_name: string;
  child_session_id: string;
}

export interface AgentCallEndEvent extends EventBase {
  event_type: "agent_call_end";
  step_num: number;
  agent_name: string;
  child_session_id: string;
  summary: {
    summary: string;
    tool_calls: number;
    steps: number;
    session_id: string;
    final_state: string;
  };
}

// 更新 Event 联合类型
export type Event = ... | AgentCallStartEvent | AgentCallEndEvent;

export const EVENT_TYPE_MAP: Record<string, string> = {
  ...,
  agent_call_start: "Agent Call Start",
  agent_call_end: "Agent Call End",
};
```

## 最新技术

| 旧方案 | 当前方案 | 变化 | 影响 |
|--------|---------|------|------|
| 单 Agent 循环 | Agent-as-Tool 多 Agent 协作 | Phase 6 | 子 Agent 完全隔离，通过结构化摘要回传结果 |
| @tool 只注册函数 | @agent 注册 Agent 定义 | Phase 6 | 函数体用作 task 模板而非直接执行 |
| ToolRegistry 管理全部工具 | AgentRegistry + ToolRegistry 分层 | Phase 6 | Agent 定义和工具定义解耦 |

## 假设日志

| # | 假设 | 所属章节 | 错误风险 |
|---|------|---------|---------|
| A1 | AgentTool 不需要子 Agent 的全套 Resilience 组件（CircuitBreaker、FailureRegistry、CheckpointManager） | 子 Agent 组件工厂 | 如果子 Agent 长时间运行且失败频繁，缺少 Resilience 可能导致雪崩 |
| A2 | 子 Agent 共享父 Agent 的 LLMClient 是安全的（无状态） | 子 Agent 组件工厂 | LLMClient 当前无状态，但将来如果添加 rate-limiting 状态，可能需要独立实例 |
| A3 | 子 Agent 的 Session 使用 `session_id` 覆盖构造是安全的 | 子 Agent 组件工厂 | Session.session_id 是 field(default_factory=uuid)，覆盖后如果有其他依赖该初始值的逻辑会出问题 |
| A4 | `ToolRegistry.register_tool_meta()` 作为新方法添加到既有类中 | AgentTool 注册 | 当前 ToolRegistry 没有直接接受 ToolMetadata 的 register 方法，现有 register() 期望 @tool 装饰过的函数 |

## 未解决问题

1. **子 Agent 是否需要独立的 TokenGuard/ContextCompressor?**
   - 已知: 子 Agent 运行在独立 Session 上，message 列表独立增长
   - 不清楚: 子 Agent 运行轮次少（max_steps=5），是否值得立即引入上下文压缩
   - 建议: Phase 6 MVP 跳过 token_guard 和 compressor，只接受 BudgetGuard 作为预算控制。如果实际运行中发现 token 超限，v2.1 引入

2. **AgentTool.execute() 是否需要通知主 FSM 暂停?**
   - 已知: 子 Agent 在 AgentTool.execute() 内部同步等待完成（await fsm.run()）
   - 不清楚: 当子 Agent 运行中发布 confirmation_required 时，主 Agent 的 web 端如何处理
   - 建议: 子 Agent 的 confirmation_required 事件使用子 session_id，主 ConfirmationDialog 按 session_id 过滤即可

3. **子 Agent 结果摘要的生成方式?**
   - 已知: D-05 要求结构化摘要 {summary, tool_calls, token_usage, steps, session_id}
   - 不清楚: summary 字段如何生成——直接取最后一条 assistant 消息？还是 LLM 再摘要？
   - 建议: v1 简单取最后一条 assistant 回复作为 summary。如果太长，v2 再引入 LLM 再摘要

4. **前端子会话事件获取方式——SSE 还是 REST?**
   - 已知: 两种方式都可行
   - 不清楚: 前端 UX 是否需要子会话实时更新（子 Agent 也在运行时实时显示）
   - 建议: Phase 6 MVP 先用 REST（`GET /api/sessions/{child_session_id}`），展示完整历史。v2.1 再考虑实时 SSE

## 环境可用性

| 依赖 | 谁需要 | 是否可用 | 版本 | 降级方案 |
|------|--------|---------|------|---------|
| Python 3.12+ | 所有后端代码 | ✓ | 3.13.x | — |
| Pydantic 2.x | AgentMetadata, 参数校验 | ✓ | 2.13.4 | — |
| asyncio | 子 Agent FSM 异步执行 | ✓ | stdlib | — |
| npm/pnpm | 前端构建 | ✓ | — | — |
| Node.js 22+ | Vite 8 开发服务器 | ✓ | — | — |

无新增外部依赖。所有依赖已在既有的 pyproject.toml 和 package.json 中声明。

## 验证架构

### 测试框架
| 属性 | 值 |
|------|-----|
| 框架 | pytest 8.x + pytest-asyncio |
| 配置文件 | pyproject.toml [tool.pytest.ini_options] |
| 快速运行命令 | `pytest tests/test_agents.py -x --timeout=10 -v` |
| 全量运行命令 | `pytest tests/ -x --timeout=10` |

### Phase 需求 → 测试映射
| 需求 ID | 行为 | 测试类型 | 自动命令 | 文件是否存在? |
|---------|------|---------|---------|-------------|
| AGT-01 | @agent 装饰器创建 AgentMetadata | unit | `pytest tests/test_agents.py::test_agent_decorator -x` | ❌ Wave 0 |
| AGT-01 | AgentTool 通过 __tool_meta__ 伪装为 Tool | unit | `pytest tests/test_agents.py::test_agent_tool_meta -x` | ❌ Wave 0 |
| AGT-02 | AgentTool.execute() 创建独立 Session | unit | `pytest tests/test_agents.py::test_sub_agent_session_isolation -x` | ❌ Wave 0 |
| AGT-03 | AgentTool.execute() 返回结构化摘要 | unit | `pytest tests/test_agents.py::test_agent_tool_result -x` | ❌ Wave 0 |
| AGT-04 | 子 Agent 超时中断 | unit | `pytest tests/test_agents.py::test_sub_agent_timeout -x` | ❌ Wave 0 |
| AGT-04 | 子 Agent BudgetGuard 独立 | unit | `pytest tests/test_agents.py::test_sub_agent_budget -x` | ❌ Wave 0 |
| AGT-05 | 子 Agent 工具集独立于主 Agent | unit | `pytest tests/test_agents.py::test_sub_agent_tool_isolation -x` | ❌ Wave 0 |
| AGT-05 | 子 Agent 只能调用注册的工具 | unit | `pytest tests/test_agents.py::test_sub_agent_tool_restriction -x` | ❌ Wave 0 |
| BIZ-03 | disk_analyzer 只能调用只读工具 | integration | `pytest tests/test_agents.py::test_disk_analyzer_tools -x` | ❌ Wave 0 |
| BIZ-03 | disk_cleaner 只能调用 disk_rm | integration | `pytest tests/test_agents.py::test_disk_cleaner_tools -x` | ❌ Wave 0 |
| WEB-01 | agent_call_start/agent_call_end 事件发布 | unit | `pytest tests/test_agents.py::test_agent_call_events -x` | ❌ Wave 0 |
| WEB-02 | 子 session_id 可被 REST API 获取 | integration | — | ❌ Wave 0 |

### 采样率
- **每次任务提交:** `pytest tests/test_agents.py -x --timeout=5 -v`
- **每个 wave 合并:** `pytest tests/test_agents.py -x --timeout=10`
- **阶段门禁:** 全量绿通过后才可 `/gsd-verify-work`

### Wave 0 缺口
- [ ] `tests/test_agents.py` — 覆盖全部 AGT-01 到 AGT-05 测试用例
- [ ] `tests/conftest.py` — 可能需要添加 `mock_agent_meta`、`mock_sub_agent_tools` 等 fixture
- [ ] `tests/conftest.py` — 可能需要添加 `agent_tool` fixture（使用 mock 组件创建 AgentTool）
- 测试框架已在 pyproject.toml 中配置（pytest-asyncio，全自动模式）

## 安全域

### 适用 ASVS 类别

| ASVS 类别 | 适用 | 标准控制 |
|-----------|------|---------|
| V2 认证 | 否 | 子 Agent 复用父 API key |
| V3 会话管理 | 部分 | 子 Session 独立 session_id，不关联用户认证 |
| V4 访问控制 | 是 | 子 Agent 权限由 tool_names 白名单控制 |
| V5 输入验证 | 是 | @agent 复用 Pydantic 参数校验（同 @tool） |
| V6 加密 | 否 | 无加密需求 |

### 已知威胁模式

| 模式 | STRIDE | 标准缓解 |
|------|--------|---------|
| 子 Agent 调用未授权工具 | 权限提升 | AgentTool 通过 tool_names 白名单控制，不允许从 ToolRegistry 按名 fetch 之外的访问 |
| 子 Agent Bash 逃逸父沙箱 | Tampering | 子 Agent 独立 ToolRegistry 但 BashTool 仍使用父配置的 working_dir (D-04) |
| 子 Agent 无限递归 | 拒绝服务 | AgentTool.tool_names 必须排除 AgentTool 自身，防止自我调用。通过 AgentRegistry 验证 |
| 子 Agent 确认弹窗劫持 | 欺骗 | 子 Agent 的 permission_guard 事件 session_id=子 session_id，前端按 session_id 过滤 |

## 来源

### 主要来源（HIGH 置信度）
- [项目代码] `src/loopai/tools/decorator.py` — @tool 装饰器的完整实现，@agent 直接复用其模式
- [项目代码] `src/loopai/tools/registry.py` — ToolRegistry 的完整实现，AgentRegistry 直接复用其模式
- [项目代码] `src/loopai/state_machine/fsm.py` — ReActFSM 执行引擎，子 Agent 的执行器
- [项目代码] `src/loopai/session/context.py` — Session 数据类，独立实例化即可
- [项目代码] `src/loopai/main.py` — create_agent_components 工厂函数，子 Agent 组件工厂参考
- [项目代码] `src/loopai/events/bus.py` — EventBus pub/sub，父子 Agent 共享同个实例
- [项目代码] `src/loopai/tools/executor.py` — ToolExecutor 执行管道，子 Agent 复用
- [项目代码] `src/loopai/tools/types.py` — ToolMetadata 定义，AgentMetadata 参考
- [项目代码] `src/loopai/tools/disk_tools.py` — 磁盘工具注册，disk_analyzer/cleaner 的工具源
- [项目代码] `src/loopai/tools/bash.py` — BashTool execution，子 Agent 需要的执行器
- [项目代码] `frontend/src/lib/eventTypes.ts` — 前端事件类型定义，新增 agent_call 事件
- [项目代码] `frontend/src/stores/eventStore.ts` — Zustand store，新增事件处理
- [项目代码] `frontend/src/components/AgentTimeline.tsx` — 时间线组件，需支持嵌套展示
- [项目代码] `frontend/src/components/StepCard.tsx` — 步骤卡片，需支持 AgentCallCard 内嵌
- [项目代码] `frontend/src/components/ConfirmationDialog.tsx` — 确认弹窗，需按 session_id 过滤

### 次要来源（MEDIUM 置信度）
- [项目测试] `tests/test_fsm.py` — FSM 测试模式，子 Agent FSM 测试参考
- [项目测试] `tests/conftest.py` — 共享 fixture，需扩展 agent_tool fixture
- [CONTEXT.md] D-01 到 D-05 锁定决策 — 约束了整个架构设计

### 三级来源（LOW 置信度）
- 无 — 所有关键决策均从既有代码模式和 CONTEXT.md 锁定决策推导

## 元数据

**置信度拆分:**
- **标准栈:** HIGH — 所有组件复用既有代码模块，已验证其存在和接口
- **架构:** HIGH — 从既有模式推演，@agent ≈ @tool, AgentRegistry ≈ ToolRegistry, AgentTool 是编排器
- **陷阱:** MEDIUM — 陷阱 1 (事件隔离) 和陷阱 4 (日志缺失) 从代码分析推演；陷阱 2 (func_ref) 和陷阱 3 (PermissionGuard) 基于架构设计推演，但未实际测试
- **前端:** MEDIUM — 嵌套组件设计基于既有 StepCard 架构推演，未验证实际渲染效果

**研究日期:** 2026-05-30
**有效期:** 7 天（基于 Phase 6 实施速度）
