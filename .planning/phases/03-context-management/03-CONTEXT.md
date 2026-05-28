# Phase 3: 上下文管理 - Context

**Gathered:** 2026-05-28
**Status:** Ready for planning

## Phase Boundary

本阶段交付 Agent 的上下文窗口管理能力：Token 实时计数、75% 阈值自动压缩（滑动窗口+摘要）、追加式消息存储固化、超长工具输出溢出文件。确保 Agent 在长对话和大量工具调用中不丢失关键上下文，也不让上下文窗口无限制膨胀。

## Implementation Decisions

### 压缩策略
- **D-01:** 滑动窗口+摘要。保留最近 N 轮对话的完整消息，旧消息用 LLM 生成摘要替代。压缩在达到 75% 上下文窗口阈值时自动触发。
- **D-02:** 压缩目标：将上下文从 75% 窗口压缩到 ~50%，为新对话留出空间。

### Token 计数
- **D-03:** 使用 tiktoken（cl100k_base 编码）做近似计数。跨模型误差在 5% 以内，安全 margin 足以保证不溢出。
- **D-04:** 预留 provider-tokenizer 接口，后续可扩展模型专属 tokenizer。

### 溢出文件
- **D-05:** 超长工具输出（>80K 字符）写入溢出文件，上下文中保留文件名引用 `[工具输出已保存至: .sandbox/overflow/xxx.txt (123KB)]`。
- **D-06:** Agent 可用 Bash 工具后续读取溢出文件内容，按需获取详情。

### Claude's Discretion
- 滑动窗口的 N 值（保留最近几轮）
- 摘要 prompt 的具体措辞
- 溢出文件的存储路径和命名规则
- 压缩触发时机（pre-LLM-call 还是 post-tool-result）

## Canonical References

### 项目定义
- `.planning/PROJECT.md` — 项目核心价值和约束
- `.planning/REQUIREMENTS.md` — CTX-01 至 CTX-04 需求定义
- `.planning/ROADMAP.md` — 阶段 3 成功标准

### Phase 1-2 决策（已有接口）
- `.planning/phases/01-agent-core-loop/01-CONTEXT.md` — EventBus、Session、Guards 设计决策
- `.planning/phases/02-tool-system-biz-validation/02-CONTEXT.md` — 工具执行管线、Bash 安全层

### 外部参考
- `src/loopai/tools/executor.py` — 已有的 100KB 输出截断逻辑（可复用）
- `src/loopai/session/context.py` — Session.messages 已实现追加式存储
- OpenAI tiktoken 文档 — cl100k_base 编码器

## Existing Code Insights

### Reusable Assets
- **ToolExecutor._execute_once** (`src/loopai/tools/executor.py:201-229`): 已有 `_MAX_RESULT_BYTES = 100 * 1024` 截断逻辑，Phase 3 可在此基础上叠加溢出文件写入
- **Session.add_message** (`src/loopai/session/context.py:64-112`): 已是追加式设计，不做原地修改，符合 D-?? 追加式存储要求
- **BudgetGuard** (`src/loopai/state_machine/guards.py`): 现有的步数预算守卫可作为 Token 预算守卫的模板

### Established Patterns
- **Append-only message store**: Session.messages 通过 `add_message` 追加，已有消息永不修改
- **Guard pipeline**: BudgetGuard → LoopDetector → MessageValidator 的链式守卫模式，TokenGuard 可复用

### Integration Points
- **FSM._handle_reason** (`src/loopai/state_machine/fsm.py:116-224`): 在 LLM 调用前插入 TokenGuard 检查和压缩触发
- **FSM._handle_act** (`src/loopai/state_machine/fsm.py:226-373`): 在工具执行后检查输出大小，决定是否写溢出文件
- **EventBus**: 压缩事件、token 预算警告事件需新增 event_type

## Specific Ideas

- 压缩后的摘要消息应标记 `[压缩摘要]` 前缀，让下游 agent 知道内容是摘要而非原文
- 每次压缩应发布 `context_compacted` 事件到 EventBus，CLI 渲染器和 JSONL 日志器可消费

## Deferred Ideas

- LLM 自动选择压缩策略（滑动窗口 vs 摘要 vs 混合）— Phase 4/5 考虑
- 跨会话上下文持久化 — Phase 6 Memory 阶段
- Provider 专属 tokenizer（DeepSeek、Anthropic 等）— Phase 6
- 压缩前后 diff 对比（审计用途）— Phase 5 Observability

---

*Phase: 3-上下文管理*
*Context gathered: 2026-05-28*
