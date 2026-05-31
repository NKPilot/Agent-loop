# Phase 8: 动态工具创建核心 (MVP) - Context

**Gathered:** 2026-05-31
**Status:** Ready for planning

## Phase Boundary

本阶段交付动态工具创建的完整最小闭环：Agent 通过 `generate_tool` 内置工具提交代码 → 语法检查（串行：ast.parse/bash -n → 危险扫描）→ 前端 ToolCreationDialog 确认弹窗 → Agent 自测在沙箱执行 → 三级持久化注册到 ToolRegistry。后续阶段在此基础上叠加安全加固（Phase 9）、UX 管理面板（Phase 10）、端到端验证（Phase 11）。

## Implementation Decisions

### generate_tool 工具参数
- **D-01:** Agent 调用 `generate_tool` 时传完整参数：`name`（工具名）、`description`（描述）、`code`（Python/Bash 代码）、`test_code`（测试用例代码）、`language`（"python"|"bash"）。系统验证后使用 Agent 提供的名称和描述。
- **D-02:** Agent 显式提供 JSON Schema（`param_schema` 字段），系统验证格式后直接使用。不做代码自动提取类型提示。

### 前端确认弹窗
- **D-03:** 新建独立的 `ToolCreationDialog` 组件，不复用/不扩展现有 `ConfirmationDialog`。功能差异大——需要代码展示（Monaco Editor 语法高亮）、持久化级别选择、目录权限配置。
- **D-04:** 确认弹窗无超时，一直等待用户操作。Agent 处于 WAITING 状态直到用户响应。

### 工具自测机制
- **D-05:** 流程：语法检查 → 危险扫描 → 前端确认弹窗（用户看到代码+风险标记+自测代码）→ 用户确认后在沙箱中执行 Agent 提供的测试用例 → 测试结果（通过/失败/输出）展示 → 测试通过则注册工具。

### 持久化时机
- **D-06:** 分级别处理：确认后工具立即注册到内存（ToolRegistry）。会话级永远留在内存。沙箱级和项目级在工具**首次执行成功**后才写入文件系统。
- **D-07:** 持久化路径：沙箱级 `.sandbox/tools/{tool_name}/`，项目级 `src/loopai/tools/dynamic/{tool_name}.py`。

### 语法检查与安全扫描
- **D-08:** 串行执行：先 `ast.parse()`（Python）或 `bash -n`（Bash）语法检查 → 通过后才执行危险模块/命令扫描 → 两项都通过才发布 `tool_creation_requested` 事件。任一失败返回结构化错误给 Agent。

### 动态工具命名空间
- **D-09:** 动态工具以 `dynamic.{name}` 命名空间注册到 ToolRegistry，与静态工具（`bash.*`、`disk.*`）隔离。使用 `ToolRegistry.register_meta()` 直接注册（复用 Phase 6 AgentTool 模式）。

### Claude's Discretion
无。全部决策由用户确认。

### Folded Todos
无匹配的待办事项。

## Canonical References

### 项目文档
- `.planning/PROJECT.md` — 项目概述、核心价值、约束
- `.planning/REQUIREMENTS.md` — v1.1 DYN 需求定义（DYN-01~DYN-10, DYN-24~DYN-26）
- `.planning/ROADMAP.md` — 阶段 8 详细定义和成功标准

### 研究参考
- `.planning/research/ARCHITECTURE.md` — DynamicToolCreator 管道架构、集成点映射
- `.planning/research/STACK.md` — 零新增 PyPI 依赖方案、Monaco Editor 选择
- `.planning/research/PITFALLS.md` — 8 个关键陷阱和防护策略

### 现有代码
- `src/loopai/tools/registry.py` — ToolRegistry.register_meta()（集成点）
- `src/loopai/tools/types.py` — ToolMetadata 模型（需扩展 is_dynamic 字段）
- `src/loopai/events/schemas.py` — 现有事件 Schema（需新增 tool_creation_* 事件）
- `src/loopai/api/routes/control.py` — /confirm 端点模式（需新增 /confirm-tool-creation）
- `frontend/src/stores/uiStore.ts` — pendingConfirmation 模式（需新增 pendingToolCreation）
- `frontend/src/components/ConfirmationDialog.tsx` — 确认弹窗参考（ToolCreationDialog 独立实现）

## Existing Code Insights

### Reusable Assets
- **ToolRegistry.register_meta()** — 直接接受 ToolMetadata 实例注册，动态工具不需要经过 @tool 装饰器
- **ConfirmationRequiredEvent 模式** — EventBus 暂停 + asyncio.Event 等待 + uiStore 状态管理，可复制此模式
- **ToolMetadata 模型** — 已有 name、description、permission_level、timeout、retry、tags、param_schema、func_ref，需要增加 is_dynamic 标记
- **control.py /confirm 端点** — APIRouter + Request 模式可直接复用

### Established Patterns
- **管道式确认** — PermissionGuard 发布事件 → EventBus → 前端弹窗 → 用户操作 → /confirm 端点 → 恢复执行
- **Zustand store** — uiStore 管理 pendingConfirmation 状态，可增加 pendingToolCreation
- **Monaco Editor** — Phase 10 会引入 `@monaco-editor/react`，Phase 8 首次使用 Editor（只读模式）

### Integration Points
- **ToolExecutor** — 需要新增对 `generate_tool` 工具类型的路由（它不走正常的工具执行管线，而是进入 DynamicToolCreator 管道）
- **EventBus schemas** — 新增 `tool_creation_requested`、`tool_creation_confirmed`、`tool_creation_rejected`、`tool_created` 事件
- **create_agent_components()** — 需要在工厂函数中注册 generate_tool 和 DynamicToolCreator

## Specific Ideas

- 确认弹窗展示内容：代码（Monaco Editor 只读、语法高亮）、危险模块标记（红色 Badge 列表）、自测代码预览、持久化级别选择器、目录权限输入框
- 工具首次执行成功后才写文件——这样工具代码经过真实执行验证，不会留下"死代码"
- Agent 自测代码和执行结果都要展示给用户，让用户基于完整信息做决策

## Deferred Ideas

无。讨论保持在阶段范围内。

---

*Phase: 8-dynamic-tool-core*
*Context gathered: 2026-05-31*
