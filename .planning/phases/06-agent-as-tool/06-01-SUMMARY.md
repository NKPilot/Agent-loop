---
phase: 06-agent-as-tool
plan: 01
subsystem: agents
tags: [agent, decorator, registry, bridge, tool]
depends_on: []
provides: [loopai.agents, AgentMetadata, AgentToolResult, @agent, AgentRegistry, AgentTool]
affects: [loopai.tools.registry, loopai.agents]
tech-stack:
  added: [Pydantic BaseModel for AgentMetadata/AgentToolResult]
  patterns:
    - "@tool 装饰器模式复用（\\_build_param_schema, \\_build_validation_model）"
    - "ToolRegistry 模式复用（AgentRegistry）"
    - "AsTool 桥接模式（AgentTool 实现 Tool 接口）"
key-files:
  created:
    - src/loopai/agents/__init__.py
    - src/loopai/agents/types.py
    - src/loopai/agents/decorator.py
    - src/loopai/agents/registry.py
    - src/loopai/agents/tool.py
    - tests/test_agents.py
  modified:
    - src/loopai/tools/registry.py
    - src/loopai/agents/types.py (after initial commit)
    - src/loopai/agents/decorator.py (after initial commit)
decisions:
  - "AgentMetadata 扩展 param_schema/validation_model 字段，供 AgentTool 构造 ToolMetadata"
  - "AgentTool 通过 register_meta() 注册到 ToolRegistry，复用完整工具基础设施"
  - "子 Agent 执行时创建独立 EventBus，不污染主 EventBus"
metrics:
  duration:
    start: "2026-05-30T02:30:00Z"
    end: "2026-05-30T02:45:00Z"
    minutes: 15
  completed_date: "2026-05-30"
---

# Phase 6 Plan 1 Summary: @agent 装饰器 + AgentRegistry + AgentTool 桥接

**One-liner:** 创建 Agent-as-Tool 基础设施——@agent 装饰器将子 Agent 封装为 Tool，AgentRegistry 管理子 Agent 元数据，AgentTool 桥接层使子 Agent 可被主 Agent 通过 ToolRegistry 调用，子 Agent 拥有独立 Session 和工具集。

## 任务完成

| Task | Name | Status | Commit | Files |
|------|------|--------|--------|-------|
| 1 | @agent 装饰器 + AgentRegistry + 类型定义 | Done | 6b1e4cf | src/loopai/agents/\_\_init\_\_.py, src/loopai/agents/types.py, src/loopai/agents/decorator.py, src/loopai/agents/registry.py, src/loopai/tools/registry.py |
| 2 | AgentTool 桥接实现 | Done | 7f7bae5 | src/loopai/agents/tool.py, src/loopai/agents/\_\_init\_\_.py, src/loopai/agents/types.py, src/loopai/agents/decorator.py |
| 3 | @agent + AgentTool 单元测试 | Done | 2964fb5 | tests/test_agents.py |

## 架构要点

### @agent 装饰器 (D-01)
- 复用 `tools/decorator.py` 的 `_build_param_schema` 和 `_build_validation_model`
- 从函数类型提示自动推导参数模式（JSON Schema）
- 通过 Pydantic 模型验证传入参数
- 元数据附加到函数 `__agent_meta__` 属性
- 支持 `auto_register=True`（默认），自动注册到模块级 `AgentRegistry`

### AgentRegistry (D-02)
- 与 `ToolRegistry` 独立管理
- 接口：`register()`、`register_many()`、`get()`、`list_all()`
- 重复名称抛出 `ValueError`
- 支持 `in` 运算符和 `len()`

### AgentTool 桥接 (D-03, D-04, D-05)
- 通过 `__tool_meta__` 属性呈现为 `Tool`
- 使用 `register_meta()` 注册到主 Agent 的 `ToolRegistry`
- `execute()` 内部创建完整子 Agent 生命周期：

1. 独立 `EventBus`（不污染主 EventBus）
2. 独立 `Session`，system prompt = agent_meta.system_prompt
3. 独立 `ToolRegistry`（复用 agent_meta 中定义的注册表）
4. `ToolExecutor` + `BudgetGuard` + `LoopDetector` + `MessageValidator` + `PermissionGuard`
5. `LLMClient`（复用主 Agent 的 API 密钥和模型配置）
6. `ReActFSM` 执行，带 `asyncio.wait_for` 超时控制

### ToolRegistry 扩展
- 添加 `register_meta(meta: ToolMetadata)` 方法
- 支持直接注册已有 `ToolMetadata` 实例（AgentTool 桥接需要）

## 测试结果

```
10 passed in 0.54s
```

| Test | Description | Type |
|------|-------------|------|
| test_agent_decorator_creates_agentmetadata | @agent 装饰器正确创建 AgentMetadata 字段 | Unit |
| test_agent_decorator_defaults | @agent 默认参数值验证 | Unit |
| test_agent_registry_register_get_list | AgentRegistry 注册/查找/列表 | Unit |
| test_agent_registry_duplicate_raises | 重复注册抛出 ValueError | Unit |
| test_agent_registry_register_many | register_many 批量注册 | Unit |
| test_agent_tool_tool_meta_shape | AgentTool.__tool_meta__ 返回有效 ToolMetadata | Unit |
| test_agent_tool_creates_independent_session | 子 Agent 创建独立 Session (mock LLM) | Async |
| test_agent_tool_returns_structured_summary | AgentTool.execute 返回结构化摘要 | Async |
| test_agent_tool_timeout_returns_error_summary | 超时返回错误摘要 (success=False) | Async |
| test_sub_agent_tool_isolation | 子 Agent 不能访问主 Agent 注册表的工具 | Unit |

## 偏差处理

### Rule 2 - Missing Functionality
- **AgentMetadata 扩展 param_schema/validation_model 字段** — 原始 AgentMetadata 未包含参数模式，AgentTool 构造 ToolMetadata 时需要。已添加可选字段并更新装饰器传递。

## 已知存根

无。所有代码均完整实现。

## 威胁标记

无。新创建的 agents 包不暴露网络端点或文件系统访问路径。

## 自检

- [x] `src/loopai/agents/__init__.py` — 已创建
- [x] `src/loopai/agents/types.py` — 已创建
- [x] `src/loopai/agents/decorator.py` — 已创建
- [x] `src/loopai/agents/registry.py` — 已创建
- [x] `src/loopai/agents/tool.py` — 已创建
- [x] `tests/test_agents.py` — 已创建
- [x] `src/loopai/tools/registry.py` — 已修改（register_meta）
- [x] 6b1e4cf — commit 存在
- [x] 7f7bae5 — commit 存在
- [x] 2964fb5 — commit 存在
