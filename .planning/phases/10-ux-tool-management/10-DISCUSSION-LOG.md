# Phase 10: 用户体验与工具管理 - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-02
**Phase:** 10-ux-tool-management
**Areas discussed:** 面板布局, 工具禁用/启用机制, 工具更新流程, 删除确认方式

---

## 面板布局

| Option | Description | Selected |
|--------|-------------|----------|
| 侧边栏 Tab | Header 旁加按钮，左侧滑出面板（和 SessionList 同样式），面板内用列表+展开模式 | ✓ |
| 右侧面板 | 复用 ToolDetail 的右侧面板位置 | |
| 独立 Dialog | 弹出大 Dialog/Modal 内含工具列表 | |

| Option | Description | Selected |
|--------|-------------|----------|
| 列表+展开 | 主视图是工具列表，点击展开内嵌代码查看（Monaco Editor 只读） | ✓ |
| 列表+详情切换 | 列表→点击→面板切换为详情视图 | |
| Tab 分页 | 面板内 Tabs："工具列表"/"代码查看" | |

| Option | Description | Selected |
|--------|-------------|----------|
| 引导提示 | 居中简短说明动态工具的用途和出现时机 | ✓ |
| 空列表+创建入口 | 空列表+"创建工具"按钮 | |
| 纯空白 | 简单显示"暂无工具" | |

| Option | Description | Selected |
|--------|-------------|----------|
| Header 按钮 | Header 栏 History 按钮旁加 Wrench 图标按钮 | ✓ |
| Header 文字链接 | "loopAI"旁加文字链接"工具" | |
| 自动显示 | 有动态工具时自动显示 tab | |

**User's choice:** 侧边栏 Tab + 列表展开 + 引导提示空状态 + Header 按钮入口
**Notes:** 和 SessionList 保持交互一致性

---

## 工具禁用/启用机制

| Option | Description | Selected |
|--------|-------------|----------|
| ToolMetadata 字段 | 在 ToolMetadata 上新增 `enabled: bool = True` 字段 | ✓ |
| ToolRegistry 独立集合 | 维护 `_disabled_tools: set[str]` | |
| 持久化标记 | 写入 meta.json 的 enabled 字段 | |

| Option | Description | Selected |
|--------|-------------|----------|
| 是，写入 meta.json | 禁用/启用操作写入对应持久化级别的 meta.json | ✓ |
| 否，仅内存 | 重启后恢复启用 | |

| Option | Description | Selected |
|--------|-------------|----------|
| 独立端点 | `POST /api/tools/{name}/disable` 和 `/enable` | ✓ |
| 统一更新端点 | `PATCH /api/tools/{name}` | |
| 前端直管 | 不做后端 API | |

| Option | Description | Selected |
|--------|-------------|----------|
| 不影响运行中会话 | 只对新启动的会话生效 | ✓ |
| 立即全局生效 | 所有会话中立即可用 | |

| Option | Description | Selected |
|--------|-------------|----------|
| Switch 开关 | 每个工具行右侧 Toggle Switch | ✓ |
| 按钮切换 | "启用"/"禁用"文字按钮 | |
| Badge + 菜单 | 状态 Badge 点击弹出下拉菜单 | |

**User's choice:** ToolMetadata 字段 + meta.json 持久化 + 独立 API 端点 + 不影响运行中会话 + Switch 开关
**Notes:** 需要新增 `@radix-ui/react-switch` 或手写 toggle

---

## 工具更新流程

| Option | Description | Selected |
|--------|-------------|----------|
| 同名自动检测 | generate_tool 提交时，tool_name 已存在→自动走更新路径 | ✓ |
| Agent 显式声明 | generate_tool 增加 action 参数 | |
| 前后端都检测 | 两端都有判断逻辑 | |

| Option | Description | Selected |
|--------|-------------|----------|
| 扩展 ToolCreationDialog | 增加 update 模式：DiffEditor、隐藏持久化选择 | ✓ |
| 新建 UpdateToolDialog | 独立组件只处理更新 | |

| Option | Description | Selected |
|--------|-------------|----------|
| 仅更新时显示 DiffEditor | 新建用 Monaco Editor 只读，更新用 DiffEditor side-by-side | ✓ |
| 新建也显示 Diff | "空→新代码"的 diff | |

| Option | Description | Selected |
|--------|-------------|----------|
| 结构化错误，可重试 | tool_creation_rejected 事件 + 拒绝原因，Agent 可修改重试 | ✓ |
| 直接关闭 | 拒绝后关闭弹窗，不通知 Agent | |

**User's choice:** 同名自动检测 + 扩展 ToolCreationDialog + 仅更新时 DiffEditor + 结构化拒绝可重试
**Notes:** 与 Phase 8 D-03 精神一致——扩展而非新建组件

---

## 删除确认方式

| Option | Description | Selected |
|--------|-------------|----------|
| 内联二次确认 | 点击删除→按钮变为"确认删除？"+ 是/否，3秒自动恢复 | ✓ |
| AlertDialog 弹窗 | shadcn/ui AlertDialog 正式确认 | |
| 无确认，直接删 | 点击即删 | |

| Option | Description | Selected |
|--------|-------------|----------|
| 不可撤销 | 删除后提示"已删除，不可撤销" | ✓ |
| 软删除 | 标记 deleted，30秒内可撤销 | |

| Option | Description | Selected |
|--------|-------------|----------|
| 工具名+持久化级别 | "删除 dynamic.xxx（沙箱级）？" | ✓ |
| 工具名+描述+代码预览 | 展开代码预览再次确认 | |
| 仅工具名 | "删除 dynamic.xxx？" | |

**User's choice:** 内联二次确认 + 不可撤销 + 展示工具名+持久化级别
**Notes:** 后端 ToolRegistry.remove() + ToolPersistenceManager.delete() 已就绪

---

## Claude's Discretion

无。全部决策由用户确认。

## Deferred Ideas

无。
