---
phase: 07-chat-mode
plan: 01
subsystem: backend-api
tags: [chat-mode, fsm, api, multi-turn]
requires: []
provides: [CHAT-01, CHAT-02]
affects: [fsm, api-routes, event-schemas]
tech-stack:
  added:
    - asyncio.Queue (进程内消息传递)
  patterns:
    - "多轮对话 FSM 循环（_run_and_cleanup 循环调用 fsm.run()）"
    - "FINISH_WAIT 状态等待用户新消息"
key-files:
  created: []
  modified:
    - src/loopai/session/context.py
    - src/loopai/state_machine/fsm.py
    - src/loopai/events/schemas.py
    - src/loopai/api/schemas.py
    - src/loopai/api/routes/control.py
    - src/loopai/api/app.py
    - frontend/src/lib/eventTypes.ts
decisions:
  - "使用 asyncio.Queue 作为进程内消息传递机制，避免共享内存或外部消息队列"
  - "session_end 事件双发保护——_run_and_cleanup 通过 session_end_published 标记避免重复发布"
  - "send_message 端点仅在 FINISH_WAIT 或 REASON 状态下接受消息（409 拒绝其他状态）"
metrics:
  duration: 2m 2s
  completed_date: 2026-05-30
---

# Phase 7 Plan 1: Chat 模式后端改造 — FSM FINISH_WAIT + 多轮 API

为 loopAI 添加聊天模式支持。FSM 新增 FINISH_WAIT 状态替代原有的 FINISH，会话完成一轮后等待用户新消息继续。新增 `POST /api/sessions/{id}/messages` 和 `POST /api/sessions/{id}/stop` 端点，基于 `asyncio.Queue` 的进程内消息队列实现多轮对话循环。

## Tasks

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | 添加 FINISH_WAIT 状态 + FSM 多轮循环 + 新事件类型 | 4741a5b | context.py, fsm.py, schemas.py(events), eventTypes.ts |
| 2 | POST /api/sessions/{id}/messages 端点 + 多轮 _run_and_cleanup | 7983924 | schemas.py(api), app.py, control.py |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical Functionality] 防止 session_end 事件双发**
- **Found during:** Task 2
- **Issue:** 原计划的 _run_and_cleanup finally 块始终发布 session_end，但 fsm.run() 在 FINISH 和 ERROR 状态下也已发布 session_end，导致双发事件。
- **Fix:** 在 _run_and_cleanup 中添加 `session_end_published` 布尔标记。当 fsm.run() 因 FINISH/ERROR 退出时标记为已发布；finally 块仅在标记为 False 时补发 session_end。
- **Files modified:** src/loopai/api/routes/control.py
- **Commit:** 7983924

## Threat Surface

| Threat ID | Disposition | Status |
|-----------|-------------|--------|
| T-07-01 (S: POST /messages content validation) | mitigate | Pydantic `content: str` 验证 |
| T-07-02 (E: POST /messages on ended session) | mitigate | 409 if state not FINISH_WAIT/REASON |
| T-07-03 (E: POST /stop on missing session) | mitigate | 404 if not found in queues |
| T-07-04 (E: SSE after session ends) | mitigate | None sentinel + finally cleanup |

## Verification

- `python -c "from loopai.session.context import AgentState; print(AgentState.FINISH_WAIT.value)"` → `finish_wait`
- FSM.run() 在 FINISH_WAIT 时发布 round_end 而非 session_end ✓
- POST /api/sessions/{id}/messages 在 FINISH_WAIT 状态返回 200 ✓
- POST /api/sessions/{id}/messages 在非 FINISH_WAIT/REASON 状态返回 409 ✓
- POST /api/sessions/{id}/stop 在活跃会话返回 200 ✓
- user_message 事件通过 EventBus 发布 ✓

## Known Stubs

None. 所有端点均已完整实现状态验证和错误处理。

## Self-Check: PASSED

- All 2 tasks committed (4741a5b, 7983924)
- All 7 modified files exist
- All verification commands pass
