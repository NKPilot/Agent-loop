---
phase: 03-context-management
plan: 03
subsystem: fsm
tags: [fsm-integration, token-guard, context-compressor, overflow-file, append-only, python]

requires:
  - phase: 03-context-management
    plan: 01
    provides: TokenCounter 类、OverflowFile 写入、ContextCompacted 事件 Schema、OverflowWritten 事件
  - phase: 03-context-management
    plan: 02
    provides: TokenGuard 接口、ContextCompressor 压缩算法
  - phase: 02-tool-system-biz-validation
    provides: ToolResult.overflow_file 字段、ReActFSM 的 _handle_reason/_handle_act 管线
provides:
  - FSM._handle_reason 的 TokenGuard + ContextCompressor 集成管线
  - FSM._handle_act 的溢出文件引用替换逻辑
  - ContextCompacted 和 OverflowWritten 事件集成
  - 追加式存储固化验证

tech-stack:
  added: []
  patterns:
    - _handle_reason 插入 TokenGuard + ContextCompressor 检查：在消息验证后、预算检查前执行
    - _summary_fn 使用 self.client.complete 做摘要 LLM 调用（无 tools），响应仅取 content
    - 溢出文件引用格式：`[工具输出已保存至: {path} ({size}KB)]` + 前 500 字符预览
    - compressor 为 None 时跳过压缩（优雅降级）

key-files:
  modified:
    - src/loopai/state_machine/fsm.py
    - src/loopai/config.py
    - src/loopai/main.py
    - tests/test_fsm.py

key-decisions:
  - "TokenGuard check 插入在 _handle_reason 的 message_validator.validate 之后、budget_guard.check 之前"
  - "摘要 LLM 调用不传 tools 参数，确保纯文本摘要响应"
  - "session.messages 通过 clear()+extend() 原地替换，追加式存储原则（不修改已有消息）"
  - "overflow_file publish 使用独立的条件判断，与 tool_content 构建分开（同一个 if 块覆盖 data non-None 场景）"

requirements-completed: [CTX-02, CTX-03, CTX-04]

duration: 15min
completed: 2026-05-28
---

# Phase 03 Plan 03: FSM 集成 — TokenGuard + 压缩 + 溢出文件 + 追加式固化

**在 ReActFSM 的 _handle_reason 中插入 TokenGuard 检查和 ContextCompressor 触发管线，在 _handle_act 中处理工具输出溢出文件引用，验证追加式存储原则。**

## Performance

- **Duration:** 15 min
- **Started:** 2026-05-28T06:23:00Z
- **Completed:** 2026-05-28T06:38:00Z
- **Tasks:** 2
- **Files modified:** 4
- **Tests added:** 8

## Accomplishments

### Task 1: FSM._handle_reason — TokenGuard + ContextCompressor 集成

- 在 `ReActFSM.__init__()` 中新增 `token_guard` 和 `compressor` 两个可选参数（keyword-only 默认 None）
- 在 `_handle_reason()` 的消息验证之后、预算检查之前插入 TokenGuard 检查管线：
  - TokenGuard.check() 返回 ("compress", token_count, threshold_tokens) 时触发压缩
  - `_summary_fn` 内联定义，调用 `self.client.complete` 做无 tools 的摘要 LLM 调用
  - `ContextCompressor.check_and_compress()` 执行滑动窗口+摘要压缩
  - 压缩成功后 `session.messages.clear(); session.messages.extend(compressed)` 追加式替换
  - 发布 `context_compacted` 事件到 EventBus
- `AgentConfig` 新增 `context_window: int = 128000` 字段
- `run_session()` 中创建 TokenCounter、TokenGuard、ContextCompressor 并注入 FSM
- 4 个集成测试验证：压缩触发、低于阈值不触发、摘要 LLM 调用、compressor=None 优雅降级

### Task 2: FSM._handle_act 溢出文件引用 + 追加式固化验证

- 在 `_handle_act()` 的 Step 5 中修改工具结果注入逻辑：
  - `result.overflow_file` 非空时使用溢出文件引用格式替换完整内容
  - 引用格式包含文件路径、文件大小（KB）、"使用 Bash 工具读取"提示、前 500 字符预览
  - 无 overflow_file 时保持原有行为（直接注入 data）
- 发布 `overflow_written` 事件包含文件路径、工具名称、大小等信息
- 4 个集成测试验证：溢出引用格式、正常输出不变、追加式固化、事件发布

## Task Commits

| # | 任务 | Commit |
|---|------|--------|
| 1 | FSM._handle_reason TokenGuard + ContextCompressor 集成 | `065d23f` |
| 2 | FSM._handle_act 溢出文件引用 + 追加式固化验证 + 全量测试 | `0b5b318` |

## Files Modified

- `src/loopai/state_machine/fsm.py` — TYPE_CHECKING 导入 TokenGuard/ContextCompressor，新增 token_guard/compressor 参数和 _handle_reason 压缩管线，修改 _handle_act 溢出文件引用
- `src/loopai/config.py` — AgentConfig 新增 context_window 字段
- `src/loopai/main.py` — run_session() 创建并注入 TokenGuard、ContextCompressor
- `tests/test_fsm.py` — 新增 _make_fsm_with_context 辅助函数 + TestContextManagement 类（8 个测试）

## Decisions Made

- **TokenGuard 插入位置** — 选择在消息验证后、预算检查前插入，确保先检查上下文窗口再检查步骤预算
- **摘要 LLM 无 tools** — `_summary_fn` 调用 `self.client.complete` 但不传 tools 参数，确保 LLM 仅执行纯文本摘要
- **session.messages 原地替换** — `clear() + extend()` 替换消息列表内容，但保持对同一 Session 对象的引用
- **追加式固化验证** — 压缩操作仅创建新的 summary 消息，不修改已有消息内容（T-03-03-01 篡改缓解）

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None.

## Verification

全部 231 个测试通过（原始 223 个 + 新增 8 个）：

```
tests/test_fsm.py:: 31 passed (原有 23 个 + 新增 8 个)
tests/test_guards.py:: 30 passed
tests/test_tools.py:: 31 passed
tests/test_schemas.py:: 19 passed
tests/test_token_counter.py:: 7 passed
tests/test_context_compressor.py:: 7 passed
(其他测试全部通过)
```

## Requirements Completed

- **CTX-02**: Token 预算守卫和自动压缩触发（FSM 集成：_handle_reason 在 LLM 调用前检查 TokenGuard 并触发 ContextCompressor）
- **CTX-03**: 压缩后的摘要消息管理（context_compacted 事件集成到 EventBus，CLI 渲染器和 JSONL 日志器可消费）
- **CTX-04**: 异常上下文预防（_handle_act 溢出文件引用替换，避免超长工具输出膨胀上下文窗口）

## Phase 3 Completion Status

- CTX-01: Token 计数通过 tiktoken 实时追踪 ✓（Plan 01）
- CTX-02: 自动压缩在 75% 阈值触发 ✓（Plan 02 + Plan 03）
- CTX-03: 压缩摘要事件集成 ✓（Plan 01 Schema + Plan 03 FSM 集成）
- CTX-04: 工具输出溢出文件避免上下文膨胀 ✓（Plan 01 + Plan 03 FSM 集成）

**Phase 3 全部完成。** 下一阶段：Phase 4 — 韧性（重试、速率限制、断路器等）。

---
*Phase: 03-context-management*
*Completed: 2026-05-28*
