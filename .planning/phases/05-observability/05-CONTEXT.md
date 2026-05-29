# Phase 5: 可观测性与 Web 前端 - Context

**Gathered:** 2026-05-28
**Status:** Ready for planning

## Phase Boundary

本阶段交付 loopAI 的 Web 可观测性前端：FastAPI SSE 实时推流端点、React 19 三面板 Dashboard（会话列表 + Agent 时间线 + 工具调用详情）、会话历史浏览、Token/成本追踪、以及完整的磁盘清理交互演示。这是 loopAI 的旗舰差异点——目前没有开源 agent 框架自带自托管可观测性面板。

## Implementation Decisions

### 前端架构
- **D-01:** 三面板布局。左侧会话列表（历史+当前），中间 Agent 思考/行动时间线（实时 SSE 驱动），右侧工具调用详情卡片（参数、结果、耗时）。
- **D-02:** 技术栈：React 19 + TypeScript 5.7 + Vite 8 + Tailwind CSS 4.3 + shadcn/ui (CLI v4) + @tanstack/react-query 5 + Zustand 5 + recharts + lucide-react。

### SSE 流
- **D-03:** 单端点 `/api/sessions/{id}/stream`，所有事件类型走同一个 SSE 连接，前端按 `event_type` 分发到对应渲染组件。
- **D-04:** SSE 连接管理：自动重连（指数退避，最大 30s），断线期间显示"重连中"状态。

### 前端范围
- **D-05:** 全功能交付——实时监控 + 会话历史浏览 + Token/成本追踪 + 磁盘清理完整交互演示。覆盖 OBS-01 到 OBS-05 及 BIZ-02。
- **D-06:** 危险操作确认弹窗集成到前端，用户在 Dashboard 中点击批准/拒绝。

### Claude's Discretion
- 具体 UI 组件选型和组合
- shadcn/ui 组件选择（Card、Dialog、Badge、Tooltip 等）
- recharts 图表类型选择
- 色彩方案和视觉风格
- Vite 代理配置

## Canonical References

### 项目定义
- `.planning/PROJECT.md` — 核心价值、技术栈
- `.planning/REQUIREMENTS.md` — OBS-01 至 OBS-05, BIZ-02
- `.planning/ROADMAP.md` — 阶段 5 成功标准
- `CLAUDE.md` — 技术栈和 What NOT to Use

### 已有后端接口
- `src/loopai/events/bus.py` — EventBus（前端消费源）
- `src/loopai/events/schemas.py` — 15 个事件类型（前端渲染依据）
- `src/loopai/consumers/cli_renderer.py` — CLI 渲染器（前端参考）
- `src/loopai/consumers/jsonl_logger.py` — JSONL 日志（会话历史数据源）

## Existing Code Insights

### Reusable Assets
- **EventBus** — 前端直接消费 EventBus 事件，通过 SSE 端口暴露
- **JSONL 日志** — 会话历史浏览的数据源
- **PermissionGuard** — 确认机制需从 CLI 扩展到 Web

### Integration Points
- **FastAPI 后端** — 新增 SSE 端点 + 静态文件服务
- **Vite 前端** — `frontend/` 目录
- **EventBus → SSE bridge** — 新增 SSE 消费者

## Deferred Ideas

- 会话回放（step-forward/backward）— Phase 6
- 多用户支持 — v2
- 暗色模式切换 — Phase 6

---

*Phase: 5-可观测性与 Web 前端*
*Context gathered: 2026-05-28*
