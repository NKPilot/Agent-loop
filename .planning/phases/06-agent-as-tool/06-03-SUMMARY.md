---
phase: 06-agent-as-tool
plan: 03
subsystem: ui
tags: [react, typescript, agent-call-card, multi-agent, dashboard]

# Dependency graph
requires:
  - phase: 05-observability
    provides: SSE streaming, event types, StepCard component, Dashboard timeline
provides:
  - AgentCallStartEvent/AgentCallEndEvent 类型定义
  - AgentCallCard 可展开嵌套卡片组件
  - StepCard 多 Agent 调用集成
affects: [06-agent-as-tool]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "AgentCallCard 可展开嵌套模式：懒加载子会话，状态驱动展开/折叠"
    - "类型安全事件查找器：通过 discriminated union 过滤事件数组"

key-files:
  created:
    - frontend/src/components/AgentCallCard.tsx
  modified:
    - frontend/src/lib/eventTypes.ts
    - frontend/src/components/StepCard.tsx

key-decisions:
  - "AgentCallCard 使用紫色主题以区别于普通工具调用"
  - "AgentCallCard 置于工具调用卡片上方，视觉上先展示嵌套调用关系"
  - "子会话数据在展开时懒加载（非挂载时预加载），避免不必要的 API 请求"
  - "通过唯一 child_session_id 去重（Set），支持同一步骤多次子 Agent 调用"
  - "加载态使用 animate-pulse 骨架屏，与项目现有 Skeleton 风格一致"

patterns-established:
  - "AgentCallCard 可展开嵌套模式：懒加载子会话数据，状态驱动展开/折叠"
  - "类型安全事件过滤：通过 type predicate 函数从 Event 联合类型中安全提取特定事件"

requirements-completed: [WEB-01, WEB-02]

# Metrics
duration: 18min
completed: 2026-05-30
---

# Phase 6 Plan 3: 前端多 Agent 调用链可视化 Summary

**AgentCallStart/AgentCallEnd 事件类型 + AgentCallCard 可展开嵌套卡片 + StepCard 集成**

## Performance

- **Duration:** 18min
- **Started:** 2026-05-30T14:00:00Z
- **Completed:** 2026-05-30T14:18:00Z
- **Tasks:** 2/2
- **Files modified:** 3

## Accomplishments

- 在 eventTypes.ts 中新增 AgentCallStartEvent/AgentCallEndEvent 接口类型，更新 Event 联合类型和 EVENT_TYPE_MAP
- 创建 AgentCallCard 组件：紫色主题卡片、agent 名称与状态标记、可展开加载子会话详情、摘要栏展示 tool_calls/tokens/steps 指标
- StepCard 集成：检测 agent_call_start 事件，按唯一 child_session_id 渲染 AgentCallCard 列表，置于普通工具调用卡片上方

## Task Commits

Each task was committed atomically:

1. **Task 1: TypeScript 事件类型 + AgentCallCard 组件** - `8761bdf` (feat)
2. **Task 2: StepCard 集成 AgentCallCard** - `866d7b3` (feat)

**Plan metadata:** `pending` (docs: complete 06-03 plan)

## Files Created/Modified

- `frontend/src/lib/eventTypes.ts` - 新增 AgentCallStartEvent/AgentCallEndEvent 接口，更新 Event 联合类型和 EVENT_TYPE_MAP
- `frontend/src/components/AgentCallCard.tsx` - 新建：紫色主题可展开嵌套卡片，展示 Agent 名称/状态/摘要/子会话 REST 加载
- `frontend/src/components/StepCard.tsx` - 集成 AgentCallCard：检测 agent_call_start 事件，按 child_session_id 渲染，置于普通工具调用卡片上方

## Decisions Made

- **紫色主题区分**：AgentCallCard 使用紫色边界/背景，明显区别于普通工具调用的默认风格，帮助用户快速识别嵌套 Agent 调用关系
- **展开懒加载**：子会话详情不在组件挂载时立即加载，而是等待用户点击展开后才发起 REST 请求（`fetchSession`）。避免用户在未展开时产生不必要的网络请求
- **上方展示**：AgentCallCard 放置在普通工具调用卡片上方，遵循"从嵌套到具体"的视觉信息层级
- **ID 去重**：从 agent_call_start 事件提取 child_session_id 时使用 Set 去重，避免同步骤多次调用同一子 Agent 时重复渲染

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- **CWD-Drift (工作任务目录偏移)**：该工作树（worktree）的根目录为 `/home/atis/HE/loopAI/.claude/worktrees/agent-a0604d4a006bbfd36`，但首次 Write/Edit 调用使用了主仓库的绝对路径（`/home/atis/HE/loopAI/frontend/...`），导致修改落入主仓库而非工作树。已在发现后通过使用工作树根路径重新写入修正。后续操作均使用工作树相对路径或派生自 `git rev-parse --show-toplevel` 的路径。此为已知问题 #3097 / #3099。

## Stub Tracking

No stubs found. The AgentCallCard component properly handles loading, empty, and error states. All displayed data is either from live SSE events (agent_call_start/agent_call_end) or REST API calls (fetchSession).

## Threat Flags

None - no new network endpoints, auth paths, or security-relevant surface introduced.

## Next Phase Readiness

- 前端 Agent-as-Tool 事件类型和可视化组件就绪
- 等待后端 Agent-as-Tool 事件发布后即可在 Dashboard 展示多 Agent 调用链
- StepCard 集成检测逻辑自动生效，无需额外前端配置

## Self-Check: PASSED

- eventTypes.ts: FOUND
- AgentCallCard.tsx: FOUND
- StepCard.tsx: FOUND
- SUMMARY.md: FOUND
- Commit 8761bdf: FOUND (feat: 添加事件类型和 AgentCallCard 组件)
- Commit 866d7b3: FOUND (feat: StepCard 集成 AgentCallCard)
- Commit cb92866: FOUND (docs: complete 06-03 计划)

No missing files or commits. All claims in SUMMARY.md verified.

---
*Phase: 06-agent-as-tool*
*Completed: 2026-05-30*
