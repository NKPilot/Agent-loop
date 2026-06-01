---
gsd_state_version: 1.0
milestone: v1.1
milestone_name: 动态工具系统
status: milestone_complete
last_updated: "2026-06-01T14:18:48.637Z"
progress:
  total_phases: 2
  completed_phases: 1
  total_plans: 8
  completed_plans: 5
  percent: 63
---

# 项目状态

## 项目参考

参见: .planning/PROJECT.md (更新于 2026-05-31)

**核心价值:** 让 AI Agent 不仅"能跑"，而且可靠、可观测、可扩展——从 harness 设计的深度思考出发，构建值得信任的 agent 系统
**当前焦点:** v1.1 动态工具系统——Agent 能在沙箱内自主编写 Python/Bash 代码，经用户确认后动态注册为新工具

## 当前位置

阶段: 路线图规划中
计划: —
状态: 需求已定义，等待 Phase 8 规划
最近活动: 2026-05-31 — v1.1 路线图创建

进度: [░░░░░░░░░░░░░░░░░░░░] 0%

## 性能指标

**速度:**

- 已完成计划数: 0
- 平均耗时: —
- 总执行时间: —

**分阶段统计:**

| 阶段 | 计划数 | 总耗时 | 平均/计划 |
|------|--------|--------|-----------|
| 8. 动态工具创建核心 (MVP) | 0 | — | — |
| 9. 安全加固与沙箱隔离 | 0 | — | — |
| 10. 用户体验与工具管理 | 0 | — | — |
| 11. 集成验证与优化 | 0 | — | — |

**近期趋势:**

- v1.0 阶段 1-6 全部完成，阶段 7（Chat 模式）进行中
- v1.1 路线图已创建，26 条需求覆盖 4 个阶段

*每次计划完成后更新*

## 累积上下文

### 决策

v1.0 决策记录在 PROJECT.md 的"关键决策"表中。v1.1 新增决策:

- [v1.1]: 动态工具系统采用"管道式创建 + 三层防御 + 人工确认门"架构模式
- [v1.1]: 零新增 Python 依赖——沙箱隔离全部使用 Python 3.12+ stdlib（ast、subprocess、resource、importlib.util）
- [v1.1]: 前端仅新增 `@monaco-editor/react` 一个依赖，覆盖代码展示和 diff 对比
- [v1.1]: 动态工具永不可获得 `PermissionLevel.SAFE`，最低为 MODERATE
- [v1.1]: 动态工具使用 `dynamic.` 命名空间前缀 + 随机哈希后缀，与静态工具分区隔离
- [v1.1]: AST 扫描做第一道快筛（不做信任边界），subprocess 子进程 + rlimit 做第二道隔离，用户确认做第三道安全门
- [v1.1]: 阶段 8 和 10 可跳过 deep research（有完善模式参考），阶段 9 和 11 需 research-phase

### 待办事项

无。

### 阻塞/关注点

| 项 | 详情 |
|----|------|
| WSL2 外部沙箱兼容性 | Phase 9 的 seccomp-bpf / Landlock 需在 WSL2 内核验证，可能有降级方案 |
| Monaco Editor React 19 兼容性 | `@monaco-editor/react@next` (4.8.0-rc.3) 是 RC 版本，需在 Phase 8 plan 阶段选定最终方案 |

## 延期项

| 分类 | 条目 | 状态 | 延期时间 |
|------|------|------|----------|
| — | — | — | — |

## 会话连续性

上次会话: 2026-05-31
停止于: v1.1 路线图创建
恢复文件: .planning/ROADMAP.md
