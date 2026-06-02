---
phase: 10-ux-tool-management
plan: 03
subsystem: frontend
tags:
  - tool-management
  - ui
  - monaco-editor
  - sidepanel
dependency_graph:
  requires:
    - "10-02 (工具管理 REST API)"
    - "Phase 8 (ToolCreationDialog 基础)"
  affects:
    - "ToolManagementPanel API consumers"
    - "ToolCreationDialog update flow"
tech-stack:
  added:
    - "@base-ui/react Switch (via shadcn)"
  patterns:
    - "Sidebar overlay matching SessionList pattern (fixed z-50, backdrop)"
    - "Monaco DiffEditor side-by-side for code change review"
    - "Inline delete confirmation with auto-reset timer"
key-files:
  created:
    - "frontend/src/components/ToolManagementPanel.tsx"
  modified:
    - "frontend/src/stores/uiStore.ts"
    - "frontend/src/lib/api.ts"
    - "frontend/src/App.tsx"
    - "frontend/src/components/ToolCreationDialog.tsx"
    - "frontend/src/lib/eventTypes.ts"
    - "frontend/src/components/ui/switch.tsx"
    - "frontend/package.json"
decisions:
  - "Switch uses shadcn/ui Switch (@base-ui/react primitive), matching project's existing component pattern"
  - "ToolManagementPanel fetches tools directly via fetch() rather than React Query for simplicity (no caching need)"
  - "DiffEditor rendered side-by-side for code change visual comparison in update mode"
  - "Delete confirmation auto-resets after 3 seconds idle, matching D-12 spec"
metrics:
  duration: 1m 35s
  completed_date: "2026-06-02"
---

# Phase 10 Plan 03: 动态工具管理面板 + ToolCreationDialog 更新模式 Summary

前端 UI：工具管理侧边栏面板 + ToolCreationDialog 更新模式。用户可通过侧边栏面板查看所有动态工具列表、展开查看代码、启用/禁用开关、内联删除确认。ToolCreationDialog 扩展 update 模式支持 Monaco DiffEditor 对比新旧代码。

## Tasks

| # | Name | Status | Commit |
|---|------|--------|--------|
| 1 | uiStore 扩展 + api.ts 工具管理函数 + switch 组件 | Done | `50eb7b7` |
| 2 | 创建 ToolManagementPanel 侧边栏组件 | Done | `5c1ad59` |
| 3 | ToolCreationDialog update 模式 + App.tsx Wrench 按钮集成 | Done | `0f0d31d` |

## Files Created/Modified

### Created
- **`frontend/src/components/ToolManagementPanel.tsx`** — (362 lines) 侧边栏工具管理组件。覆盖层布局（w-80 面板 + 遮罩），工具列表展示名称/语言 Badge/持久化 Badge/Switch 开关，展开 Monaco Editor 只读代码，内联删除二次确认。空状态中文引导提示。

### Modified
- **`frontend/src/stores/uiStore.ts`** — 添加 `toolPanelOpen` 状态和 `setToolPanelOpen` setter
- **`frontend/src/lib/api.ts`** — 添加 `ToolSummary`、`ToolDetail` 接口和 `fetchTools`、`fetchToolDetail`、`disableTool`、`enableTool`、`deleteTool` 函数
- **`frontend/src/App.tsx`** — Header 添加 Wrench 图标按钮，`toolPanelOpen` 为 true 时渲染 ToolManagementPanel
- **`frontend/src/components/ToolCreationDialog.tsx`** — 导入 DiffEditor，update 模式使用 DiffEditor side-by-side 展示代码变更，隐藏 Persistence 区域，标题/描述根据 `is_update` 切换
- **`frontend/src/lib/eventTypes.ts`** — ToolCreationRequestedEvent 添加 `old_code?: string` 字段
- **`frontend/src/components/ui/switch.tsx`** — 通过 shadcn CLI v4 创建

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical field] ToolCreationRequestedEvent 缺少 `old_code` 字段**

- **Found during:** Task 3
- **Issue:** Plan 要求在 update 模式中使用 `event.old_code` 作为 DiffEditor 的 `original` 值，但 TypeScript 类型定义中缺少该字段
- **Fix:** 在 `ToolCreationRequestedEvent` 接口中添加 `old_code?: string` 可选字段
- **Files modified:** `frontend/src/lib/eventTypes.ts`
- **Commit:** `0f0d31d`

## Key Features Delivered

1. **ToolManagementPanel 侧边栏面板** — 固定覆盖层，w-80 宽度，背景遮罩
   - 加载时显示 Skeleton 骨架屏
   - 空状态显示中文提示："暂无动态工具。当 Agent 在会话中创建工具并经你确认后，它们会出现在这里。"
   - 工具行显示名称、语言 Badge、持久化级别 Badge、Switch 启用/禁用开关
   - 展开后 Monaco Editor 只读展示完整代码（高度 200px，vs-dark 主题）
   - Switch 即时调用 API 切换启用/禁用状态
   - 删除按钮点击后内联显示二次确认询问（"删除 {name}（{persistence}级）？" + "是"/"否"），3秒无操作自动复位
   - 删除成功后显示不可撤销提示，3秒后自动清除
   - 点击遮罩关闭面板
   - 点击 X 按钮关闭面板

2. **ToolCreationDialog update 模式**
   - `event.is_update=true` 时代码区使用 Monaco DiffEditor（side-by-side 布局）
   - 标题显示 "Update Tool"，描述更新为代码变更审阅
   - Persistence 持久化选择区域隐藏（D-09）
   - 代码区标题显示 "Code Changes" + "Update Mode" amber Badge

3. **App.tsx 集成**
   - Header 新增 Wrench 图标按钮（在 History 按钮旁）
   - 点击切换 `toolPanelOpen` 状态
   - ToolManagementPanel 在 `toolPanelOpen=true` 时渲染

## Stub Tracking

No stubs detected. All components have real data wiring:
- ToolManagementPanel fetches from `/api/tools/` via fetchTools()
- Switch toggle calls disableTool/enableTool API
- Delete calls deleteTool API with confirmation payload
- Monaco Editor renders real event.code content
- DiffEditor uses real event.old_code and event.code

## Threat Surface Scan

| Flag | File | Description |
|------|------|-------------|
| threat_flag: new-api-consumer | frontend/src/lib/api.ts | New API consumer functions (fetchTools, fetchToolDetail, disableTool, enableTool, deleteTool) that call /api/tools/ endpoints. All use standard fetch() with no auth headers — follows existing pattern. |

No additional surface beyond the planned tool management API endpoints. All threats from plan's threat model were addressed:
- T-10-08 (Information Disclosure): Monaco Editor is readOnly=true, code displayed is already user-confirmed
- T-10-09 (DoS): Switch toggle calls are user-action-gated, single API call per toggle
- T-10-10 (Tampering): DiffEditor is readOnly=true, decisions pass through Approve/Reject buttons

## Verification Results

```
$ cd frontend && npx tsc --noEmit
# 0 TypeScript errors
```

| Check | Result |
|-------|--------|
| TypeScript compilation | 0 errors |
| ToolManagementPanel.tsx exists | YES (362 lines, >=200) |
| DiffEditor imported in ToolCreationDialog | YES (3 references) |
| ToolManagementPanel imported in App.tsx | YES (2 references) |
| Wrench icon in App.tsx | YES (2 references) |
| toolPanelOpen in uiStore.ts | YES (3 references) |
| fetchTools/fetchToolDetail in api.ts | YES (5 functions exported) |

## Success Criteria Met

- [x] ToolManagementPanel 组件存在，正确渲染工具列表
- [x] 空状态显示 D-02 指定的中文提示
- [x] 展开视图显示 Monaco Editor 只读代码
- [x] Switch 开关即时调用 disable/enable API
- [x] 内联删除二次确认按 D-12/D-13/D-14 实现
- [x] ToolCreationDialog 更新模式显示 Monaco DiffEditor
- [x] 更新模式隐藏持久化选择
- [x] App.tsx 集成 Wrench 按钮和面板
- [x] TypeScript 编译零错误

## Self-Check: PASSED
