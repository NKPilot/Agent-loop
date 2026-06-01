---
phase: 09-security-hardening
plan: 01
subsystem: events
tags: [schemas, sandbox, security, event-driven, Pydantic, TypeScript]
requires: []
provides: [sandbox_event_schemas]
affects: [SandboxExecutor, DynamicToolCreator, SSE Bridge, Frontend Events]
tech-stack:
  added: []
  patterns: [EventBase subclass, discriminated union, Literal constraint]
key-files:
  created: []
  modified:
    - src/loopai/events/schemas.py
    - frontend/src/lib/eventTypes.ts
    - tests/test_schemas.py
decisions: []
metrics:
  duration: 0.1h
  completed_date: 2026-06-01
---

# Phase 09 Plan 01: 沙箱安全事件契约 Summary

为沙箱安全加固定义事件契约——新增 3 个沙箱违规事件类型（SandboxTimeout、SandboxViolation、SandboxResourceExceeded），同步 Python Pydantic 模型和 TypeScript 前端接口。后续 SandboxExecutor 加固（Plan 09-02）和 DynamicToolCreator 集成（Plan 09-03）可直接引用这些事件类型。

## 已完成任务

| 任务 | 名称 | 提交 | 文件 |
|------|------|------|------|
| 1 (RED) | 添加沙箱安全事件 Schema 失败测试 | `644d478` | `tests/test_schemas.py` |
| 1 (GREEN) | 新增 3 个沙箱事件 Pydantic 模型 + 更新 Event 联合类型 | `0194ca0` | `src/loopai/events/schemas.py`, `tests/test_schemas.py` |
| 2 | 同步 TypeScript 前端事件类型 | `60a7c9e` | `frontend/src/lib/eventTypes.ts` |

## 实现详情

### Python 事件模型（schemas.py）

新增 3 个 EventBase 子类，位于 `# ── 沙箱安全事件（Phase 9）──` 区块：

- **SandboxTimeout** — `event_type: "sandbox_timeout"`，字段：`step_num: int`、`tool_name: str`、`timeout_seconds: float`
- **SandboxViolation** — `event_type: "sandbox_violation"`，字段：`step_num: int`、`tool_name: str`、`violation_type: Literal["path_escape", "network_attempt", "sensitive_path"]`、`detail: str`
- **SandboxResourceExceeded** — `event_type: "sandbox_resource_exceeded"`，字段：`step_num: int`、`tool_name: str`、`resource_type: Literal["memory", "process", "file_size"]`、`limit: str`、`detail: str`

3 个新类均已加入 `Event` 区分联合类型（`ToolCreationFailed` 之后）。

### TypeScript 前端类型（eventTypes.ts）

新增 3 个 interface 在 `// ── Sandbox security events (Phase 9) ──` 区块：

- **SandboxTimeoutEvent** — 字段与 Python 一一对应
- **SandboxViolationEvent** — `violation_type` 为 3 值 union type
- **SandboxResourceExceededEvent** — `resource_type` 为 3 值 union type

Event 联合类型和 EVENT_TYPE_MAP 均已同步更新。

### 测试覆盖

- 4 个新测试类：`TestSandboxTimeoutSchema`、`TestSandboxViolationSchema`、`TestSandboxResourceExceededSchema`、`TestSandboxEventsDiscriminatedUnion`
- 覆盖：实例化、字段值、Literal 约束（有效值通过/非法值拒绝）、Event 区分联合类型反序列化、JSON 往返序列化
- 更新已有测试：事件类型计数 22 -> 25，`TestAllEventsUniqueType` 和 `TestUpdatedEventTypeCount` 均包含新事件类
- **36/36 测试全部通过**，TypeScript 编译零错误

## 成功标准验证

- [x] `SandboxTimeout` Pydantic 模型正确序列化/反序列化
- [x] `SandboxViolation` Pydantic 模型正确序列化/反序列化，violation_type 约束生效
- [x] `SandboxResourceExceeded` Pydantic 模型正确序列化/反序列化，resource_type 约束生效
- [x] Event 区分联合类型可路由到三种新事件类型
- [x] TypeScript 编译无错误，3 个新 interface 与 Python 字段一一对应
- [x] EVENT_TYPE_MAP 包含 3 个新条目的中文标签

## 偏差

无——计划完全按描述执行。

## TDD Gate Compliance

| Gate | Commit | Status |
|------|--------|--------|
| RED | `644d478` — `test(09-01): 添加沙箱安全事件 Schema 的失败测试（RED）` | PASS |
| GREEN | `0194ca0` — `feat(09-01): 新增 3 个沙箱安全事件 Pydantic 模型 + 更新 Event 联合类型` | PASS |

RED 阶段测试因 ImportError 失败（类未定义），GREEN 阶段 36/36 通过。TDD 门序列完整。

## 已知 Stubs

无。

## Threat Flags

无——纯类型定义和事件契约，未引入新的网络端点、认证路径或文件访问模式。事件字段设计遵循计划中的威胁模型：`detail` 字段仅承载人类可读中文描述，不包含系统路径或凭据；资源限制值（limit 字段）为公开安全策略配置。

## 备注

- 任务 1 采用 TDD 流程：先写失败测试（RED），再实现代码（GREEN）
- TypeScript 编译验证使用主仓库的 `tsc` 二进制（工作树 node_modules 未安装），编译零错误
- 前置 SSE 测试失败（`test_event_stream_handles_disconnect`）为已有问题，与本次变更无关
