---
status: testing
phase: 10-ux-tool-management
source:
  - .planning/phases/10-ux-tool-management/10-01-SUMMARY.md
  - .planning/phases/10-ux-tool-management/10-02-SUMMARY.md
  - .planning/phases/10-ux-tool-management/10-03-SUMMARY.md
started: 2026-06-02T10:50:00Z
updated: 2026-06-02T10:50:00Z
---

## Current Test

number: 1
name: 工具管理侧边栏面板
expected: |
  启动应用后，Header 栏出现 Wrench 图标按钮（在 History 按钮旁）。
  点击 Wrench 按钮，左侧滑出工具管理面板（覆盖层 + 遮罩）。
  面板内显示动态工具列表，每行包含工具名称、语言 Badge（Python/Bash）、持久化级别 Badge（会话/沙箱/项目）、Switch 启用/禁用开关。
  点击遮罩或 X 按钮可关闭面板。
awaiting: user response

## Tests

### 1. 工具管理侧边栏面板
expected: |
  启动应用后，Header 栏出现 Wrench 图标按钮（在 History 按钮旁）。
  点击 Wrench 按钮，左侧滑出工具管理面板（覆盖层 + 遮罩）。
  面板内显示动态工具列表，每行包含工具名称、语言 Badge（Python/Bash）、持久化级别 Badge（会话/沙箱/项目）、Switch 启用/禁用开关。
  点击遮罩或 X 按钮可关闭面板。
result: [pending]

### 2. 工具代码查看（Monaco Editor）
expected: |
  点击工具列表中的某个工具项，面板内嵌展开 Monaco Editor 只读视图，显示该工具的完整 Python/Bash 代码（语法高亮，vs-dark 主题）。
result: [pending]

### 3. 启用/禁用开关
expected: |
  在工具列表中点击某个工具的 Switch 开关，开关立即切换状态。
  禁用工具后，该工具从 LLM 可调用工具列表中移除（system prompt 中不再列出）。
  刷新页面后禁用状态保持（沙箱级/项目级工具）。
result: [pending]

### 4. 删除工具 + 内联确认
expected: |
  在展开的工具详情区域底部点击删除按钮，按钮变为"确认删除 {tool_name}（{持久化级别}级）？" + "是" / "否"两个按钮。
  点击"是"，工具被删除，显示"已删除 {tool_name}，不可撤销"提示。
  3 秒内不操作自动恢复为删除按钮。
result: [pending]

### 5. 空状态提示
expected: |
  当没有任何动态工具时，面板显示引导提示："暂无动态工具。当 Agent 在会话中创建工具并经你确认后，它们会出现在这里。"
result: [pending]

### 6. 工具列表 REST API
expected: |
  GET /api/tools/ 返回所有动态工具列表，每个工具包含名称、描述、持久化级别、enabled 状态。
  GET /api/tools/{tool_name} 返回工具详情（含完整代码）。
result: [pending]

### 7. 禁用/启用 REST API
expected: |
  POST /api/tools/{tool_name}/disable 返回 200，工具 enabled 变为 false。
  POST /api/tools/{tool_name}/enable 返回 200，工具 enabled 变为 true。
result: [pending]

### 8. 删除 REST API
expected: |
  DELETE /api/tools/{tool_name} 返回 200，工具从 ToolRegistry 和持久化存储中移除。
  删除会话级工具：仅从内存移除。
  删除沙箱级工具：从内存移除 + 删除 .sandbox/tools/ 下文件。
  删除项目级工具：从内存移除 + 删除 src/loopai/tools/dynamic/ 下文件。
result: [pending]

### 9. 工具更新 DiffEditor
expected: |
  Agent 提交已有工具的新版本时，ToolCreationDialog 弹窗标题显示 "Update Tool"。
  代码区使用 Monaco DiffEditor side-by-side 展示：左侧 original（只读、灰色背景）、右侧 modified（语法高亮）。
  持久化级别选择区域隐藏（更新不改级别）。
result: [pending]

### 10. 启动自动加载持久化工具
expected: |
  重启后端服务后，沙箱级和项目级动态工具自动出现在 ToolRegistry 中。
  工具名称和描述注入 system prompt（通过 list_tools 可验证）。
result: [pending]

### 11. list_tools 内置工具
expected: |
  Agent 可通过调用 list_tools 内置工具查询所有可用动态工具的详细信息（含名称、描述、完整 Schema）。
  list_tools 是只读操作，PermissionLevel.SAFE，无需用户确认。
result: [pending]

## Summary

total: 11
passed: 0
issues: 0
pending: 11
skipped: 0

## Gaps

[none yet]
