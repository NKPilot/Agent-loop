---
phase: 03-context-management
plan: 02
subsystem: context
tags: [context-compressor, sliding-window, llm-summary, token-guard, tiktoken, python]

requires:
  - phase: 03-context-management
    plan: 01
    provides: TokenCounter 类（tiktoken cl100k_base 编码）
  - phase: 01-agent-core-loop
    provides: Event Schema 模式、Guard 模式参考（BudgetGuard）
provides:
  - ContextCompressor — 75% 阈值触发的滑动窗口+摘要压缩，保留最近 3 轮完整对话
  - TokenGuard — Token 预算守卫，返回 ("ok"|"compress", token_count, threshold_tokens)
affects:
  - 03-03-PLAN.md（FSM 集成依赖 ContextCompressor 和 TokenGuard 的接口）

tech-stack:
  added: []
  patterns:
    - ContextCompressor: 异步 check_and_compress(messages, summary_fn) 分离摘要生成和消息处理
    - TokenGuard: check(messages) 返回状态信号，不修改消息列表（与 BudgetGuard 同模式）
    - _find_round_cutoff: 反向遍历识别 assistant+tool_calls 对话轮

key-files:
  created:
    - src/loopai/context/compressor.py
    - tests/test_context_compressor.py
  modified:
    - src/loopai/context/__init__.py
    - src/loopai/state_machine/guards.py
    - tests/test_guards.py

key-decisions:
  - "保留最近 3 轮完整对话（Claude's Discretion），不足 3 轮时不压缩"
  - "摘要消息使用 role='system' + [Compressed Summary] 前缀标记，避免与原始消息混淆（T-03-02-01/02）"
  - "_find_round_cutoff 从末端反向遍历：只计数 assistant 消息 + tool_calls 为对话轮"

patterns-established:
  - "压缩器与守卫分离：ContextCompressor 执行压缩，TokenGuard 仅返回信号"
  - "异步 summary_fn 注入：LLM 调用由外部注入，压缩器不直接依赖 LLM 客户端"
  - "TYPE_CHECKING 导入 TokenCounter 用于 guards.py 类型注解，避免循环导入"

requirements-completed: [CTX-01, CTX-02]

duration: 8min
completed: 2026-05-28
---

# Phase 03 Plan 02: 上下文压缩器 + Token 预算守卫

**ContextCompressor 滑动窗口+摘要压缩（75% 阈值，保留最近 3 轮）+ TokenGuard 阈值检测信号**

## Performance

- **Duration:** 8 min
- **Started:** 2026-05-28T06:15:00Z
- **Completed:** 2026-05-28T06:23:00Z
- **Tasks:** 2
- **Files modified:** 5 (+2 created)

## Accomplishments

- ContextCompressor 实现滑动窗口+摘要压缩算法：超过 75% 阈值时自动触发，保留最近 N 轮完整对话
- `_find_round_cutoff` 反向遍历识别对话轮（assistant + tool_calls = 1 轮），消息不足时不压缩
- `_build_summary_prompt` 生成标准摘要 prompt，保留用户需求、工具调用结果和任务状态
- 摘要消息标记 `[Compressed Summary]` 前缀（T-03-02-01），role 固定为 "system"（T-03-02-02）
- TokenGuard 实现 Token 预算守卫：未达 75% 返回 "ok"，达到返回 "compress" 信号
- 通过 TYPE_CHECKING 避免 `guards.py` 环形导入

## Task Commits

每个任务原子化提交：

| # | 任务 | Commit |
|---|------|--------|
| 1 | ContextCompressor 滑动窗口+摘要压缩 + 测试 | `32559b1` |
| 2 | TokenGuard Token 预算守卫 + 测试 | `f921d9f` |

## Files Created/Modified

- `src/loopai/context/compressor.py` — ContextCompressor 类（滑动窗口+摘要压缩算法）
- `tests/test_context_compressor.py` — 7 个 ContextCompressor 测试
- `src/loopai/context/__init__.py` — 添加 ContextCompressor 导出
- `src/loopai/state_machine/guards.py` — 添加 TokenGuard 类（TYPE_CHECKING 导入 TokenCounter）
- `tests/test_guards.py` — 新增 5 个 TokenGuard 测试

## Decisions Made

- **保留 3 轮完整对话（Claude's Discretion）** — 不足 3 轮时不压缩，确保短对话不会丢失上下文
- **摘要消息 role="system" + [Compressed Summary] 前缀** — 遵循 T-03-02-01/02 威胁缓解策略，下游不会混淆摘要和原始消息
- **反序遍历轮次识别** — _find_round_cutoff 从末端反向遍历，只计数 assistant + tool_calls 为对话轮，user/system 消息与其他上下文一起随最旧内容摘要
- **压缩器与守卫分离** — TokenGuard 只返回信号不修改消息，实际压缩由 FSM 调用 ContextCompressor 执行

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## Verification

全部 223 个测试通过：

```
tests/test_context_compressor.py:: 7 passed
tests/test_guards.py:: 30 passed (含 5 个 TokenGuard 测试)
tests/test_token_counter.py:: 7 passed
tests/test_tools.py:: 31 passed
tests/test_schemas.py:: 19 passed
(其他 129 个已有测试全部通过)
```

## Requirements Completed

- **CTX-01**: Token 计数通过 tiktoken 实时追踪上下文用量（进一步：TokenGuard 利用 TokenCounter 做阈值检测）
- **CTX-02**: Agent 在达到 75% 窗口阈值时自动触发上下文压缩（ContextCompressor 实现）

## Next Phase Readiness

- 03-03-PLAN.md 可依赖 ContextCompressor + TokenGuard 接口集成到 ReActFSM：
  - FSM._handle_reason 在 LLM 调用前执行 TokenGuard.check()，收到 "compress" 时调用 ContextCompressor
  - ContextCompacted 事件已在 Plan 01 中定义 Schema，压缩时可发布到 EventBus
- Token 预算守卫的模式与 BudgetGuard 一致，FSM 可统一编排守卫管线

---
*Phase: 03-context-management*
*Completed: 2026-05-28*
