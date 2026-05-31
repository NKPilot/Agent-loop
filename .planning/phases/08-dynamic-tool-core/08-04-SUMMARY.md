---
phase: 08-dynamic-tool-core
plan: 04
subsystem: tools
tags: [dynamic-tool, generate_tool, tool-registry, system-prompt, fastapi, rest]
requires:
  - phase: 08-03
    provides: DynamicToolCreator 6 阶段管道 + generate_tool 内置工具函数
provides:
  - generate_tool 在 Agent 会话中可调用（注册到 ToolRegistry + 注入 system prompt）
  - POST /api/sessions/{session_id}/confirm-tool-creation REST 端点处理用户确认/拒绝
  - system prompt 注入已注册动态工具列表（名称 + 描述 + 持久化级别）
  - 会话关闭时自动清理会话级动态工具（DYN-24）
affects: [08-05-tool-creation-ui, 09-sandbox-hardening]
tech-stack:
  added: []
  patterns:
    - "动态工具集成模式：create_agent_components 工厂函数统一创建 SandboxExecutor + ToolPersistenceManager + DynamicToolCreator"
    - "确认端点模式：通过 active_sessions 字典获取 DynamicToolCreator，调用 respond() 解除 asyncio.Event 阻塞"
    - "system prompt 动态段模式：build_system_prompt 遍历 registry.list_all() 筛选 is_dynamic=True 的工具追加独立段落"
key-files:
  created: []
  modified:
    - src/loopai/main.py - create_agent_components 注册 generate_tool + 动态工具基础设施
    - src/loopai/api/routes/control.py - confirm-tool-creation 端点 + 会话清理
    - src/loopai/tools/prompt_builder.py - build_system_prompt 追加动态工具列表
key-decisions:
  - "Session 创建提前至工具注册阶段之前，使 session.session_id 可用于 DynamicToolCreator 初始化"
  - "动态工具指引在 system prompt 中独立成段（「## 动态工具创建」），与子 Agent 说明并列"
  - "会话清理遍历 registry.list_dynamic()，仅移除无 persist: tag 的会话级工具"
patterns-established:
  - "工厂函数组件传递模式：create_agent_components 返回 dynamic_creator，start_session 将其注入 active_sessions"
  - "确认端点三层验证：session_id 存在性 → dynamic_creator 存在性 → confirmation_id 有效性 → 404 拒绝"
requirements-completed:
  - DYN-01
  - DYN-08
  - DYN-24
duration: 5min
completed: 2026-05-31
---

# Phase 8 Plan 4: generate_tool 集成到 Agent 组件工厂 + 确认端点 + 动态工具列表 Summary

**generate_tool 在 Agent 会话中可调用，confirm-tool-creation REST 端点处理用户确认/拒绝，system prompt 注入动态工具列表，会话关闭时清理会话级动态工具**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-05-31
- **Completed:** 2026-05-31
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments
- generate_tool 通过 create_agent_components 工厂函数注册到 ToolRegistry，Agent 可在会话中直接调用
- system prompt 追加「## 动态工具创建」指引段落，Agent 知晓 generate_tool 用法
- POST /api/sessions/{session_id}/confirm-tool-creation 端点可用，支持用户确认/拒绝动态工具创建
- 端点包含三层验证：session_id 存在 → dynamic_creator 存在 → confirmation_id 有效，无效请求返回 404
- 会话关闭时自动清理会话级动态工具（无 persist: tag），满足 DYN-24 生命周期要求
- build_system_prompt 自动追加已注册动态工具列表，Agent 知晓可调用的动态工具

## Task Commits

1. **Task 1: 在 create_agent_components 中注册 generate_tool 并传递 dynamic_creator** - `6ee674f` (feat)
2. **Task 2: 添加 confirm-tool-creation REST 端点 + 会话清理** - `fda3ba4` (feat)
3. **Task 3: 更新 build_system_prompt 追加动态工具列表** - `fcfc6c2` (feat)

## Files Modified
- `src/loopai/main.py` — 导入 DynamicToolCreator/SandboxExecutor/ToolPersistenceManager，创建动态工具基础设施，注册 generate_tool，追加 system prompt 指引，返回 dynamic_creator
- `src/loopai/api/routes/control.py` — 新增 confirm_tool_creation 端点，start_session 中注入 dynamic_creator，_run_and_cleanup 中清理会话级动态工具
- `src/loopai/tools/prompt_builder.py` — build_system_prompt 追加动态工具列表段落（名称 + 描述 + 持久化级别）

## Decisions Made
- Session 创建提前至工具注册阶段之前（main.py 流程重塑），使 session_id 可用于 DynamicToolCreator
- 动态工具创建指引以独立「## 动态工具创建」段落追加到 system prompt，与子 Agent 说明并列
- 会话清理仅移除无 persist: tag 的会话级工具，沙箱级/项目级工具保留
- 确认端点使用 `dynamic_creator._pending_confirmations` 直接访问，与 PermissionGuard 的 `_pending` 模式一致

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## Threat Flags

No new threat surface beyond what the plan's threat model already identified. All three STRIDE entries are addressed:
- T-08-12 (Elevation of Privilege): confirm_tool_creation 端点包含三层验证（session → dynamic_creator → confirmation_id）
- T-08-13 (Prompt Injection): system prompt 使用固定模板包裹动态工具信息，DynamicToolCreator 中已限制描述长度 500 字符
- T-08-14 (DoS): 会话清理 O(n) 遍历，动态工具数量预期 < 100，可接受

## Known Stubs

None - all integration points are fully wired.

## Next Phase Readiness
- generate_tool 管道完整贯通：Agent 调用 → 6 阶段创建 → 用户确认端点 → 工具注册 → system prompt 可见
- 前端 ToolCreationDialog（08-05）可基于 confirm-tool-creation 端点和 SSE 事件构建
- Phase 9 沙箱加固可直接复用 SandboxExecutor + DynamicToolCreator 架构

---
*Phase: 08-dynamic-tool-core*
*Completed: 2026-05-31*
