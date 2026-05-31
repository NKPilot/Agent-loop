---
phase: 08-dynamic-tool-core
plan: "01"
subsystem: api
tags: [pydantic, typescript, fastapi, monaco-editor, shadcn, event-schema]

# Dependency graph
requires: []
provides:
  - "ToolMetadata.is_dynamic 字段（默认 False，向后兼容）"
  - "6 个动态工具创建事件类型（Python Pydantic + TypeScript 接口）"
  - "Event 联合类型扩展至 32 个类型"
  - "ConfirmToolCreationRequest API Schema（PersistenceLevel + 持久化/目录权限）"
  - "前端 RiskFlag 接口和 6 个事件接口镜像"
  - "@monaco-editor/react@4.8.0-rc.3 依赖"
  - "shadcn radio-group 和 label UI 组件"
affects: [08-02, 08-03, 08-04, 08-05]

# Tech tracking
tech-stack:
  added:
    - "@monaco-editor/react@4.8.0-rc.3（代码编辑器）"
    - "shadcn radio-group + label 组件"
  patterns:
    - "类型契约层先行：Pydantic 事件 Schema 与 TypeScript 接口镜像保持一致，event_type 为判别字段"
    - "动态工具事件遵循 EventBase 基类约定，timestamp 自动生成 ISO 格式"
    - "API Schema 使用 Pydantic BaseModel + 字面量类型，保持与现有 ConfirmRequest 模式一致"

key-files:
  created:
    - "frontend/src/components/ui/label.tsx"
    - "frontend/src/components/ui/radio-group.tsx"
  modified:
    - "src/loopai/tools/types.py"
    - "src/loopai/events/schemas.py"
    - "src/loopai/api/schemas.py"
    - "frontend/src/lib/eventTypes.ts"
    - "frontend/package.json"
    - "frontend/pnpm-lock.yaml"

key-decisions:
  - "is_dynamic 字段不设 exclude，默认 False 确保向后兼容，同时允许序列化到 JSONL 日志"
  - "6 个新事件追加在 AgentCallEnd 之后，Event 联合类型位置不影响功能"
  - "PersistenceLevel 定义为模块级 Literal 类型别名，供 API Schema 和事件 Schema 共享"
  - "@monaco-editor/react 使用 @next 标签安装 4.8.0-rc.3（React 19 兼容 RC 版本）"

patterns-established:
  - "类型契约双层镜像：Python Pydantic 定义后端事件模型，TypeScript interface 定义前端镜像，event_type 字面量判别字段确保类型安全反序列化"
  - "事件扩展模式：新增事件类型继承 EventBase → 定义 Literal event_type → 加入 Event 联合类型 → 镜像到 TS Event 联合类型 → 添加 EVENT_TYPE_MAP 标签"

requirements-completed: [DYN-01, DYN-04, DYN-05, DYN-06, DYN-07, DYN-08, DYN-10, DYN-24, DYN-25, DYN-26]

# Metrics
duration: 14min
completed: 2026-05-31
---

# Phase 8 Plan 1: 类型契约层 Summary

**建立 Phase 8 动态工具系统全部模块共享的 Python/TypeScript 类型契约——ToolMetadata 扩展、6 个工具创建事件、API Schema，以及前端 Monaco Editor 和 shadcn 组件依赖**

## Performance

- **Duration:** ~14min
- **Started:** 2026-05-31T04:45:00Z
- **Completed:** 2026-05-31T04:59:00Z
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments

- ToolMetadata 新增 `is_dynamic: bool = False` 字段，不影响现有静态工具序列化
- 后端新增 6 个 Pydantic 事件模型（ToolCreationRequested/Confirmed/Rejected/TestResult/Created/Failed），Event 联合类型从 26 扩展至 32 个类型
- 前端新增 RiskFlag 接口和 6 个 TypeScript 事件接口镜像，Event 联合类型和 EVENT_TYPE_MAP 同步更新
- API Schema 新增 PersistenceLevel 字面量类型和 ConfirmToolCreationRequest 请求模型
- 安装 @monaco-editor/react@4.8.0-rc.3（代码编辑器）和 shadcn radio-group/label 组件
- TypeScript 编译零错误，Python 导入全部通过

## Task Commits

1. **Task 1: 扩展 ToolMetadata + 新增事件 Schema + 新增 API Schema** - `dbab2f9` (feat)
2. **Task 2: 新增前端 TypeScript 事件类型 + 安装依赖** - `e43e608` (feat)

## Files Created/Modified

- `src/loopai/tools/types.py` - ToolMetadata 新增 `is_dynamic: bool = False` 字段及文档
- `src/loopai/events/schemas.py` - 新增 6 个动态工具创建事件类型，Event 联合类型扩展至 32 个类型
- `src/loopai/api/schemas.py` - 新增 PersistenceLevel 类型和 ConfirmToolCreationRequest 模型，更新 __all__
- `frontend/src/lib/eventTypes.ts` - 新增 RiskFlag 接口和 6 个工具创建事件接口，扩展 Event 联合类型和 EVENT_TYPE_MAP
- `frontend/package.json` - 新增 @monaco-editor/react 依赖
- `frontend/pnpm-lock.yaml` - lockfile 更新
- `frontend/src/components/ui/label.tsx` - shadcn label 组件（新增）
- `frontend/src/components/ui/radio-group.tsx` - shadcn radio-group 组件（新增）

## Decisions Made

- is_dynamic 字段不设 Field(exclude=True)，允许序列化到 JSONL 日志供审计追踪
- 6 个新事件追加在 AgentCallEnd 之后，保持现有事件顺序不变
- PersistenceLevel 定义为模块级 Literal 类型别名而非 StrEnum，与现有 API Schema 风格一致
- @monaco-editor/react 使用 @next 标签（4.8.0-rc.3），是目前唯一支持 React 19 的版本

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- 验证时因 loopai 包以 editable mode 安装指向主仓库而非 worktree，需通过 PYTHONPATH 指向 worktree 的 src 目录进行导入验证。这是 worktree 并行执行环境的预期行为，不影响代码正确性。

## Next Phase Readiness

- 类型契约层完整就绪，下游计划（08-02 generate_tool 工具、08-03 代码校验管线、08-04 工具注册、08-05 前端确认弹窗）可并行开发
- ToolCreationRequested 事件携带完整代码载荷（Pitfall 2 已知风险：SSE 大 payload），Phase 10 优化为摘要+REST 获取

---
*Phase: 08-dynamic-tool-core*
*Completed: 2026-05-31*
