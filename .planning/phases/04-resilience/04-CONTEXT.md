# Phase 4: 韧性与恢复 - Context

**Gathered:** 2026-05-28
**Status:** Ready for planning

## Phase Boundary

本阶段在已有的基础守卫（BudgetGuard、LoopDetector、TokenGuard）和基础重试（ToolExecutor 指数退避）之上，构建分层的自愈恢复能力：检查点持久化、循环检测升级（分类+元认知）、失败注册表、守卫管道完善（成本+速率限制）、熔断器。让 Agent 从偶发错误中优雅恢复，不丢失关键状态。

## Implementation Decisions

### 检查点
- **D-01:** JSONL 增量追加模式。每步结束后将 Session 状态序列化为一行 JSON 追加写入检查点文件。恢复时重放最后一条记录。
- **D-02:** 检查点文件与 JSONL 日志共用目录结构，通过 session_id 关联。

### 分层自愈恢复
- **D-03:** 升级现有 ToolExecutor 重试为四层恢复：
  1. **外观修复** — 参数格式修正后重试（如 LLM 给的 JSON 有小错误）
  2. **上下文内重试** — LLM 看到结构化错误信息后自行修正调用
  3. **完整重试+退避** — 已有，IndexError + jitter
  4. **人工升级** — 多次失败后暂停 agent，等用户指令
- **D-04:** 每层有独立的进入条件和升级阈值（连续失败次数）。

### 熔断器
- **D-05:** 滑动窗口计数。最近 N 次调用同一工具，失败率 > 50% 则熔断（open），30s 冷却后放行一次试探（half-open），成功则恢复（closed）。
- **D-06:** 熔断状态变化发布事件到 EventBus（circuit_opened / circuit_closed）。

### Claude's Discretion
- 滑动窗口 N 值和冷却时间
- 检查点序列化字段选择
- 四层恢复的具体阈值参数
- 失败注册表的存储格式

## Canonical References

### 项目定义
- `.planning/PROJECT.md` — 核心价值和约束
- `.planning/REQUIREMENTS.md` — RES-01 至 RES-06
- `.planning/ROADMAP.md` — 阶段 4 成功标准

### 已有接口
- `.planning/phases/03-context-management/03-CONTEXT.md` — TokenGuard 接口（Phase 4 扩展为 GuardPipeline）
- `src/loopai/tools/executor.py` — 现有重试逻辑（Phase 4 升级为分层恢复）
- `src/loopai/state_machine/guards.py` — BudgetGuard、LoopDetector、TokenGuard（Phase 4 新增 CostGuard、RateLimitGuard）
- `src/loopai/tools/errors.py` — 现有 ErrorCategory 枚举

## Existing Code Insights

### Reusable Assets
- **TokenGuard** (`src/loopai/state_machine/guards.py`): 守卫模式模板，CostGuard/RateLimitGuard 可复用
- **ToolExecutor._execute_with_retry** (`src/loopai/tools/executor.py:108-163`): 现有重试循环，可扩展为分层恢复
- **LoopDetector** (`src/loopai/state_machine/guards.py`): 已有滑动窗口+签名检测，熔断器可复用窗口模式
- **EventBus** — 熔断状态变化、检查点事件可发布

### Integration Points
- **FSM._handle_act** — 工具执行层，分层恢复和熔断器接入点
- **FSM._handle_reason** — GuardPipeline 接入点（整合 TokenGuard + CostGuard + RateLimitGuard）
- **Session** — 检查点序列化源

## Deferred Ideas

- 跨会话检查点恢复（从历史会话恢复）— Phase 6
- 分布式熔断器（多实例共享状态）— 不在范围内
- 熔断器自动调参 — v2

---

*Phase: 4-韧性与恢复*
*Context gathered: 2026-05-28*
