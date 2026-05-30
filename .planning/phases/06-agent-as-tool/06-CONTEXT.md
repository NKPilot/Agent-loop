# Phase 6: Agent-as-Tool - Context

**Gathered:** 2026-05-30
**Status:** Ready for planning

## Phase Boundary

本阶段交付 Agent-as-Tool 多 Agent 协作框架：`@agent` 装饰器将 Agent 封装为可被主 Agent 调用的 Tool，子 Agent 拥有独立 Session 和工具集，完成后结构化回传结果。以磁盘诊断为验证场景——主 Agent 委托"磁盘分析 Agent"诊断 + 委托"清理 Agent"执行清理。前端展示多 Agent 嵌套调用链。

## Implementation Decisions

### @agent 装饰器
- **D-01:** `@agent` 装饰器——类似 `@tool`，定义子 Agent 的 system prompt、工具集、预算。调用时内部启动独立 ReActFSM session，完成后返回结构化结果。对外表现为普通 Tool。
- **D-02:** 子 Agent 通过 `AgentRegistry` 注册，与 `ToolRegistry` 独立管理。`AgentTool` 桥接两者——它既是 Tool（可被 ToolRegistry 注册），内部又调用 Agent。

### 子 Agent 工具权限
- **D-03:** 独立工具集——每个子 Agent 有自己独立的 `ToolRegistry`。例如磁盘分析 Agent 只有 disk_df/disk_du/disk_find（只读），清理 Agent 只有 disk_rm（需确认）。
- **D-04:** 子 Agent 的 Bash 工作目录继承自主 Agent 配置。

### 结果回传
- **D-05:** 结构化摘要——子 Agent 完成后返回 `{summary, tool_calls: [...], token_usage, steps, session_id}`。主 Agent 看到摘要 + 关键指标，不需要读全部细节。

### Claude's Discretion
- @agent 装饰器的具体参数设计
- AgentTool 内部的 FSM 创建和 Session 生命周期管理
- 子 Agent 结果摘要的生成方式（最终回复 vs LLM 再摘要）
- 前端多 Agent 调用链的 UI 布局

## Canonical References

### 项目定义
- `.planning/PROJECT.md` — v2.0 核心价值
- `.planning/REQUIREMENTS.md` — AGT-01 至 AGT-05, BIZ-03, WEB-01/02

### 复用接口
- `src/loopai/tools/decorator.py` — @tool 装饰器（@agent 的参考模板）
- `src/loopai/tools/registry.py` — ToolRegistry（AgentRegistry 的参考）
- `src/loopai/state_machine/fsm.py` — ReActFSM（子 Agent 的执行引擎）
- `src/loopai/session/context.py` — Session（子 Agent 的上下文容器）
- `src/loopai/main.py` — create_agent_components()（子 Agent 组件创建参考）

## Existing Code Insights

### Reusable Assets
- **@tool 装饰器 + ToolRegistry** — @agent 和 AgentRegistry 可直接复用模式
- **ReActFSM** — 子 Agent 的执行引擎，无需改动
- **Session** — 子 Agent session 独立实例化即可
- **create_agent_components()** — 已有组件工厂，可复用于子 Agent 创建

### Integration Points
- **AgentTool.execute()** — 创建子 Agent 组件 → 运行 FSM → 收集结果 → 返回摘要
- **主 Agent 的 ToolRegistry** — 注册 AgentTool，LLM 像调用普通工具一样调用
- **Web 前端** — AgentTimeline 需支持嵌套展示（子 Agent 调用可展开）

## Deferred Ideas

- 子 Agent 并行执行（多个子 Agent 同时跑）— v2.1
- Agent-to-Agent 直接通信（不经过主 Agent）— v2.2
- 子 Agent 结果缓存（相同输入不重复跑）— v2.1

---

*Phase: 6-Agent-as-Tool*
*Context gathered: 2026-05-30*
