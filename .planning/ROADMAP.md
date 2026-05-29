# Roadmap: loopAI

## 概览

从零构建 ReAct AI Agent 框架及其 harness 基础设施。遵循依赖链顺序：Agent 循环 -> 工具系统 -> 上下文管理 -> 韧性恢复 -> 可观测性。每个阶段交付一个端到端可用的增量，共 5 个阶段覆盖 31 条 v1 需求。首个业务验证场景（磁盘空间诊断与清理）在阶段 2 进行端到端验证，阶段 5 交付完整的 Web 交互式演示。

## 阶段

- [ ] **阶段 1: Agent 核心循环** - 可运行的 ReAct 状态机，LLM 调用，流式输出，步骤控制，基础循环检测，JSONL 日志
- [ ] **阶段 2: 工具系统与业务验证** - 工具注册/执行管线、Bash 安全执行、权限分级、重试机制、磁盘清理场景验证
- [ ] **阶段 3: 上下文管理** - Token 计数、上下文压缩、追加式存储、溢出文件处理
- [ ] **阶段 4: 韧性与恢复** - 检查点、循环检测升级、失败注册表、守卫管道、分层恢复、熔断器
- [ ] **阶段 5: 可观测性与 Web 前端** - 事件总线、SSE 实时推流、React 前端面板、会话历史、交互式演示

## 阶段详情

### 阶段 1: Agent 核心循环
**目标**: 可运行的 ReAct 状态机，支持 LLM 调用、流式输出、步骤控制、基础循环检测和会话日志
**依赖**: 无（第一阶段）
**需求**: CORE-01, CORE-02, CORE-03, CORE-04, CORE-05, CORE-06, CORE-07
**成功标准**（必须为真的条件）:
  1. 用户可以通过 CLI 启动 agent 会话，agent 能完成简单的问答（无需工具调用）
  2. Agent 的思考、行动、观察步骤在终端中实时流式输出，步骤间清晰可见
  3. Agent 在达到步骤预算时自动终止并返回最终答复；在检测到同一工具连续调用 3 次以上时触发干预
  4. 消息结构校验确保 tool_call 和 tool_result 成对出现，孤立 tool_call 被拦截
  5. 每次会话从第一轮开始即生成 JSONL 结构化日志文件，可在文件系统中找到
**计划**: 5 plans
**Plans:**
- [x] 01-01-PLAN.md — EventBus 基础设施：项目脚手架、事件 Schema、asyncio.Queue 发布订阅
- [x] 01-02-PLAN.md — 守卫与配置：BudgetGuard、LoopDetector、MessageValidator、AgentConfig
- [x] 01-03-PLAN.md — LLM 集成：LLMClient（OpenAI beta streaming）、Session 状态容器
- [x] 01-04-PLAN.md — 事件消费者：JSONL 日志记录器、Rich CLI 实时渲染器
- [x] 01-05-PLAN.md — 状态机与会话编排：ReActFSM、CLI 入口点、优雅关闭

### 阶段 2: 工具系统与业务验证
**目标**: 工具注册与执行管线、Bash 安全执行、权限分级、错误分类与重试，以及磁盘清理业务场景的端到端验证
**依赖**: 阶段 1
**需求**: TOOL-01, TOOL-02, TOOL-03, TOOL-04, TOOL-05, TOOL-06, TOOL-07, BIZ-01
**成功标准**（必须为真的条件）:
  1. 用户可以通过 `@tool` 装饰器将任意 Python 函数注册为 agent 工具，系统自动从 type hints + docstring 生成 JSON Schema
  2. Agent 能调用 Bash 工具执行 `df`、`du`、`find` 等命令，结果安全返回并结构化注入上下文
  3. 执行 `rm`、`dd`、`mkfs` 等危险命令时，agent 暂停执行并等待用户确认后才继续
  4. 工具执行遇到瞬时错误（如 NetworkError）时，系统自动按指数退避 + 随机抖动重试
  5. 磁盘空间诊断与清理全流程跑通：agent 扫描磁盘 -> 定位大文件 -> 分析安全性 -> 请求确认 -> 清理，用户可通过终端交互完成
**计划**: 4 plans
**Plans:**
- [x] 02-01-PLAN.md — 工具系统基础：类型定义、@tool 装饰器（自动 Schema 生成）、ToolRegistry、执行管线（含错误分类+重试）
- [x] 02-02-PLAN.md — Bash 工具与权限系统：命令分类器（白名单/黑名单+路径感知）、BashTool（安全 subprocess）、PermissionGuard
- [x] 02-03-PLAN.md — FSM 集成与 CLI 确认：事件 Schema 扩展、ReActFSM 重构（真实工具管线）、CLI 确认交互
- [x] 02-04-PLAN.md — 磁盘清理业务验证：4 磁盘工具注册、预设沙箱场景、端到端流程测试

### 阶段 3: 上下文管理
**目标**: Token 计数、上下文压缩、追加式存储、溢出文件处理，确保上下文窗口不会无限制膨胀
**依赖**: 阶段 2
**需求**: CTX-01, CTX-02, CTX-03, CTX-04
**成功标准**（必须为真的条件）:
  1. 系统实时追踪每次 LLM 调用的 token 消耗，当上下文达到 75% 窗口阈值时自动触发压缩
  2. 上下文压缩后，旧消息被摘要替代、工具输出被截断、过期历史被移除，LLM 仍能正常运行
  3. 超长工具输出（>80K 字符）自动写入溢出文件而非截断到上下文中，agent 仍可引用
  4. 所有消息操作（包括压缩）均为追加式，不做原地修改，审计轨迹完整可追溯
**计划**: 3 plans
**Plans:**
- [x] 03-01-PLAN.md — Token 计数 + 溢出文件 + 事件 Schema：TokenCounter（tiktoken）、ToolExecutor 溢出文件写入、ContextCompacted/TokenWarning 事件类型
- [x] 03-02-PLAN.md — 上下文压缩 + Token 守卫：ContextCompressor 滑动窗口摘要、TokenGuard 阈值检测
- [x] 03-03-PLAN.md — FSM 集成 + 追加式固化：TokenGuard/Compressor/溢出文件集成到 ReActFSM 的 _handle_reason 和 _handle_act

### 阶段 4: 韧性与恢复
**目标**: 检查点、循环检测升级、失败注册表、守卫管道、分层恢复、熔断器，确保 agent 运行的可靠性
**依赖**: 阶段 3
**需求**: RES-01, RES-02, RES-03, RES-04, RES-05, RES-06
**成功标准**（必须为真的条件）:
  1. Agent 崩溃后可从上一次检查点恢复，不丢失关键状态
  2. 同一工具重复调用 3 次以上时，系统触发基于分类的干预策略并附加元认知提示，agent 改变行为
  3. 曾经失败的操作被注册到"不再重复"列表，同一会话中 agent 不会再次尝试该操作
  4. Token 预算、成本、速率限制守卫有效拦截越界操作，agent 收到明确守卫违规反馈
  5. 某工具连续失败达到阈值后，熔断器自动暂停该工具；暂停期间 agent 不会收到该工具的调用选项
**计划**: 3 plans
**Plans:**
- [x] 04-01-PLAN.md — 韧性子系统基础：事件 Schema + CheckpointManager + FailureRegistry + CircuitBreaker
- [x] 04-02-PLAN.md — 守卫管道（GuardPipeline + CostGuard + RateLimitGuard）+ LoopDetector 升级（分类 + 元认知）
- [x] 04-03-PLAN.md — 4 层恢复 + Registry 过滤 + FSM 集成 + main.py 更新

### 阶段 5: 可观测性与 Web 前端
**目标**: 事件总线、SSE 实时推流、React Web 前端展示、Token/成本追踪、会话历史浏览，以及完整的交互式演示
**依赖**: 阶段 4
**需求**: OBS-01, OBS-02, OBS-03, OBS-04, OBS-05, BIZ-02
**成功标准**（必须为真的条件）:
  1. 用户打开浏览器即可看到 agent 实时思考步骤、工具调用卡片（含状态标记）和状态变化——操作无需刷新页面
  2. 每次 LLM 调用的 token 消耗和预估成本在前端面板实时展示
  3. 用户可以浏览历史 agent 会话记录，查看过去任意会话的完整步骤
  4. 磁盘清理演示全流程可通过网页交互完成，包括危险操作的确认弹窗和实时状态反馈
**计划**: 7 plans
**Plans:**
- [x] 05-01-PLAN.md -- FastAPI Backend + SSE Bridge：应用工厂、CORS、SSE 桥接消费者、流端点、测试脚手架
- [x] 05-02-PLAN.md -- Session REST + Agent Control API：会话 CRUD、启动/确认端点、组件工厂提取、集成测试
- [x] 05-03-PLAN.md -- Frontend Scaffold：Vite 项目 + 依赖安装 + shadcn/ui 初始化
- [x] 05-04-PLAN.md -- Frontend Layout + Data Pipeline：三面板布局、TypeScript 事件类型、useSSE hook、Zustand stores
- [ ] 05-05-PLAN.md -- Agent Timeline + Session List：SessionList 组件、AgentTimeline+StepCard、ConnectionStatus、键盘导航
- [ ] 05-06-PLAN.md -- Tool Detail + Token/Cost + Confirmation：ToolDetail、TokenUsageCard+recharts、ConfirmationDialog（D-06）
- [ ] 05-07-PLAN.md -- End-to-End Integration + Production：Start Agent 串联、StaticFiles 生产模式、BIZ-02 端到端验证

## 进度

| 阶段 | 计划完成 | 状态 | 完成日期 |
|------|----------|------|----------|
| 1. Agent 核心循环 | 5/5 | 完成 | - |
| 2. 工具系统与业务验证 | 4/4 | 完成 | - |
| 3. 上下文管理 | 3/3 | 完成 | 2026-05-28 |
| 4. 韧性与恢复 | 0/3 | 进行中 | - |
| 5. 可观测性与 Web 前端 | 0/0 | 未开始 | - |
