---
phase: "05"
phase_slug: observability
created: "2026-05-29"
nyquist_version: "1.0"
---

## 验证架构

### 测试框架
| 属性 | 值 |
|------|-----|
| 框架 | pytest 9.0.3 + pytest-asyncio 1.4.0（后端）/ vitest（前端，Vite 内置） |
| 配置文件 | pyproject.toml（后端 pytest 配置）/ vitest.config.ts（前端，Wave 0 创建） |
| 快速运行 | `pytest tests/api/ -x -q`（后端）/ `pnpm --dir frontend test --run`（前端） |
| 完整套件 | `pytest tests/ -x -q`（后端）/ `pnpm --dir frontend test`（前端） |

### 需求 → 测试映射
| Req ID | 行为 | 测试类型 | 自动化命令 | 文件存在? |
|--------|------|----------|-----------|----------|
| OBS-02 | SSE 端点流式推送会话事件 | integration | `pytest tests/api/test_sse.py::test_stream_events -x` | 否 — Wave 0 |
| OBS-02 | SSE 端点按 session_id 过滤 | integration | `pytest tests/api/test_sse.py::test_stream_session_filter -x` | 否 — Wave 0 |
| OBS-02 | SSE 端点处理客户端断开 | integration | `pytest tests/api/test_sse.py::test_stream_disconnect -x` | 否 — Wave 0 |
| OBS-05 | GET /api/sessions 返回会话列表 | integration | `pytest tests/api/test_sessions.py::test_list_sessions -x` | 否 — Wave 0 |
| OBS-05 | GET /api/sessions/{id} 返回事件列表 | integration | `pytest tests/api/test_sessions.py::test_get_session -x` | 否 — Wave 0 |
| OBS-05 | DELETE /api/sessions/{id} 删除会话 | integration | `pytest tests/api/test_sessions.py::test_delete_session -x` | 否 — Wave 0 |
| BIZ-02 | POST /api/sessions/start 启动 agent | integration | `pytest tests/api/test_control.py::test_start_session -x` | 否 — Wave 0 |
| BIZ-02 | POST /api/sessions/{id}/confirm 响应守卫 | integration | `pytest tests/api/test_control.py::test_confirm_command -x` | 否 — Wave 0 |
| OBS-03 | 前端渲染三面板布局 | smoke | `pnpm --dir frontend test --run` | 否 — Wave 0 |
| OBS-04 | Token 使用量在前端展示 | unit | `pnpm --dir frontend test --run` | 否 — Wave 0 |

### 采样频率
- **每任务提交:** `pytest tests/api/ -x -q`（后端 API 测试，< 30s）
- **每 Wave 合并:** `pytest tests/ -x -q`（完整后端套件）+ `pnpm --dir frontend test`（前端）
- **Phase 门控:** 全量测试绿色通过后方可 `/gsd-verify-work`

### Wave 0 缺口
- [ ] `tests/api/` 目录 — 尚不存在，需要创建
- [ ] `tests/api/test_sse.py` — SSE 端点测试
- [ ] `tests/api/test_sessions.py` — 会话 CRUD 端点测试
- [ ] `tests/api/test_control.py` — Agent 控制端点测试
- [ ] `tests/api/conftest.py` — 共享夹具（EventBus、测试会话、FastAPI TestClient）
- [ ] `frontend/vitest.config.ts` — Vitest 配置
- [ ] `frontend/src/__tests__/` — 前端组件测试
- [ ] 后端: 安装 `httpx`（已安装 0.28.1）用于 `TestClient` — 或使用 `fastapi.testclient.TestClient`

### 安全威胁模型
| 模式 | STRIDE | 标准缓解 |
|------|--------|----------|
| XSS via 工具结果内容 | 信息泄露 | 工具结果为用户可控内容，渲染为文本（不做 HTML 解析），使用 React 默认转义，仅等宽字体展示 |
| CSRF on 确认端点 | 篡改 | 同源 CORS 策略（`allow_origins=["http://localhost:..."]`），本地部署 CSRF 风险极低 |
| SSE 跨会话数据泄露 | 信息泄露 | SSE bridge 必须按 `session_id` 过滤重放，否则 `bus.replay()` 返回所有会话事件 |
| 会话创建洪水 | 拒绝服务 | 本地工具可接受，若暴露到网络则使用已有 `RateLimitGuard` |

### 未解决问题（已解决）
- Session isolation in EventBus → 已解决: 按 session_id 过滤
- FastAPI lifespan wiring → 已解决: 提取工厂函数
- Confirmation flow across SSE → 已解决: PermissionGuard 使用 asyncio.Event
- Session history data format → 已解决: 轻量列表 + 完整事件数组
