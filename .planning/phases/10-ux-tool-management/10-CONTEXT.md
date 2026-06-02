# Phase 10: 用户体验与工具管理 - Context

**Gathered:** 2026-06-02
**Status:** Ready for planning

## Phase Boundary

本阶段将 Phase 8/9 的动态工具基础设施包装为用户可操作的管理界面。交付：工具管理侧边栏面板（列表+展开代码查看）、启用/禁用开关（持久化到 meta.json）、删除确认（内联二次确认）、工具更新 DiffEditor 流程、启动时自动加载持久化工具、list_tools 内置工具。不改动 DynamicToolCreator 管道和 SandboxExecutor 安全边界。

## Implementation Decisions

### 面板布局
- **D-01:** 工具管理面板使用侧边栏 Tab 模式——Header 增加 Wrench 图标按钮，点击后左侧滑出覆盖层（与 SessionList 一致交互）。面板内为列表+展开模式：主视图为工具列表（名称+描述+持久化级别+状态 Badge），点击工具项后内嵌展开 Monaco Editor 只读代码查看，展开区域内含 Switch 开关和删除按钮。
- **D-02:** 空状态显示引导提示："暂无动态工具。当 Agent 在会话中创建工具并经你确认后，它们会出现在这里。"不显示操作按钮。

### 工具禁用/启用机制
- **D-03:** 禁用状态存储在 `ToolMetadata.enabled: bool = True` 字段上。`ToolRegistry.get_schemas()` 自动过滤 `enabled=False` 的工具。system prompt 生成也因此自动排除禁用工具。
- **D-04:** 禁用状态跨重启持久化——`ToolPersistenceManager` 在 `meta.json` 中读写 `enabled` 字段。沙箱级和项目级工具的禁用状态在重启后保持。会话级工具重启后本来就不存在。
- **D-05:** 禁用 API 使用独立端点：`POST /api/tools/{tool_name}/disable` 和 `POST /api/tools/{tool_name}/enable`。端点更新 ToolMetadata 并写回 meta.json（如适用）。
- **D-06:** 禁用工具不影响已在运行中的会话——只对新启动的会话生效。已运行会话已将工具注入 system prompt，中途移除可能造成 LLM 混乱。
- **D-07:** 前端 Switch 开关交互——每个工具行右侧 Toggle Switch，即时切换并调用 disable/enable API。

### 工具更新流程
- **D-08:** 后端同名自动检测更新——`generate_tool` 提交时，若 tool_name 已存在于 ToolRegistry 动态分区，自动标记为更新。事件中增加 `is_update: bool` 字段，前端据此切换 UI。
- **D-09:** 扩展 ToolCreationDialog 增加 update 模式（不复用其他组件，不新建独立组件）。update 模式下：标题改为"更新工具"、代码区变为 Monaco DiffEditor（original vs modified side-by-side）、隐藏持久化级别选择（更新不改级别）、自测代码区域保留。
- **D-10:** DiffEditor 仅在更新时显示。新建工具使用 Monaco Editor 只读模式展示代码。
- **D-11:** 用户拒绝更新后，返回 `tool_creation_rejected` 事件 + 拒绝原因，Agent 可修改代码重新提交（改名或改进）。与创建拒绝行为一致。

### 删除确认方式
- **D-12:** 内联二次确认——点击删除按钮后按钮变为"确认删除？"+ "是" / "否"两个小按钮。3 秒内不操作自动恢复为删除按钮。后端调用 `ToolRegistry.remove()` + `ToolPersistenceManager.delete()` 完成清理。
- **D-13:** 删除不可撤销。删除成功后显示简短提示"已删除 {tool_name}，不可撤销"。
- **D-14:** 删除确认展示工具名+持久化级别（如"删除 dynamic.a1b2c3d4_disk_check（沙箱级）？"），不展示完整代码（展开面板已有代码查看）。

### Claude's Discretion
无。全部决策由用户确认。

## Canonical References

### 项目文档
- `.planning/PROJECT.md` — 项目概述、核心价值、v1.1 里程碑目标
- `.planning/REQUIREMENTS.md` — v1.1 DYN-15~DYN-23 需求定义
- `.planning/ROADMAP.md` — 阶段 10 详细定义和成功标准

### 上游阶段 Context
- `.planning/phases/08-dynamic-tool-core/08-CONTEXT.md` — Phase 8 决策（ToolCreationDialog 设计、命名空间、持久化路径、创建管道流程）
- `.planning/phases/09-security-hardening/09-CONTEXT.md` — Phase 9 决策（加固沙箱、审计事件类型、资源限制）

### 现有代码（关键集成点）
- `src/loopai/tools/registry.py` — ToolRegistry（list_dynamic / remove / register_meta / get_schemas，需扩展 enabled 过滤）
- `src/loopai/tools/tool_persistence.py` — ToolPersistenceManager（load_sandbox_tools / load_project_tools / delete / save，需扩展 enabled 读写）
- `src/loopai/tools/prompt_builder.py` — build_system_prompt()（已将动态工具注入 system prompt，需过滤 disabled）
- `src/loopai/tools/dynamic_creator.py` — DynamicToolCreator（generate_tool 管道，需增加同名检测→更新标记）
- `src/loopai/api/routes/control.py` — 现有端点模式（/confirm、/confirm-tool-creation，需新增 disable/enable/delete/list 端点）
- `src/loopai/events/schemas.py` — EventBus 事件类型（需新增 tool_updated、tool_deleted 等事件）
- `frontend/src/App.tsx` — Header 布局（需增加工具面板按钮 + 侧边栏容器）
- `frontend/src/components/ToolCreationDialog.tsx` — 创建弹窗（需扩展 update 模式 + DiffEditor）
- `frontend/src/components/ToolDetail.tsx` — 工具调用结果详情面板（参考但本阶段新建 ToolManagementPanel 组件）
- `frontend/src/stores/uiStore.ts` — UI 状态管理（需新增 toolPanelOpen 等状态）
- `frontend/src/lib/eventTypes.ts` — TypeScript 事件类型（需同步新增）

## Existing Code Insights

### Reusable Assets
- **SessionList 侧边栏模式** — 左侧滑出覆盖层 + 背景遮罩 + 点击外部关闭。工具管理面板完全复用此交互模式
- **Monaco Editor** — `@monaco-editor/react` 已安装，ToolCreationDialog 已使用 Editor 组件（只读模式）。DiffEditor 组件同包可用
- **ToolCreationDialog 7 区布局** — 代码区、风险标记、自测区、持久化选择等分区结构可复用，update 模式选择性显示/隐藏区域
- **shadcn/ui 组件** — Dialog、Badge、Button、ScrollArea、Separator、Tabs 已安装，面板构建无需新增依赖（Switch 除外，需 `@radix-ui/react-switch`）
- **Zustand uiStore** — pendingConfirmation/pendingToolCreation 状态管理模式，新增 toolPanelOpen 遵循相同模式

### Established Patterns
- **管道式确认** — EventBus 事件 → 前端弹窗 → 用户操作 → API 端点 → 恢复执行。工具管理操作（disable/enable/delete）不走 EventBus——它们是直接 REST 调用，不需要暂停 Agent 循环
- **组件独立原则（Phase 8 D-03）** — 新功能新建独立组件，不扩展已有组件。但 ToolCreationDialog 是此规则的例外——update 模式是其功能的自然扩展，不是强行复用
- **追加式事件流** — 工具管理操作产生的事件（tool_disabled、tool_deleted 等）通过 EventBus 发布写入 JSONL，但不阻塞 Agent 循环

### Integration Points
- **ToolRegistry.get_schemas()** — 需增加 `enabled` 过滤，这是 system prompt 和 LLM function calling 的唯一入口点
- **DynamicToolCreator 管道** — Stage 1（语法检查）需增加同名检测逻辑，决定走 create 还是 update 分支
- **App.tsx Header** — 需增加 Wrench 按钮 + ToolManagementPanel 侧边栏组件
- **FastAPI 路由** — 需在 control.py 或新建 tools.py 路由中增加 disable/enable/delete/list 端点

## Specific Ideas

- 工具管理面板和 Agent 会话互不干扰——用户在会话进行中可以随时打开面板查看/管理工具，不影响 Agent 运行
- 列表项关键信息：工具名（`dynamic.xxx`）、描述（一行截断）、持久化 Badge（会话/沙箱/项目）、状态 Badge（启用/禁用）
- DiffEditor 在更新确认弹窗中 side-by-side 展示：左侧 original（只读，灰色背景）、右侧 modified（语法高亮）
- 删除按钮在展开区域底部，远离 Switch 开关（防止误触）
- Switch 组件使用 `@radix-ui/react-switch`（shadcn/ui 生态），或直接用 Tailwind CSS 手写 toggle（避免新增依赖）

## Deferred Ideas

无。讨论保持在阶段范围内。

---

*Phase: 10-ux-tool-management*
*Context gathered: 2026-06-02*
