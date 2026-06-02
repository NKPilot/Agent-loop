---
phase: 10-ux-tool-management
plan: 02
subsystem: api
tags: [tools, rest-api, dynamic-tools, tool-management, event-bus]
requires:
  - "10-01 — 基础设施层（Schema 扩展 + 事件类型 + 持久化加载）"
provides:
  - "10-03 — 前端工具管理 UI（依赖本计划的 REST 端点）"
affects:
  - src/loopai/api/schemas.py
  - src/loopai/api/routes/tools.py
  - src/loopai/api/app.py
  - src/loopai/tools/dynamic_creator.py
  - src/loopai/main.py
tech-stack:
  added: ["FastAPI APIRouter（工具管理路由）"]
  patterns: ["跨会话注册表去重", "EventBus 工具管理事件发布"]
key-files:
  created:
    - src/loopai/api/routes/tools.py
  modified:
    - src/loopai/api/schemas.py
    - src/loopai/api/app.py
    - src/loopai/tools/dynamic_creator.py
    - src/loopai/main.py
decisions:
  - "REST 端点使用免认证设计（单用户本地工具，无网络暴露面，per T-10-04 accept）"
  - "list_tools 内置工具使用 SAFE 权限级别（只读查询，无需用户确认）"
metrics:
  duration: "~3 分钟"
  completed_date: "2026-06-02"
---

# Phase 10 Plan 02: 工具管理 REST 端点 + 更新检测 + list_tools

## One-Liner

后端 API 层：5 个工具管理 REST 端点（list/get/disable/enable/delete）+ DynamicToolCreator Stage 0 更新检测（is_update + old_code）+ create_list_tools_fn 内置工具工厂，注册到 main.py。

## Tasks Completed

| # | Task | Type | Commit | Key Files |
|---|------|------|--------|-----------|
| 1 | 创建 tools.py 路由 + schemas.py 扩展 + app.py 挂载 | auto | `7963126` | `api/schemas.py`, `api/routes/tools.py`, `api/app.py` |
| 2 | DynamicToolCreator 更新检测 + list_tools 内置工具 + main.py 注册 | auto | `734db00` | `tools/dynamic_creator.py`, `main.py` |

## Key Implementation Details

### Task 1: REST 端点

- **GET /tools/** — 收集所有活跃会话的 ToolRegistry，按工具名去重（首条胜出），从 tags 中提取 persistence/lang，返回排序后的 ToolListResponse
- **GET /tools/{tool_name}** — 跨会话注册表查找单个工具，返回完整 ToolDetailResponse（含源代码和 param_schema）
- **POST /tools/{tool_name}/disable** — 跨会话设置 enabled=False，同步更新持久化文件 meta.json，发布 `tool_disabled` 事件
- **POST /tools/{tool_name}/enable** — 与 disable 对称，设置 enabled=True，发布 `tool_enabled` 事件
- **POST /tools/{tool_name}/delete** — 需 `confirmation=true`，从所有注册表移除 + 清理持久化文件系统 + 发布 `tool_deleted` 事件

### Task 2: 更新检测 + list_tools

- **Stage 0 更新检测:** `generate_tool()` 计算 tool_id 后立即调用 `registry.get(tool_id)` 检测冲突，设置 `is_update` 和 `old_code`
- **_stage3_user_confirmation:** 事件 payload 新增 `is_update` 和 `old_code` 字段，前端可据此展示新旧代码 diff
- **_stage56_persist_and_register:** is_update 时原地更新现有 meta 的 code/description/param_schema/func_ref，不修改 tags（保留持久化级别），发布 `tool_updated` 事件
- **create_list_tools_fn:** 工厂函数创建 `@tool(name="list_tools")` 内置工具，detail 参数控制是否返回源代码

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None found.

## Threat Flags

None — all endpoints are in the plan's must_haves and threat register has `accept` disposition for all tool management endpoints (single-user local tool, no network exposure).

## Verification

- Tool schemas import OK (ToolSummary, ToolListResponse, ToolDetailResponse, ToolActionResponse, ToolDeleteRequest)
- Tools router has 5 routes: GET /tools/, GET /tools/{tool_name}, POST disable/enable/delete
- create_list_tools_fn produces @tool with name="list_tools" and permission_level="safe"
- is_update and old_code params present in _stage3_user_confirmation and _stage56_persist_and_register signatures

## Self-Check: PASSED

- [x] All 5 schema models created and importable
- [x] tools.py contains exactly 5 endpoints
- [x] app.py mounts tools.router at /api prefix
- [x] DynamicToolCreator detects name conflicts at Stage 0
- [x] _stage3_user_confirmation includes is_update and old_code in payload
- [x] Update flow updates in-place instead of re-registering
- [x] Update flow publishes tool_updated event
- [x] create_list_tools_fn exported in __all__ and produces valid @tool
- [x] main.py registers list_tools in create_agent_components
