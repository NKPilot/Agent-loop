# Phase 8: 动态工具创建核心 (MVP) - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-31
**Phase:** 08-dynamic-tool-core
**Areas discussed:** generate_tool 工具参数, 确认弹窗设计, 工具自测机制, 持久化时机, 语法检查流程, Schema生成方式, 确认超时处理

---

## generate_tool 工具参数

| Option | Description | Selected |
|--------|-------------|----------|
| 完整参数 | Agent传完整参数：名称、描述、代码、测试代码、语言类型。系统验证后自动生成schema | ✓ |
| 仅代码 | Agent只传代码字符串，系统自动从代码中提取名称/描述/schema | |
| 最小参数 | 第一版先传代码+名称+描述，schema自动提取 | |

**User's choice:** 完整参数 — Agent 提供名称、描述、代码、测试代码、语言类型

---

## 确认弹窗设计

| Option | Description | Selected |
|--------|-------------|----------|
| 独立组件 | 新建独立的 ToolCreationDialog 组件 | ✓ |
| 扩展现有组件 | 扩展现有 ConfirmationDialog 支持多种确认类型 | |
| 统一确认中心 | 所有确认事件走同一个组件 | |

**User's choice:** 独立 ToolCreationDialog 组件

---

## 工具自测机制

| Option | Description | Selected |
|--------|-------------|----------|
| Agent写测试 | 语法检查→确认→自测→结果展示→最终确认 | ✓ |
| Agent先自测再确认 | 语法检查→Agent先跑测试→展示结果+代码→确认 | |
| 暂时跳过自测 | v1.1不要求自测 | |

**User's choice:** Agent 附带测试代码，用户确认后在沙箱执行，结果展示给用户审查

---

## 持久化时机

| Option | Description | Selected |
|--------|-------------|----------|
| 确认后立即写入 | 用户确认后立即写文件 | |
| 首次执行成功后 | 工具首次执行成功后才持久化 | |
| 分级别处理 | 会话级内存一直存活，沙箱/项目级首次执行成功后才落盘 | ✓ |

**User's choice:** 分级别 — 会话级确认后内存注册，沙箱/项目级首次成功执行后才写文件

---

## 语法检查流程

| Option | Description | Selected |
|--------|-------------|----------|
| 串行：语法→扫描 | 先语法检查→通过后危险扫描→两项通过才发布确认事件 | ✓ |
| 并行检查 | 语法和扫描同时进行 | |
| 语法通过后展示全部 | 语法通过后确认弹窗同时展示扫描结果 | |

**User's choice:** 串行 — 语法先过，再扫描，都通过才进确认

---

## Schema 生成方式

| Option | Description | Selected |
|--------|-------------|----------|
| Agent提供schema | Agent在参数中显式提供 JSON Schema | ✓ |
| 代码自动提取 | 系统自动从代码类型提示提取 | |
| 暂不生成schema | v1.1动态工具均为无参数工具 | |

**User's choice:** Agent 显式提供 param_schema JSON

---

## 确认超时处理

| Option | Description | Selected |
|--------|-------------|----------|
| 无超时等待 | 一直等待用户操作，Agent 处于 WAITING 状态 | ✓ |
| 超时自动拒绝 | 5分钟后自动拒绝 | |
| 可配置 | 前端可配置超时时间 | |

**User's choice:** 无超时 — 无限等待用户操作

---

## Claude's Discretion

无。全部决策由用户确认。

## Deferred Ideas

无。讨论保持在阶段范围内。
