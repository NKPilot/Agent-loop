# loopAI

## 这是什么

一个基于 ReAct（Reasoning + Acting）范式的 AI Agent 框架。核心不是 agent 循环本身，而是围绕循环的工程化基础设施（harness）：工具抽象、上下文组织、错误恢复、执行边界。附带 Web 前端用于实时展示 agent 的思考链路、工具调用和状态变化。

**v1.0 已交付：** 单 Agent ReAct 循环 + 工具系统 + 上下文管理 + 韧性恢复 + Web 可观测性 Dashboard。首个业务验证场景为磁盘空间诊断与清理。

**v2.0 方向：** 多 Agent 协作——Agent-as-Tool 模式，主 Agent 可委托子 Agent 执行专项任务。仍以磁盘诊断为验证场景。

## 核心价值

让 AI Agent 不仅"能跑"，而且可靠、可观测、可扩展——从 harness 设计的深度思考出发，构建值得信任的 agent 系统。

## 核心设计目标

loopAI 的核心目标不是简单调用 LLM，而是跑通一条可观察、可恢复、可测试的 Agent 执行链路：

用户目标 → ReActFSM → LLM 决策 → 工具调用 → 观察结果 → 下一步 → 终止/追问 → 日志和前端可见

这条链路应满足：

- 每一步都有明确状态和结构化事件记录
- 工具调用结果能反馈给下一轮推理
- 失败路径可恢复、可审计
- CLI、JSONL 日志、Web 前端能观察同一条运行轨迹
- 多轮对话中 Agent 可以终止，也可以主动追问

## 需求

### 已验证（v1.0）

- ✓ ReAct 状态机 + LLM 调用 + 流式输出 + JSONL 日志 — Phase 1
- ✓ @tool 装饰器 + Bash 安全层 + 权限分级 + 错误分类/重试 — Phase 2
- ✓ 磁盘清理完整流程（含危险确认）— Phase 2
- ✓ Token 计数 + 上下文压缩 + 追加式存储 + 溢出文件 — Phase 3
- ✓ 检查点 + 熔断器 + GuardPipeline + 四层恢复 — Phase 4
- ✓ Web 可观测性 Dashboard（SSE + React + 时间线 + 确认弹窗）— Phase 5

### 进行中（v2.0）

- [ ] Agent-as-Tool：把 Agent 封装为可被主 Agent 调用的 Tool
- [ ] 子 Agent Session 隔离：每个子 Agent 调用有独立的 Session 和上下文
- [ ] 结果回传：子 Agent 完成后将结果结构化传回主 Agent
- [ ] 超时/预算控制：子 Agent 有独立的 step budget 和超时
- [ ] 磁盘诊断验证：主 Agent 委托"磁盘分析 Agent"和"清理 Agent"完成任务
- [ ] v2 Web 前端展示：Dashboard 可视化多 Agent 调用链

### 不在范围内

- 生产级部署 — 学习探索项目，不追求生产可用性
- 对接所有 LLM 提供商 — 先支持 OpenAI 兼容接口
- Agent 自主安装工具包 — 安全风险

## 上下文

- 学习驱动项目，通过实践深入理解 Agent 架构和 harness 设计
- Python 后端 + React Web 前端
- DeepSeek 兼容（OpenAI-compatible API）
- v1 业务验证：磁盘空间诊断与清理 ✓

## 约束

- **技术栈**: Python 3.12+, React 19 + Vite 8 + Tailwind 4
- **LLM 接口**: OpenAI 兼容 API
- **安全**: 危险操作必须有确认机制
- **语言**: 文档和代码注释使用中文

## 关键决策

| 决策 | 理由 | 结论 |
|------|------|------|
| 深度方向分层推进 | 各方向有依赖关系，地基先行 | ✓ 已实施 |
| Agent-as-Tool 模式 | 复用现有 @tool 基础设施，最务实的多 Agent 入口 | v2.0 |
| 磁盘诊断作为验证场景 | 对 harness 各维度验证最全面 | 延续使用 |
| 子 Agent Session 独立 | 避免上下文污染，便于调试和回放 | v2.0 |

## 演进

本文档随阶段转换和里程碑边界演进。

---
*最后更新: 2026-06-03 补充核心 Agent 执行链路设计目标*
