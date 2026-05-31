---
phase: 08-dynamic-tool-core
plan: 03
subsystem: tools
tags: [dynamic-tool, pipeline, safety, sandbox, registration]
requires:
  - 08-01 (ToolMetadata.is_dynamic + types)
  - 08-02 (DangerousModuleScanner + SandboxExecutor + ToolPersistenceManager + ToolRegistry 分区)
provides:
  - DynamicToolCreator (6 阶段管道)
  - create_generate_tool_fn (内置工具工厂)
  - generate_tool (@tool 装饰的 Agent 可调用工具)
affects:
  - src/loopai/tools/dynamic_creator.py
tech-stack:
  added: [asyncio.Event, hashlib, uuid, subprocess (bash -n), tempfile]
  patterns: [pipeline, observer (EventBus publish), async-gate (asyncio.Event), closure-isolation]
key-files:
  created:
    - src/loopai/tools/dynamic_creator.py (696 行)
  modified: []
decisions:
  - DynamicToolCreator 6 阶段管道顺序：语法检查→危险扫描→确认暂停→沙箱自测→持久化→注册
  - Stage 2 危险扫描不阻止流程——风险标记供用户在 Stage 3 审查决策
  - Stage 3 确认使用 asyncio.Event 无超时等待（D-04 设计要求）
  - func_ref 通过闭包捕获不可变值（str）构造独立 async 函数（Pitfall 3 防护）
  - 动态工具 permission_level 强制 MODERATE，永不可 SAFE
  - Phase 8 基础版 func_ref：每次调用创建临时 SandboxExecutor + 临时目录执行
  - Bash 危险扫描覆盖 11 种模式（rm -rf /, dd, mkfs, fork bomb, curl|sh, wget|sh, /dev/sd, chmod 777 /, > /dev/sd, wget -O, curl -o）
metrics:
  duration: ""
  completed_date: ""
---

# Phase 08 Plan 03: DynamicToolCreator 6 阶段管道 + generate_tool 内置工具

**一句话总结：** 实现 DynamicToolCreator 6 阶段串行管道（语法检查、危险扫描、确认暂停、沙箱自测、持久化、注册）和 generate_tool 内置工具工厂函数，Agent 可通过 ToolExecutor 调用提交代码创建动态工具。

## 已完成任务

### Task 1: 创建 DynamicToolCreator 6 阶段管道类

**提交:** `df9f07a`

**实现内容:**

- **DynamicToolCreator 类** — 接受 registry/bus/session_id/sandbox/persistence 五个依赖
- **Stage 0 — 基本校验:** language 白名单（python/bash）、name/code 非空、param_schema JSON 合法性、tool_id 按 `dynamic.{sha256[:8]}_{name}` 格式计算
- **Stage 1 — 语法检查:** Python 使用 `ast.parse()` 捕获 SyntaxError 返回行号和错误信息；Bash 使用 `bash -n` 子进程检查，10 秒超时
- **Stage 2 — 危险扫描:** Python 委托 `DangerousModuleScanner().scan()`；Bash 使用 11 种正则模式（rm -rf /, dd, mkfs, fork bomb, curl|sh, wget|sh, /dev/sd 等），返回结构化风险列表。扫描不阻止流程
- **Stage 3 — 用户确认:** `uuid4()[:8]` 生成 confirmation_id → `asyncio.Event` 存入 `_pending_confirmations` → `EventBus.publish("tool_creation_requested")` 携带完整代码/风险标记 → `await event.wait()` 无超时阻塞
- **Stage 4 — 沙箱自测:** 合并 code + test_code → `SandboxExecutor.execute()` 隔离执行 → 发布 `tool_creation_test_result` 事件 → 失败返回 ToolResult.error，清理临时目录
- **Stage 5+6 — 持久化 + 注册:** `register_meta(is_dynamic=True)` 立即注册到内存 → `ToolPersistenceManager.save()` 写文件（session 级跳过）→ 发布 `tool_created` 事件
- **respond() 方法:** API 端点调用，查找 `_pending_confirmations`，存储 config，`event.set()` 唤醒管道
- **_make_func_ref():** 闭包仅捕获 code/language（str 不可变值），返回独立 async 函数，每次调用创建新 SandboxExecutor + TemporaryDirectory，kwargs 写入 args.json 后执行包装脚本。不持有 self/Session 引用（Pitfall 3 防护）

### Task 2: 创建 generate_tool 内置工具函数

**提交:** 代码包含在 `df9f07a`（与 Task 1 同一文件，同一提交）

**实现内容:**

- **create_generate_tool_fn(creator) -> Callable** 工厂函数
- **_generate_tool_impl** — async 函数，接受 name/description/code/test_code/language/param_schema 6 个参数，委托 `creator.generate_tool()`
- **@tool 装饰:** name="generate_tool", description 含中文流程说明, permission_level=MODERATE, timeout=120s, tags=["dynamic", "meta"]
- **`__all__`** 导出: `["DynamicToolCreator", "create_generate_tool_fn"]`

## 验证结果

所有自动化验证通过:

```
DynamicToolCreator instantiation OK
tool_id format OK
generate_tool fn OK
Module OK
__all__ exports OK
```

## 偏离说明

### 执行流程偏离

**1. [Task 合并] Task 1 和 Task 2 在同一提交中完成**
- **原因:** 两个任务修改同一文件 `src/loopai/tools/dynamic_creator.py`，`create_generate_tool_fn` 依赖于 `DynamicToolCreator` 类。为保持代码一致性和减少文件碎片，在一次写入中完成全部实现。
- **影响:** Task 2 的独立提交缺失——两个任务的代码在 `df9f07a` 中一起提交。两个验证（Task 1 和 Task 2）均独立通过。

## 已知 Stub

无。

## 威胁标记

无新增威胁表面。实现遵循计划 `<threat_model>` 中的所有缓解措施：
- T-08-08: func_ref 闭包不捕获 self/Session（已验证）
- T-08-09: confirmation_id 使用 uuid4 生成，仅 `_pending_confirmations` 中有效
- T-08-10: generate_tool timeout=120s，各阶段独立超时
- T-08-11: 结构化错误仅返回语法错误行号/消息和危险模块名，不泄露路径或内部状态

## Self-Check: PASSED

- [x] `src/loopai/tools/dynamic_creator.py` 存在（696 行）
- [x] 提交 `df9f07a` 存在于 git log
- [x] 模块可导入：`from loopai.tools.dynamic_creator import DynamicToolCreator, create_generate_tool_fn`
- [x] DynamicToolCreator 可实例化（5 个依赖注入）
- [x] create_generate_tool_fn 返回 @tool 装饰函数，__tool_meta__ 正确
- [x] __all__ 导出正确
