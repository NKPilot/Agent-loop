---
phase: 10-ux-tool-management
verified: 2026-06-02T11:00:00Z
status: gaps_found
score: 10/10 must-haves verified
overrides_applied: 0
gaps:
  - truth: "DYN-17 — 禁用工具不出现在 system prompt"
    status: failed
    reason: "禁用工具仍出现在 system prompt 的 '## 动态工具' 信息段落中。get_schemas() 正确过滤了禁用工具（不可被 Agent 调用），但 prompt_builder.py 中 list_all() 未过滤 enabled=False。计划明确选择了不修改 prompt_builder.py，导致此设计缺口。"
    artifacts:
      - path: "src/loopai/tools/prompt_builder.py"
        issue: "第 59 行 dynamic_tools 列表推导使用 registry.list_all() 而非 registry.get_schemas()，未过滤 enabled=False 的工具。第 65-70 行将所有动态工具（含禁用）写入 system prompt。"
    missing:
      - "prompt_builder.py 中 '## 动态工具' 段落应过滤 enabled=False 的工具，或直接使用已过滤 get_schemas() 中的工具列表"
deferred: []
---

# Phase 10: 用户体验与工具管理 Verification Report

**Phase Goal:** 用户可通过前端"动态工具"面板集中管理所有动态工具——查看代码、启用/禁用、删除、diff 更新对比、命名冲突处理。工具发现系统确保 Agent 始终知晓可用动态工具

**Verified:** 2026-06-02T11:00:00Z
**Status:** gaps_found
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths (Roadmap Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | 用户在侧边栏"动态工具"tab 中可查看所有动态工具列表，包括名称、描述、持久化级别 Badge 和启用/禁用状态 | VERIFIED | ToolManagementPanel.tsx 第 231-268 行: 工具列表渲染（名称、语言 Badge、持久化级别 Badge、Switch 开关）。通过 fetchTools() 从 `/api/tools/` 获取数据。持久化级别从 tags 中 "persist:" 前缀提取。空状态中文引导提示（D-02）。 |
| 2 | 用户点击工具项可查看完整代码（Monaco Editor 语法高亮只读）；禁用工具后，该工具不出现在 system prompt 且不可被 Agent 调用 | WARNING | **查看代码:** VERIFIED — ToolManagementPanel.tsx 第 76-106 行 toggleExpand 展开后 Monaco Editor 只读展示。**不可调用:** VERIFIED — get_schemas() 过滤 enabled=False（registry.py 第 224 行）。**不出现在 system prompt:** FAILED — prompt_builder.py 第 59 行 "## 动态工具" 段落仍列出禁用工具（见 gaps 说明）。 |
| 3 | 用户可删除动态工具（含确认弹窗），系统根据持久化级别自动清理对应存储 | VERIFIED | 内联二次确认（ToolManagementPanel.tsx 第 135-157 行），调用 POST `/api/tools/{name}/delete`（tools.py 第 300-370 行），`registry.remove()` 清理注册表，`ToolPersistenceManager.delete()` 清理文件系统。 |
| 4 | Agent 提交已有工具的新版本时，前端展示新旧代码 side-by-side Monaco DiffEditor，用户选择覆盖或拒绝；命名冲突时同样展示对比供用户决策 | VERIFIED | DynamicToolCreator.generate_tool() Stage 0 检测更新（dynamic_creator.py 第 125-128 行），_stage3 事件 payload 含 is_update+old_code（第 385-401 行），ToolCreationDialog.tsx 第 215-234 行 DiffEditor side-by-side 展示，accept/reject 按钮。 |
| 5 | 系统启动时自动扫描并加载所有持久化动态工具，工具名和描述注入 system prompt；Agent 可通过 list_tools 内置工具查询所有动态工具的详细信息（含完整 Schema） | VERIFIED | **启动加载:** main.py 第 101-135 行: load_sandbox_tools + load_project_tools 循环。**注入 system prompt:** prompt_builder.py 第 32 行 get_schemas() + 第 58-71 行动态工具段落。**list_tools:** dynamic_creator.py 第 753-802 行 create_list_tools_fn，main.py 第 148-150 行注册。 |

**Score:** 10/10 must-haves verified (1 warning on DYN-17 system prompt gap)

### Must-Haves Verification

#### Plan 01 — 后端类型层基础设施

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | 禁用工具从 LLM 工具列表中自动消失——get_schemas() 过滤 enabled=False，system prompt 和 function calling 均不包含禁用工具 | VERIFIED | registry.py 第 224 行: `dynamic_tools = [m for m in self._dynamic_tools.values() if m.enabled]`。prompt_builder.py 第 32 行使用 get_schemas() 构建可用工具列表。已验证 python 测试 get_schemas 过滤 enabled=False。 |
| 2 | 禁用状态跨重启持久化——重启后禁用工具仍保持禁用，meta.json 中 enabled 字段正确读写 | VERIFIED | tool_persistence.py 第 336 行: `"enabled": extra.get("enabled", True)`。tools.py 第 376-407 行 `_update_persistence_enabled()` 同步更新 meta.json。main.py 第 112 行启动加载时读取 enabled。 |
| 3 | 系统启动时自动发现并加载沙箱级和项目级动态工具——无需手动注册 | VERIFIED | main.py 第 102-135 行: for loader_name, loader_fn in [("sandbox", persistence.load_sandbox_tools), ("project", persistence.load_project_tools)] 的循环动态加载。 |
| 4 | disable/enable/delete/update 操作产生审计事件写入 JSONL——完整可追溯 | VERIFIED | schemas.py 第 449-477 行: ToolDisabled、ToolEnabled、ToolDeleted、ToolUpdated 4 个事件类型。Event 联合类型包含所有 4 个（第 518-521 行）。tools.py 各端点在操作后发布事件。 |
| 5 | 工具创建事件（ToolCreationRequested）携带 is_update 标记——前端据此切换创建/更新 UI | VERIFIED | schemas.py 第 333 行: `is_update: bool = False` on ToolCreationRequested。dynamic_creator.py 第 398 行在事件 payload 中传递。eventTypes.ts 第 244 行 TS 镜像。 |

#### Plan 02 — 后端 API 层

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 6 | 用户可通过 REST API 启用/禁用动态工具 | VERIFIED | tools.py 第 177-297 行: POST disable/enable 端点。设置 registry 中 enabled 字段，更新 meta.json，发布事件。 |
| 7 | 用户可通过 REST API 删除动态工具（含文件系统清理） | VERIFIED | tools.py 第 300-370 行: POST delete 端点需 confirmation=true。registry.remove() + ToolPersistenceManager.delete() 清理。 |
| 8 | 用户可通过 REST API 查询所有动态工具完整信息（含代码） | VERIFIED | tools.py 第 100-134 行 GET /tools/ 列出摘要。第 137-174 行 GET /tools/{name} 返回完整信息含代码。 |
| 9 | Agent 提交已有工具新版本时，后端自动检测并标记 is_update=true | VERIFIED | dynamic_creator.py 第 125-128 行: Stage 0 `existing_meta = self._registry.get(tool_id)` 检测冲突，设置 is_update 和 old_code。_stage56 原地更新现有 meta。 |
| 10 | Agent 可通过 list_tools 内置工具查询动态工具详细信息 | VERIFIED | dynamic_creator.py 第 753-802 行 create_list_tools_fn。main.py 第 148-150 行注册。__all__ 导出。 |

#### Plan 03 — 前端 UI

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 11 | 用户可通过侧边栏面板查看所有动态工具列表（名称、描述、持久化级别 Badge、启用状态） | VERIFIED | ToolManagementPanel.tsx 第 231-268 行: 工具行渲染名称/语言 Badge/持久化 Badge/Switch。 |
| 12 | 用户点击工具项可展开查看完整代码（Monaco Editor 只读） | VERIFIED | ToolManagementPanel.tsx 第 76-106 行 toggleExpand + 第 279-293 行 Monaco Editor vs-dark 只读。 |
| 13 | 用户可通过 Switch 开关即时启用/禁用工具 | VERIFIED | ToolManagementPanel.tsx 第 110-131 行 handleToggle -> enableTool/disableTool API -> refetch。 |
| 14 | 用户可删除工具（内联二次确认），删除后列表移除 | VERIFIED | ToolManagementPanel.tsx 第 135-157 行 handleDelete + 第 296-340 行内联确认 UI。3 秒自动复位。 |
| 15 | Agent 提交更新版本时，弹窗展示 Monaco DiffEditor（新旧代码 side-by-side） | VERIFIED | ToolCreationDialog.tsx 第 215-234 行: is_update 时 DiffEditor original=old_code, modified=code, renderSideBySide=true。 |
| 16 | 空状态下显示引导提示 | VERIFIED | ToolManagementPanel.tsx 第 221-227 行: "暂无动态工具。当 Agent 在会话中创建工具并经你确认后，它们会出现在这里。" |

---

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `src/loopai/tools/types.py` | ToolMetadata.enabled/code 字段 | VERIFIED | 第 217-218 行: enabled: bool = True, code: str = "" |
| `src/loopai/tools/registry.py` | get_schemas() 过滤 enabled=False | VERIFIED | 第 224 行: dynamic_tools 列表推导含 m.enabled 过滤 |
| `src/loopai/tools/tool_persistence.py` | meta.json enabled 字段 | VERIFIED | 第 336 行: "enabled": extra.get("enabled", True) |
| `src/loopai/tools/dynamic_creator.py` | build_func_ref 静态方法, is_update 检测, create_list_tools_fn | VERIFIED | 第 611-661 行 build_func_ref, 第 125-128 行 is_update 检测, 第 753-802 行 create_list_tools_fn |
| `src/loopai/events/schemas.py` | 4 个新事件类型 + is_update | VERIFIED | 第 449-477 行 ToolDisabled/ToolEnabled/ToolDeleted/ToolUpdated, 第 333 行 is_update |
| `src/loopai/main.py` | 启动加载持久化工具 + list_tools 注册 | VERIFIED | 第 101-135 行 startup loading, 第 148-150 行 list_tools 注册 |
| `src/loopai/api/routes/tools.py` | 5 个工具管理 REST 端点 | VERIFIED | 5 端点在 router 中: GET /tools/, GET /tools/{name}, POST disable/enable/delete |
| `src/loopai/api/schemas.py` | 工具管理请求/响应模型 | VERIFIED | 第 111-155 行: ToolSummary, ToolListResponse, ToolDetailResponse, ToolActionResponse, ToolDeleteRequest |
| `frontend/src/lib/eventTypes.ts` | TS 镜像同步 | VERIFIED | 第 289-311 行 4 个 interface, 第 418-421 行 Event union, 第 461-464 行 EVENT_TYPE_MAP |
| `frontend/src/components/ToolManagementPanel.tsx` | 侧边栏工具管理面板 | VERIFIED | 362 行, 列表+展开+代码+开关+删除 |
| `frontend/src/components/ToolCreationDialog.tsx` | DiffEditor 更新模式 | VERIFIED | 第 16 行导入 DiffEditor, 第 215-234 行 DiffEditor 渲染 |
| `frontend/src/stores/uiStore.ts` | toolPanelOpen 状态 | VERIFIED | 第 34 行 toolPanelOpen: boolean, 第 50 行 setToolPanelOpen setter |
| `frontend/src/lib/api.ts` | 工具管理 API 函数 | VERIFIED | 第 156-202 行: ToolSummary, ToolDetail 接口 + fetchTools/fetchToolDetail/disableTool/enableTool/deleteTool |
| `frontend/src/App.tsx` | Wrench 按钮 + ToolManagementPanel | VERIFIED | 第 3 行 import Wrench, 第 378-385 行 Wrench button, 第 411 行 ToolManagementPanel 渲染 |
| `frontend/src/components/ui/switch.tsx` | Switch 组件 | VERIFIED | @base-ui/react Switch 基于 Radix 的切换组件 |

---

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | --- | --- | ------ | ------- |
| ToolRegistry.get_schemas() | ToolMetadata.enabled | 过滤 enabled=False | WIRED | registry.py 第 224 行: `if m.enabled` 过滤 |
| create_agent_components | ToolPersistenceManager.load_* | 启动时扫描 | WIRED | main.py 第 102-135 行: sandbox + project 循环 |
| schemas.py | eventTypes.ts | 镜像同步 | WIRED | 4 个 TS interface (eventTypes.ts 第 289-311 行) 匹配 Python (schemas.py 第 449-477 行) |
| POST /api/tools/{name}/disable | ToolRegistry._dynamic_tools | 设置 enabled=False + meta.json | WIRED | tools.py 第 207-218 行: 跨会话设置 + _update_persistence_enabled |
| DynamicToolCreator Stage 0 | ToolRegistry._dynamic_tools | 检测 name 冲突 | WIRED | dynamic_creator.py 第 126 行: `self._registry.get(tool_id)` |
| create_list_tools_fn | ToolRegistry.list_dynamic() | 查询动态工具信息 | WIRED | dynamic_creator.py 第 778 行: `registry.list_dynamic()` |
| App.tsx Wrench button | ToolManagementPanel | toggle toolPanelOpen | WIRED | App.tsx 第 381 行: `setToolPanelOpen(!toolPanelOpen)` |
| ToolCreationDialog | Monaco DiffEditor | import { DiffEditor } | WIRED | ToolCreationDialog.tsx 第 16 行: 导入 DiffEditor |
| ToolManagementPanel | api.ts functions | fetch/toggle/delete | WIRED | ToolManagementPanel.tsx 第 48/115/138 行调用 api.ts 函数 |

---

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| -------- | ------------- | ------ | ------------------ | ------ |
| ToolManagementPanel tools list | `tools` (useState) | `fetchTools()` -> GET `/api/tools/` | YES — registry.list_dynamic() from active sessions | FLOWING |
| ToolManagementPanel code display | `toolCodeMap` (useState) | `fetchToolDetail()` -> GET `/api/tools/{name}` | YES — returns meta.code from ToolMetadata | FLOWING |
| ToolManagementPanel Switch toggle | `enabled` on meta | disableTool/enableTool API -> POST disable/enable | YES — sets ToolMetadata.enabled + meta.json | FLOWING |
| ToolManagementPanel delete | - | deleteTool API -> POST delete | YES — registry.remove() + persistence.delete() | FLOWING |
| ToolCreationDialog DiffEditor | `event.old_code` / `event.code` | EventBus event from DynamicToolCreator Stage 3 | YES — is_update detection reads existing meta.code | FLOWING |
| get_schemas() enabled filtering | enabled field | ToolMetadata (registry) | YES — direct field read | FLOWING |

---

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| ToolMetadata enabled/code fields | `python -c "from loopai.tools.types import ToolMetadata; m = ToolMetadata(name='t', description='d'); assert m.enabled == True; assert m.code == ''"` | PASS | PASS |
| get_schemas() filters disabled | `python -c test_script (registry test with disabled/enabled tools)` | All assertions passed | PASS |
| Event union includes 4 new types | `python -c "from loopai.events.schemas import ToolDisabled, ToolEnabled, ToolDeleted, ToolUpdated"` | Import OK | PASS |
| API schemas importable | `python -c "from loopai.api.schemas import ToolSummary, ToolListResponse, ToolDetailResponse, ToolActionResponse, ToolDeleteRequest"` | Import OK | PASS |
| Tools router has >=5 routes | `python -c "from loopai.api.routes.tools import router; assert len(router.routes) >= 5"` | 5 routes | PASS |
| create_list_tools_fn | `python -c test (create function, verify name/list_tools, permission_level/safe)` | All assertions passed | PASS |
| TypeScript compilation | `cd frontend && npx tsc --noEmit` | 0 errors | PASS |
| ToolManagementPanel exists | `ls frontend/src/components/ToolManagementPanel.tsx` | EXISTS (362 lines >= 200) | PASS |

---

### Probe Execution

Step 7c: SKIPPED (Phase 10 does not declare probes and is not a migration/tooling phase.)

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ---------- | ----------- | ------ | -------- |
| DYN-15 | 10-01, 10-03 | 前端侧边栏"动态工具"tab 列出所有动态工具 | VERIFIED | ToolManagementPanel 列表渲染名称/描述/Badge/状态 |
| DYN-16 | 10-03 | 点击工具项查看完整代码（Monaco Editor 只读） | VERIFIED | ToolManagementPanel.tsx 第 279-293 行 Monaco Editor |
| DYN-17 | 10-01, 10-02, 10-03 | 禁用/启用动态工具——禁用工具不出现在 system prompt 且不可调用 | WARNING | get_schemas() 正确过滤（不可调用），但 system prompt "动态工具"段落仍列出禁用工具 |
| DYN-18 | 10-02, 10-03 | 删除动态工具（含确认弹窗），根据持久化级别清理存储 | VERIFIED | 内联确认+POST delete+ToolPersistenceManager.delete |
| DYN-19 | 10-02 | Agent 通过 generate_tool 提交已有工具的更新版本 | VERIFIED | Stage 0 is_update detection |
| DYN-20 | 10-02, 10-03 | 更新时前端 Monaco DiffEditor（新旧代码 side-by-side） | VERIFIED | ToolCreationDialog.tsx 第 215-234 行 DiffEditor |
| DYN-21 | 10-02, 10-03 | 命名冲突时展示新旧代码对比 | VERIFIED | 同 DYN-19/DYN-20 的 is_update 路径 |
| DYN-22 | 10-01 | 启动时扫描所有持久化动态工具并注入 system prompt | VERIFIED | main.py 101-135 行启动加载 + prompt_builder 注入 |
| DYN-23 | 10-02 | list_tools 内置工具查询动态工具详细信息 | VERIFIED | create_list_tools_fn + main.py 注册 |

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| *None* | - | - | - | No TBD/FIXME/XXX markers, no stub implementations, no console.log stubs found in modified files. |

---

### Gaps Summary

**One gap found:**

**DYN-17 — 禁用工具仍出现在 system prompt 的 "## 动态工具" 信息段落中**

The `prompt_builder.py` builds the system prompt from two sources:
1. `registry.get_schemas()` (line 32) — correctly filters out disabled tools ("## 可用工具" section). LLM function calling is properly restricted.
2. `registry.list_all()` (line 59) — lists ALL dynamic tools including disabled ones ("## 动态工具" informational section). Disabled tools still appear here.

**Root cause:** The plan explicitly chose not to modify `prompt_builder.py` (Plan 01, Task 1 action item: "Do NOT modify prompt_builder.py"). The `list_all()` call at line 59 was not updated to filter by `enabled` status.

**Impact:** Low. Disabled tools cannot be called by the Agent (get_schemas() controls function calling eligibility). The mention in the informational "## 动态工具" section is descriptive only.

**Fix:** Either:
- Option A (clean): Add `enabled=True` filter to line 59: `[m for m in registry.list_all() if m.is_dynamic and m.enabled]`
- Option B (conservative): Use get_schemas()-derived tool names to cross-reference for the dynamic tools section

---

### Human Verification Required

No items require human verification. All must-haves are verifiable through code analysis and automated checks.

---

### Artifact Status Summary

| Artifact | Exists | Substantive | Wired | Data Flows | Overall |
| -------- | ------ | ----------- | ----- | ---------- | ------- |
| `src/loopai/tools/types.py` | ✓ | ✓ | ✓ | ✓ | VERIFIED |
| `src/loopai/tools/registry.py` | ✓ | ✓ | ✓ | ✓ | VERIFIED |
| `src/loopai/tools/tool_persistence.py` | ✓ | ✓ | ✓ | ✓ | VERIFIED |
| `src/loopai/tools/dynamic_creator.py` | ✓ | ✓ | ✓ | ✓ | VERIFIED |
| `src/loopai/events/schemas.py` | ✓ | ✓ | ✓ | ✓ | VERIFIED |
| `src/loopai/main.py` | ✓ | ✓ | ✓ | ✓ | VERIFIED |
| `src/loopai/api/routes/tools.py` | ✓ | ✓ | ✓ | ✓ | VERIFIED |
| `src/loopai/api/schemas.py` | ✓ | ✓ | ✓ | ✓ | VERIFIED |
| `frontend/src/lib/eventTypes.ts` | ✓ | ✓ | ✓ | ✓ | VERIFIED |
| `frontend/src/components/ToolManagementPanel.tsx` | ✓ | ✓ | ✓ | ✓ | VERIFIED |
| `frontend/src/components/ToolCreationDialog.tsx` | ✓ | ✓ | ✓ | ✓ | VERIFIED |
| `frontend/src/stores/uiStore.ts` | ✓ | ✓ | ✓ | ✓ | VERIFIED |
| `frontend/src/lib/api.ts` | ✓ | ✓ | ✓ | ✓ | VERIFIED |
| `frontend/src/App.tsx` | ✓ | ✓ | ✓ | ✓ | VERIFIED |

---

_Verified: 2026-06-02T11:00:00Z_
_Verifier: Claude (gsd-verifier)_
