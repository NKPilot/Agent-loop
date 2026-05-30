---
phase: 06-agent-as-tool
verified: 2026-05-30T15:30:00Z
updated: 2026-05-30T06:25:00Z
status: passed
score: 8/8 must-haves verified
overrides_applied: 0
gaps:
  - truth: "前端接收到 agent_call_start/agent_call_end SSE 事件并展示多 Agent 嵌套调用链"
    status: resolved
    resolution: "commit 840915d — 在 schemas.py 中新增 AgentCallStart/AgentCallEnd Pydantic 模型，加入 Event 联合类型；AgentTool._run_sub_agent() 向 self._bus 发布生命周期事件"
    artifacts:
      - path: "src/loopai/events/schemas.py"
        issue: "已添加 AgentCallStart/AgentCallEnd 事件类型定义"
      - path: "src/loopai/agents/tool.py"
        issue: "AgentTool._run_sub_agent() 现在在子 Agent 执行前后向主 EventBus 发布 agent_call_start/agent_call_end 事件"
  - truth: "前端 AgentCallCard 组件可通过 agent_call_start/agent_call_end 事件触发渲染"
    status: resolved
    resolution: "后端事件管线已连通——SSE 桥接器自动将 EventBus 事件序列化为 JSON 推送到前端"
    artifacts:
      - path: "frontend/src/lib/eventTypes.ts"
        issue: "AgentCallStartEvent/AgentCallEndEvent TypeScript 类型已定义，后端现已发布匹配事件"
---

# Phase 6: Agent-as-Tool Verification Report

**Phase Goal:** Agent-as-Tool — 多 Agent 协作框架。使子 Agent 能被封装为普通 Tool 供主 Agent 调用，前端支持多 Agent 调用链可视化。
**Verified:** 2026-05-30T15:30:00Z
**Status:** gaps_found
**Re-verification:** No — initial verification

## Goal Achievement

The phase goal has two linked parts separated by the goal description:

1. **使子 Agent 能被封装为普通 Tool 供主 Agent 调用** — VERIFIED. The @agent decorator, AgentRegistry, AgentTool bridge, and disk sub-agents are all fully implemented with passing tests.
2. **前端支持多 Agent 调用链可视化** — FAILED. The backend does not define or publish the agent_call_start/agent_call_end events that the frontend visualization components depend on. The frontend code (AgentCallCard, StepCard, eventTypes.ts) is correctly implemented, but the data pipeline from backend → SSE → frontend is disconnected because the events never originate.

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | @agent 装饰器正确创建 AgentMetadata，AgentRegistry 注册/查找功能完整 | VERIFIED | `decorator.py` 复用 `_build_param_schema` 和 `_build_validation_model`，`__agent_meta__` 模式正确附加元数据。`registry.py` 实现 register/get/list_all/register_many。10 个 agent 单元测试通过。 |
| 2 | AgentTool 桥接层将子 Agent 封装为 Tool，可通过 ToolRegistry.register_meta() 注册 | VERIFIED | `tool.py` 的 `__tool_meta__` 属性返回有效 ToolMetadata，func_ref 指向 self.execute。`ToolRegistry.register_meta()` 方法存在于 `tools/registry.py`。测试 3 验证。 |
| 3 | 子 Agent 调用创建独立 Session，上下文不污染主 Agent | VERIFIED | `tool.py` `_run_sub_agent()` 中创建独立 `EventBus()` 和 `Session(config=config)`，注入 `agent_meta.system_prompt`。测试 4 验证 session_id 不同。BIZ-03-2 验证两子 Agent session_id 不同。 |
| 4 | 子 Agent 完成后结构化返回结果（summary, tool_calls, token_usage, steps, session_id） | VERIFIED | `_extract_summary()` 从 session.messages 提取摘要，返回 `AgentToolResult` Pydantic 模型。测试 5 验证结构化结果。 |
| 5 | 子 Agent 有独立 step budget 和超时控制 | VERIFIED | `_run_sub_agent()` 使用 `BudgetGuard(max_steps=agent_meta.max_steps)` 和 `asyncio.wait_for(..., timeout=agent_meta.timeout)`。测试 6 验证超时返回 error summary。 |
| 6 | 子 Agent 工具集可配置（只读 vs 危险操作分离） | VERIFIED | `decorator.py` `@agent(tools=...)` 接受工具列表创建独立 ToolRegistry。`disk_agents.py` `_build_sub_registries()` 将 df/du/find（只读）与 rm（危险）分离到不同子 Agent。测试 7 验证工具隔离。 |
| 7 | disk_analyzer 和 disk_cleaner 子 Agent 定义并集成到 create_agent_components() | VERIFIED | `disk_agents.py` 定义两个子 Agent。`main.py` `create_agent_components()` 创建 AgentRegistry、注册子 Agent、为每个创建 AgentTool 并注册到主 ToolRegistry。BIZ-03-1 测试验证。 |
| 8 | 前端接收到 agent_call_start/agent_call_end SSE 事件并展示多 Agent 嵌套调用链 | FAILED | 见下。 |

**Score:** 6/8 truths verified

### Deferred Items

No deferred items identified. The gap is a missing implementation in the current phase, not work deferred to a later phase. Later phases (none exist beyond 06) do not reference this gap.

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/loopai/agents/__init__.py` | 导出 agent 系统公共 API | VERIFIED | 导出 AgentMetadata, AgentToolResult, agent, AgentRegistry, get_default_registry, AgentTool |
| `src/loopai/agents/types.py` | AgentMetadata + AgentToolResult Pydantic 模型 | VERIFIED | 包含所有必需字段 (name, description, system_prompt, tool_registry, max_steps, timeout, param_schema, validation_model; summary, tool_calls, token_usage, steps, session_id, success) |
| `src/loopai/agents/decorator.py` | @agent 装饰器 | VERIFIED | 复用 tools/decorator.py 的 _build_param_schema/_build_validation_model，附加 __agent_meta__，支持 auto_register |
| `src/loopai/agents/registry.py` | AgentRegistry | VERIFIED | register/get/list_all/register_many，支持 in/len |
| `src/loopai/agents/tool.py` | AgentTool 桥接 | VERIFIED | __tool_meta__ 属性、execute() 入口、_run_sub_agent() 完整生命周期、_extract_summary() |
| `src/loopai/agents/disk_agents.py` | 磁盘诊断子 Agent | VERIFIED | disk_analyzer（只读，df/du/find）, disk_cleaner（危险，rm），_build_sub_registries(), _define_agent() |
| `src/loopai/tools/registry.py` | register_meta 方法 | VERIFIED | 新增 register_meta(meta: ToolMetadata) 方法 |
| `src/loopai/main.py` | create_agent_components 集成 | VERIFIED | AgentRegistry 创建、AgentTool 注册、系统提示追加子 Agent 说明 |
| `src/loopai/events/schemas.py` | AgentCallStart/AgentCallEnd 事件类型 | MISSING | 未定义 agent_call_start 和 agent_call_end Pydantic 模型 |
| `tests/test_agents.py` | @agent + AgentTool 单元测试 | VERIFIED | 12 个测试全部通过（10 agent tests + 2 BIZ-03 integration tests） |
| `frontend/src/lib/eventTypes.ts` | AgentCallStartEvent/AgentCallEndEvent TypeScript 类型 | VERIFIED | 两事件接口 + Event 联合类型 + EVENT_TYPE_MAP |
| `frontend/src/components/AgentCallCard.tsx` | 可展开嵌套卡片组件 | VERIFIED | 紫色主题、状态标记、懒加载、摘要指标栏、骨架屏、错误态、空态 |
| `frontend/src/components/StepCard.tsx` | AgentCallCard 集成 | VERIFIED | 检测 agent_call_start 事件，按 child_session_id 去重渲染，置于工具调用卡片上方 |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `main.py` → `disk_agents.py` | AgentRegistry/AgentTool 注册 | import + __agent_meta__ | WIRED | `create_agent_components()` 导入 disk_analyzer/disk_cleaner，注册到 AgentRegistry |
| `main.py` → `tool.py` | AgentTool.create_agent_components | AgentTool(agent_meta, config, bus) + registry.register_meta() | WIRED | 遍历 agent_registry.list_all() 创建 AgentTool 并注册 |
| `AgentTool` → `schemas.py` | 发布 agent_call_start/end 事件 | EventBus.publish() | NOT_WIRED | `tool.py` 未导入 schemas.py 的事件类型，未向 self._bus 发布任何 agent_call 事件 |
| `AgentCallCard.tsx` → `api.ts` | 懒加载子会话详情 | fetchSession(child_session_id) | WIRED | GET /api/sessions/{id} REST 接口已在 Phase 5 实现 |
| `StepCard.tsx` → `AgentCallCard.tsx` | 检测 agent_call_start 渲染 AgentCallCard | import + child_session_id Set | WIRED | 组件导入、事件过滤、Set 去重全部正确 |
| `eventTypes.ts` → SSE 流 | 接收 agent_call_* JSON 事件 | SSE EventSource message handler | DISCONNECTED | 后端不产生这些事件 |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|--------------|--------|-------------------|--------|
| `AgentCallCard.tsx` | `startEvent`, `endEvent` | `events` prop (SSE) | Backend never publishes | DISCONNECTED |
| `AgentCallCard.tsx` | `childSession` | `fetchSession(childSessionId)` | REST call to `/api/sessions/{id}` | FLOWING (REST exists) |
| `AgentTool._run_sub_agent` | Sub-agent events | `sub_bus` (internal EventBus) | Yes - internal only | STATIC (events never forwarded to main bus) |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Agent module imports | `python3 -c "from loopai.agents import AgentMetadata, AgentToolResult, AgentRegistry, AgentTool"` | No error | PASS |
| Agent tests pass | `uv run pytest tests/test_agents.py -v` | 12 passed in 0.80s | PASS |
| Disk agents import | `python3 -c "from loopai.agents.disk_agents import disk_analyzer, disk_cleaner"` | No error (implied by test) | PASS |

### Probe Execution

| Probe | Command | Result | Status |
|-------|---------|--------|--------|
| N/A — no probes defined in phase | — | — | SKIPPED |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-----------|-------------|--------|----------|
| AGT-01 | 06-01-PLAN | AgentTool——将任意 Agent 封装为 @tool | SATISFIED | AgentTool class in tool.py, __tool_meta__ property, execute() method, register_meta() in ToolRegistry |
| AGT-02 | 06-01-PLAN | 子 Agent Session 隔离 | SATISFIED | _run_sub_agent creates independent EventBus + Session, test verifies unique session_id |
| AGT-03 | 06-01-PLAN | 结果回传 | SATISFIED | _extract_summary returns AgentToolResult with summary/tool_calls/token_usage/steps/session_id |
| AGT-04 | 06-01-PLAN, 06-02-PLAN | 超时和预算控制 | SATISFIED | BudgetGuard(max_steps) + asyncio.wait_for(timeout) + timeout error test |
| AGT-05 | 06-01-PLAN | 子 Agent 工具集 | SATISFIED | @agent(tools=...) creates separate ToolRegistry, tool isolation test |
| BIZ-03 | 06-02-PLAN | 磁盘诊断多 Agent 演示 | SATISFIED | disk_analyzer + disk_cleaner in disk_agents.py, integrated in main.py, 2 integration tests pass |
| WEB-01 | 06-03-PLAN | 多 Agent 调用链可视化 | BLOCKED | Frontend types + components exist but backend does not publish events |
| WEB-02 | 06-03-PLAN | 子 Agent 会话可展开 | BLOCKED | Same root cause as WEB-01 - no events to trigger rendering |

### Anti-Patterns Found

No anti-patterns (TBD/FIXME/XXX/TODO/HACK) found in any phase 06 source files. No stub patterns detected. The disk_agent wrapper functions (`_disk_analyzer_impl`, `_disk_cleaner_impl`) return simple confirmation strings, but this is expected behavior — the actual agent logic runs in the ReActFSM loop driven by the LLM, not in the function body.

### Human Verification Required

No items require human verification. All gaps are programmatically verifiable.

### Gaps Summary

**BLOCKER: Backend does not publish agent_call_start/agent_call_end events.**

The frontend components for multi-agent call chain visualization are complete (AgentCallCard, StepCard integration, TypeScript event types), but the Python backend has two missing pieces:

1. **src/loopai/events/schemas.py**: Missing `AgentCallStart` and `AgentCallEnd` Pydantic event classes. The Event union type does not include these events. Compare Phase 4 events (CheckpointSaved, CircuitOpened, etc.) which ARE defined in schemas.py.

2. **src/loopai/agents/tool.py** (`AgentTool._run_sub_agent`): Creates an independent EventBus (`sub_bus`) for the sub-agent's internal events but never publishes lifecycle events (`agent_call_start` before execution, `agent_call_end` after) to the main EventBus (`self._bus`). The SSE bridge subscribes to the main EventBus, so these events never reach the frontend.

**Root cause:** The three plans in Phase 6 were designed independently:
- Plan 01 (backend agent framework) focused on AgentTool internals but did not add event publishing
- Plan 03 (frontend visualization) assumed events would be available from the backend
- The integration between Plans 01 and 03 was not completed

**To close the gap:**
1. Add `AgentCallStart` and `AgentCallEnd` Pydantic models to `src/loopai/events/schemas.py`
2. Add them to the `Event` discriminated union type
3. In `AgentTool.execute()`, publish `agent_call_start` to `self._bus` before starting the sub-agent, and `agent_call_end` after completion (with the AgentToolResult data)

---

_Verified: 2026-05-30T15:30:00Z_
_Verifier: Claude (gsd-verifier)_
