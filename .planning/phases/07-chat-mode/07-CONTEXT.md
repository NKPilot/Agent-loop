# Phase 7: Chat 模式 - Context

**Gathered:** 2026-05-30
**Status:** Ready for planning

## Phase Boundary

将 loopAI 从"给任务→跑完→看结果"的任务模式改造为对话式 Chat 模式。用户通过底部输入框发送消息，Agent 响应（含工具调用），对话可持续多轮。前端从三面板+Start Agent 表单变为聊天界面——消息气泡流 + 可展开的工具调用卡片。

后端核心变更：Session 不再是一次性的——Agent 完成一轮响应后保持 FINISH_WAIT 状态，等待下一条用户消息后重新进入 REASON。

## Implementation Decisions

### 会话模型
- **D-01:** 会话从"一次性"变为"持续对话"。一轮 = 用户消息 → Agent 响应（可能多步工具调用）→ 完成。一轮结束后 Session 保持活跃，等待下一条用户消息。
- **D-02:** FSM 新增 FINISH_WAIT 状态。当前轮完成后进入 FINISH_WAIT，收到新用户消息后回到 REASON。
- **D-03:** 前后端通过 SSE 保持长连接，新用户消息通过 REST API 发送。Session 生命周期由前端控制（关闭页面 = 结束会话）。

### 前端 Chat UI
- **D-04:** 纯对话式布局：顶部标题栏 + 中间消息流 + 底部输入框。去掉三面板布局和 Start Agent 表单。
- **D-05:** 消息气泡：用户消息（右对齐）+ Agent 消息（左对齐，含可展开的思考步骤和工具调用卡片）。
- **D-06:** 保留现有功能：Markdown 渲染、表格、确认弹窗、Token 追踪。以更轻量的方式嵌入气泡中。

### Claude's Discretion
- 消息气泡的具体 UI 设计
- 历史会话列表的展示方式
- 确认弹窗在 Chat 模式下的交互
- 现有三面板代码的保留/废弃策略

## Canonical References

### 已有接口
- `src/loopai/api/routes/control.py` — 会话启动和确认接口
- `src/loopai/api/routes/stream.py` — SSE 流端点
- `src/loopai/state_machine/fsm.py` — ReActFSM（需加 FINISH_WAIT）
- `frontend/src/App.tsx` — 当前布局（需重构为 Chat）

## Existing Code Insights

### Reusable
- SSE 流 + EventBus 完全复用
- StepCard / ToolDetail / ConfirmationDialog 组件可嵌入气泡
- API 路由基本复用，只需加一个 send_message 端点

### Changes Needed
- FSM 新增 FINISH_WAIT 状态
- Session 支持追加用户消息
- API 新增 POST /api/sessions/{id}/messages
- 前端布局重构

## Deferred Ideas

- 多会话同时聊天（Tab 切换）— Phase 8
- 会话搜索 — Phase 8
- 暗色模式 — v3

---
*Phase: 7-Chat 模式*
*Context gathered: 2026-05-30*
