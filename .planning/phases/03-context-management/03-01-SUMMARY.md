---
phase: 03-context-management
plan: 01
subsystem: context
tags: [tiktoken, token-counter, overflow-file, event-schema, pydantic, python]
requires:
  - phase: 01-agent-core-loop
    provides: EventBus 基础设施、事件 Schema 模式、Pydantic 事件基类
  - phase: 02-tool-system-biz-validation
    provides: ToolExecutor、ToolResult（含 overflow_file 字段）、工具执行管线
provides:
  - TokenCounter 类（tiktoken cl100k_base 编码精确计数）
  - TokenizerProtocol 接口（D-04 provider-tokenizer 预留）
  - ToolExecutor 溢出文件写入（>80K 字符自动写入 .sandbox/overflow/）
  - ContextCompacted / TokenWarning 事件 Schema（Event 联合类型扩展）
affects:
  - 03-02-PLAN.md（上下文压缩 + Token 守卫依赖 TokenCounter 和 TokenWarning 事件）
  - 03-03-PLAN.md（FSM 集成依赖溢出文件逻辑和 ContextCompacted 事件）

tech-stack:
  added: ["tiktoken>=0.9.0"]
  patterns:
    - TokenizerProtocol: typing.Protocol 定义 provider 无关的 tokenizer 接口
    - Overflow file: 工具输出超过 80K 字符时写入磁盘文件，ToolResult.overflow_file 指向路径

key-files:
  created:
    - src/loopai/context/__init__.py
    - src/loopai/context/token_counter.py
    - tests/test_token_counter.py
  modified:
    - pyproject.toml
    - src/loopai/tools/executor.py
    - src/loopai/events/schemas.py
    - tests/test_tools.py
    - tests/test_schemas.py

key-decisions:
  - "使用 tiktoken cl100k_base 编码（D-03），跨模型误差在 5% 以内"
  - "溢出文件路径格式 .sandbox/overflow/{session_id}_{tool_call_id}_{timestamp}.txt"
  - "溢出文件仅写入磁盘，不在上下文中自动替换——FSM._handle_act 负责注入上下文时引用"

patterns-established:
  - "tokenizer 接口通过 typing.Protocol 定义，实现类只需实现 count_text/count_message/count_messages"
  - "溢出文件使用 os.makedirs + pathlib.Path.write_text，确保目录存在且编码正确"
  - "ContextCompacted/TokենWarning 遵循现有 EventBase 模式，event_type 字面量默认值"

requirements-completed: [CTX-01, CTX-04]

duration: 14min
completed: 2026-05-28
---

# Phase 03 Plan 01: Token 计数 + 溢出文件 + 事件 Schema 扩展

**tiktoken TokenCounter 实现、ToolExecutor 溢出文件写入（替换 100KB 截断）、ContextCompacted/TokenWarning 事件类型**

## Performance

- **Duration:** 14 min
- **Started:** 2026-05-28T05:59:16Z
- **Completed:** 2026-05-28T06:13:30Z
- **Tasks:** 3
- **Files modified:** 5 (+2 created)

## Accomplishments

- TokenCounter 类实现 tiktoken 精确计数：count_text / count_message / count_messages
- TokenizerProtocol 接口定义 provider-tokenizer 协议（D-04 预留）
- ToolExecutor 移除 100KB 截断，改为 >80K 字符自动写入溢出文件
- 溢出文件路径 `.sandbox/overflow/{session_id}_{tool_call_id}_{timestamp}.txt`
- ContextCompacted / TokenWarning 事件 Schema 定义完成，可被 EventBus 消费
- Event 联合类型扩展，支持新事件的 discriminated union 解析

## Task Commits

每个任务原子化提交：

| # | 任务 | Commit |
|---|------|--------|
| 1 | TokenCounter 实现 + tiktoken 依赖 + 包结构 | `aebeca1` |
| 2 | ToolExecutor 溢出文件写入（替换 100KB 截断） | `af2bc26` |
| 3 | 新增上下文管理事件 Schema（ContextCompacted / TokenWarning） | `76ee85d` |

## Files Created/Modified

- `pyproject.toml` — 添加 `tiktoken>=0.9.0` 依赖
- `src/loopai/context/__init__.py` — context 包导出 TokenCounter 和 TokenizerProtocol
- `src/loopai/context/token_counter.py` — TokenCounter 类和 TokenizerProtocol 接口
- `src/loopai/tools/executor.py` — 溢出文件写入逻辑（替换 100KB 截断）
- `src/loopai/events/schemas.py` — ContextCompacted / TokenWarning 事件 Schema
- `tests/test_token_counter.py` — 7 个 TokenCounter 测试
- `tests/test_tools.py` — 3 个溢出文件测试（新增在 28 个工具测试中）
- `tests/test_schemas.py` — 5 个新事件 Schema 测试 + 更新现有 unique type 断言

## Decisions Made

- **tiktoken cl100k_base 编码（D-03）** — 跨模型误差 <5%，适用 GPT-4/GPT-3.5
- **溢出文件路径格式** — `.sandbox/overflow/{session_id}_{tool_call_id}_{timestamp}.txt`，session_id 为空时回退到 `{timestamp}.txt`
- **溢出文件行为** — 仅写入磁盘，数据保持完整，由 FSM._handle_act 负责在注入上下文时替换为引用

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- tiktoken 首次 `get_encoding("cl100k_base")` 触发编码数据下载，超过 pytest 默认 10s 超时。使用 `--timeout 120` 解决（一次性问题，后续调用使用缓存）。
- TokenCounter 测试中的精确 token 计数断言需要先通过 tiktoken 验证具体数值，调整了 "get_weather{"city": "Tokyo"}" = 9 tokens 等实际值。

## Verification

全部 54 个测试通过：

```
tests/test_token_counter.py:: 7 passed
tests/test_tools.py:: 28 passed (含 3 个 overflow 测试)
tests/test_schemas.py:: 19 passed (含 5 个新事件测试)
```

## Requirements Completed

- **CTX-01**: Token 计数通过 tiktoken 实时追踪上下文用量
- **CTX-04**: 超长工具输出（>80K 字符）写入溢出文件而非截断

## Next Phase Readiness

- 03-02-PLAN.md 可依赖 TokenCounter 实现上下文压缩 + Token 守卫
- 03-03-PLAN.md 可依赖溢出文件逻辑和 ContextCompacted 事件集成到 ReActFSM

---
*Phase: 03-context-management*
*Completed: 2026-05-28*
