---
phase: 04-resilience
plan: 02
subsystem: resilience/guards
tags: [guard-pipeline, cost-estimation, rate-limiting, loop-classification, metacognitive-prompting]
requires: [03-03 TokenGuard]
provides: [GuardPipeline, CostGuard, RateLimitGuard, LoopClassification, metacognitive prompts]
affects: [fsm.py (future integration), guards.py]
tech-stack:
  added: []
  patterns: [short-circuit pipeline, sliding-window rate limit, model-pricing table, window-based loop classification]
key-files:
  created: []
  modified:
    - src/loopai/state_machine/guards.py
    - tests/test_guards.py
decisions:
  - "LoopClassification 分类通过两条路径触发：primary（consecutive_count >= threshold）和 secondary（窗口大小 >= threshold 但签名不同）"
  - "GuardPipeline 使用 isinstance 检查适配 TokenGuard 的 tuple 返回和 CostGuard/RateLimitGuard 的 GuardResult 返回"
  - "CostGuard 使用 API 默认定价表，模型名前缀匹配，未知模型回退 gpt-4o 定价"
  - "RateLimitGuard 使用 time.monotonic() 滑动窗口而非基于计数的滑动窗口"
metrics:
  duration: 15min
  completed_date: "2026-05-29"
---

# Phase 4 Plan 2: 守卫管道 + 成本/速率限制 + 循环分类升级 Summary

实现 GuardPipeline 编排层、CostGuard 成本估算守卫、RateLimitGuard 速率限制守卫，以及 LoopDetector 循环检测升级（分类类型 + 元认知提示注入）。

## 任务与提交

| 任务 | 描述 | 提交哈希 | 关键变更 |
|------|------|----------|----------|
| 1 | GuardPipeline + CostGuard + RateLimitGuard | `5da1cdb` | GuardPipeline 短路由管道, CostGuard 模型定价成本估算, RateLimitGuard 滑动窗口速率限制, GuardResult 数据类 |
| 2 | LoopDetector 升级 — 分类 + 元认知提示 | `448797a` | LoopClassification StrEnum, check() 三元组返回, window-based 双路径分类, get_meta_prompt() 中文元认知提示 |

## 需求实现

| 需求 | 状态 |
|------|------|
| RES-02: 循环检测分类 + 元认知提示 | 已实现 |
| RES-04: 守卫管道（Token → Cost → Rate 顺序） | 已实现 |

## 测试覆盖

- **Task 1**: 10 个新测试 (TestGuardPipeline x3, TestCostGuard x4, TestRateLimitGuard x3)
- **Task 2**: 7 个新测试 (TestLoopDetectorUpgrade x7) + 8 个已更新测试 (TestLoopDetector x7 + TestLoopDetectorEdgeCases x2, 解包三元组)
- **总计**: 47 个 guards 测试全部通过
- **FSM 测试**: tiktoken 缺失（预存环境问题，非本计划引入）

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] LoopClassification 的 LOOP_SAME_TOOL 和 LOOP_STUCK 在原始设计中无法检测**

- **发现于:** Task 2 — LoopDetector 升级实现
- **问题:** 原始设计中 classification 逻辑仅在 `consecutive_count >= warn_threshold` 时运行，但 LOOP_SAME_TOOL（不同参数）和 LOOP_STUCK（不同工具）每次都会重置 consecutive_count 为 1，永远无法达到 warn_threshold，因此这两种分类永远不会被返回。
- **修复:** 添加 secondary classification path — 当窗口中有 >= warn_threshold 个条目时，即使 consecutive_count < warn_threshold，也分析窗口模式：全部同一工具 → LOOP_SAME_TOOL，全部不同工具 → LOOP_STUCK。Primary path（同签名 + consecutive_count）仍处理 LOOP_EXACT_SAME。
- **修改文件:** `src/loopai/state_machine/guards.py` — check() 方法中的 classification 逻辑
- **提交:** `448797a`

## 威胁缓解

| 威胁 | 处理方式 |
|------|----------|
| T-04-05 (DoS: RateLimitGuard) | 已实现 — 可配置 max_calls/window_seconds，被限制时返回明确反馈 |
| T-04-06 (Tampering: LoopClassification metadata) | 已实现 — get_meta_prompt() 使用硬编码中文模板字符串，不受 LLM 输出污染 |

## Known Stubs

无。

## Self-Check: PASSED

- [x] `src/loopai/state_machine/guards.py` 存在并包含 GuardPipeline, CostGuard, RateLimitGuard, LoopClassification, get_meta_prompt
- [x] `tests/test_guards.py` 存在并包含 TestGuardPipeline, TestCostGuard, TestRateLimitGuard, TestLoopDetectorUpgrade
- [x] 提交 `5da1cdb` 存在
- [x] 提交 `448797a` 存在
- [x] 全部 47 个 guards 测试通过
