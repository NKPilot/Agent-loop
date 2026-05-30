---
phase: 06-agent-as-tool
plan: 02
subsystem: agents
tags: [agent, disk, diagnostic, multi-agent, @agent, AgentTool, BIZ-03]
requires:
  - phase: 06-01
    provides: @agent decorator, AgentRegistry, AgentTool bridge
  - phase: 06-03
    provides: AgentCallCard frontend component, agent_call_start/end event types
provides:
  - disk_analyzer sub-agent (read-only diagnostics with df/du/find)
  - disk_cleaner sub-agent (cleanup execution with rm)
  - create_agent_components() integration with AgentTool registration
  - BIZ-03 integration tests for multi-agent disk diagnostic flow
affects: [06-01, 06-03, Phase 5 web dashboard]
tech-stack:
  added: []
  patterns:
    - Sub-agent ToolRegistry created via register_meta() from pre-existing tool functions
    - AgentMetadata constructed directly (not via @agent(tools=[]) due to func_ref.__tool_meta__ constraint)
    - Tool isolation: read-only vs dangerous tools separated per agent
key-files:
  created:
    - src/loopai/agents/disk_agents.py
  modified:
    - src/loopai/main.py
    - tests/test_agents.py
key-decisions:
  - "D-06: disk_agents.py builds AgentMetadata directly using _define_agent() rather than @agent(tools=[]) because ToolMetadata.func_ref points to the original function (not the @tool wrapper), which lacks __tool_meta__ required by ToolRegistry.register()"
  - "Sub-agent tool working_dir defaults to .sandbox (same as register_disk_tools default). Runtime config.tool_working_dir is not propagated to sub-agents in this plan."
requirements-completed: [AGT-04, BIZ-03]
duration: 15min
completed: 2026-05-30
---

# Phase 6 Agent-as-Tool Plan 02: 磁盘诊断子 Agent + 多 Agent 集成

**创建 disk_analyzer 和 disk_cleaner 两个子 Agent，集成到 create_agent_components()，实现 BIZ-03 多 Agent 磁盘诊断端到端验证**

## Performance

- **Duration:** 15 min
- **Started:** 2026-05-30T13:40:00Z (approx)
- **Completed:** 2026-05-30T13:55:00Z (approx)
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- disk_analyzer 子 Agent：只读诊断 Agent，tool_registry 包含 disk_df/disk_du/disk_find，max_steps=10
- disk_cleaner 子 Agent：清理执行 Agent，tool_registry 仅包含 disk_rm（危险操作），max_steps=5
- create_agent_components() 集成：创建 AgentRegistry、为每个子 Agent 创建 AgentTool 桥接、通过 register_meta() 注册到主 ToolRegistry
- 系统提示中追加"可用子 Agent"说明，使 LLM 知晓可委托子任务
- BIZ-03-1 测试：验证 AgentTool 在 ToolRegistry 中，tool schemas 包含子 Agent 的 function 定义
- BIZ-03-2 测试：Mock 多 Agent 端到端流程，先调用 disk_analyzer 分析再调用 disk_cleaner 清理

## Task Commits

Each task was committed atomically:

1. **Task 1: 磁盘诊断子 Agent 定义** - `b17e34f` (feat)
2. **Task 2: create_agent_components 集成 + BIZ-03 测试** - `c6b6066` (feat)

## Files Created/Modified

### Created
- `src/loopai/agents/disk_agents.py` - disk_analyzer 和 disk_cleaner 子 Agent 定义，包含 _build_sub_registries() 和 _define_agent() 辅助函数

### Modified
- `src/loopai/main.py` - create_agent_components() 中添加 AgentRegistry 创建、AgentTool 注册、系统提示追加
- `tests/test_agents.py` - 新增 BIZ-03-1 和 BIZ-03-2 两个集成测试（共 12 个测试全部通过）

## Decisions Made

1. **D-06: 直接构建 AgentMetadata 而非使用 @agent(tools=[])**
   - **背景:** @agent(tools=[]) 内部调用 ToolRegistry.register(t)，要求 t 有 __tool_meta__。
   - **问题:** disk_tools.py 中 @tool 装饰器将 ToolMetadata.func_ref 设为原始函数（而非包装器），原始函数没有 __tool_meta__。
   - **解决:** 使用 _define_agent() 直接从 _build_param_schema() 构建 AgentMetadata 并附加 __agent_meta__。

2. **子 Agent 工具工作目录**
   - 子 Agent 的工具函数默认绑定到 ".sandbox"（register_disk_tools 的默认值）。
   - 暂未从 AgentConfig.tool_working_dir 传播（D-04）。后续计划可改进此点。

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

1. **func_ref 缺少 __tool_meta__ 导致 @agent(tools=[]) 失败**
   - 最初使用 @agent(tools=[extracted_func_ref]) 模式，但 ToolMetadata.func_ref 指向 @tool 装饰器的原始函数（func），而非装饰后的包装器。
   - 解决：改用 _define_agent() + _build_sub_registries() 模式，通过 ToolRegistry.register_meta() 注册工具元数据。

2. **工作目录路径差异（Main Repo vs Worktree）**
   - 使用 Write 工具时路径以主仓库为基准，需要手动 cp 到 worktree 目录。
   - 已通过每次 Edit/Write 后复制到 worktree 解决。

## Stub Tracking

No stubs identified. The sub-agent wrapper functions contain minimal logic (return confirmation message), which is expected behavior since the actual agent logic is in the ReActFSM loop driven by LLM calls, not in the function body.

## Threat Flags

None - no new network endpoints, auth paths, or trust boundary changes introduced.

## Self-Check: PASSED

- [x] `src/loopai/agents/disk_agents.py` exists and imports correctly
- [x] `src/loopai/main.py` modified with AgentTool registration
- [x] `tests/test_agents.py` modified with BIZ-03 tests
- [x] Commit b17e34f exists (Task 1)
- [x] Commit c6b6066 exists (Task 2)
- [x] All 12 agent tests pass (`uv run pytest tests/test_agents.py -v`)

---
*Phase: 06-agent-as-tool*
*Completed: 2026-05-30*
