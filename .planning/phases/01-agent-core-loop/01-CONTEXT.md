# 阶段 1: Agent 核心循环 — 上下文

**收集时间:** 2026-05-27
**状态:** 待规划

<domain>
## 阶段边界

本阶段交付可运行的 ReAct 状态机——LLM 调用、流式输出、步骤控制、基础循环检测、JSONL 会话日志。这是整个 agent 框架的地基，后续所有阶段的代码都建立在这个循环之上。

覆盖需求: CORE-01 至 CORE-07（7 条）
</domain>

<decisions>
## 实现决策

### 状态机设计
- **D-01:** REASON 状态下，LLM 返回纯文本（无 tool_calls）时，直接转换到 FINISH。遵循 OpenAI function calling 原生行为——模型在一次调用中要么返回 tool_calls，要么返回最终答案，不存在"空 ACT"的情况。
- **D-02:** 状态机五个状态: REASON → ACT → OBSERVE → FINISH → ERROR。REASON 是入口，每次循环从 REASON 开始。

### 流式输出
- **D-03:** 双粒度事件——步骤级事件（step_start, step_end）+ Token 级实时输出（llm_token）。CLI 可逐字打印，Web 前端可实时渲染思考过程。
- **D-04:** 分层事件结构——顶层生命周期事件包裹内层子事件流。每个步骤内嵌套 token 流和工具调用事件。
- **D-05:** 基于 `asyncio.Queue` 的内部 Event Bus（发布-订阅模式）。三个消费者: CLI（Rich 终端渲染）、JSONL Logger（结构化日志）、SSE 端点（Phase 5 使用但架构上现在预留）。

### 步骤控制与终止
- **D-06:** 默认最大步骤数: 15-20 步。磁盘诊断等典型场景 10-15 步足够，留有余量。
- **D-07:** 预算耗尽行为: 最后一轮摘要机会——给 LLM 注入提示"预算已用完，请基于当前信息给出最终答案"，然后强制终止。
- **D-08:** "目标不可达成"判定: 系统规则检测 + LLM 自判两者结合。系统检测硬信号（连续失败、用户拒绝），LLM 也可主动声明不可达成。
- **D-09:** 80% 预算预警: 向 LLM 上下文注入提醒提示——"步骤预算已使用 80%，请在后续步骤中优先给出结论"。

### JSONL 日志
- **D-10:** 事件流记录——JSONL 每行对应事件总线的一个事件，1:1 映射。支持完整会话回放。
- **D-11:** 每会话一个文件，按 `session_id` + 时间戳命名。如 `logs/sessions/2026-05-27_14a3f2.jsonl`。

### Claude 可自行决定
以下领域未在讨论中锁定，规划者和研究者可自主选择合理方案:
- ERROR 状态是终态还是可恢复状态
- 状态转换失败时的处理策略
- 事件 Schema 的具体字段定义（按分层结构自行设计）
- 循环检测的干预策略细节（CORE-06）
- 消息结构校验的严格程度（CORE-05）
- LLM 配置方式（环境变量 vs 配置文件 vs CLI 参数）
</decisions>

<canonical_refs>
## 规范参考

**下游 agent 在规划或实现前必须阅读以下文件:**

### 项目级文档
- `.planning/ROADMAP.md` — 阶段定义、依赖关系、成功标准
- `.planning/REQUIREMENTS.md` — CORE-01 至 CORE-07 完整需求描述及可追溯性矩阵
- `.planning/PROJECT.md` — 项目核心价值、技术栈决策、约束条件
- `CLAUDE.md` — 推荐技术栈详情、版本兼容性、替代方案对比

### 阶段 1 需求
- `CORE-01`: ReAct 状态机（REASON → ACT → OBSERVE → FINISH → ERROR）
- `CORE-02`: OpenAI 兼容 API 调用（可配置 base_url, api_key, model）
- `CORE-03`: 流式输出（async generator/SSE）
- `CORE-04`: 步骤预算 + 终止条件（80% 预警）
- `CORE-05`: 消息结构交替校验（tool_call 和 tool_result 必须成对）
- `CORE-06`: 基础循环检测（同一工具连续调用 3 次以上触发干预）
- `CORE-07`: JSONL 日志记录（从第一轮开始）
</canonical_refs>

<code_context>
## 现有代码洞察

### 可复用资产
- 无——全新项目，无现有代码。

### 已有模式
- 无——首次编码阶段，模式将在实现过程中建立。

### 集成点
- `CLAUDE.md` 已定义技术栈: Python 3.13 + `openai` SDK 2.38 + `asyncio` + `rich` 15.0
- 推荐使用 `uv` 管理 Python 依赖
</code_context>

<specifics>
## 具体想法

讨论中用户提及:
- 偏好成熟、经过验证的做法——"有什么成熟的做法吗"
- 倾向于实际工程考量（多消费者、改动成本、后续兼容性）
</specifics>

<deferred>
## 延期想法

无——讨论保持在阶段范围内。
</deferred>

---

*阶段: 1-Agent 核心循环*
*上下文收集时间: 2026-05-27*
