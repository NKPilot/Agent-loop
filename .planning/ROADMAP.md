# Roadmap: loopAI

## 概览

从零构建 ReAct AI Agent 框架及其 harness 基础设施。遵循依赖链顺序：Agent 循环 -> 工具系统 -> 上下文管理 -> 韧性恢复 -> 可观测性。每个阶段交付一个端到端可用的增量，共 5 个阶段覆盖 31 条 v1 需求。首个业务验证场景（磁盘空间诊断与清理）在阶段 2 进行端到端验证，阶段 5 交付完整的 Web 交互式演示。

**v1.1 动态工具系统：** 阶段 8-11，共 4 个阶段覆盖 26 条 DYN 需求。Agent 能在沙箱内自主编写 Python/Bash 代码，经用户确认后动态注册为新工具。遵循"管道式创建 + 三层防御 + 人工确认门"架构模式。

## 阶段

### v1.0 — Agent 核心框架

- [x] **阶段 1: Agent 核心循环** - 可运行的 ReAct 状态机，LLM 调用，流式输出，步骤控制，基础循环检测，JSONL 日志
- [x] **阶段 2: 工具系统与业务验证** - 工具注册/执行管线、Bash 安全执行、权限分级、重试机制、磁盘清理场景验证
- [x] **阶段 3: 上下文管理** - Token 计数、上下文压缩、追加式存储、溢出文件处理
- [x] **阶段 4: 韧性与恢复** - 检查点、循环检测升级、失败注册表、守卫管道、分层恢复、熔断器
- [x] **阶段 5: 可观测性与 Web 前端** - 事件总线、SSE 实时推流、React 前端面板、会话历史、交互式演示
- [x] **阶段 6: Agent-as-Tool 多 Agent 协作** - Agent 封装为 @tool、子 Agent Session 隔离、调用链可视化
- [ ] **阶段 7: Chat 模式** - 对话式 Chat UI、多轮对话、FSM FINISH_WAIT 状态

### v1.1 — 动态工具系统

- [ ] **阶段 8: 动态工具创建核心 (MVP)** - Agent 提议工具代码、语法检查+危险扫描、前端确认弹窗、自测验证、三级持久化、工具发现
- [ ] **阶段 9: 安全加固与沙箱隔离** - 子进程隔离执行、资源硬限制、网络禁止、文件系统沙箱
- [ ] **阶段 10: 用户体验与工具管理** - 工具管理面板、diff 更新、命名冲突处理、工具发现 UI
- [ ] **阶段 11: 集成验证与优化** - 端到端验证、静态/动态工具并存、恢复管道、JSONL 审计

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
- [x] 05-05-PLAN.md -- Agent Timeline + Session List：SessionList 组件、AgentTimeline+StepCard、ConnectionStatus、键盘导航
- [x] 05-06-PLAN.md -- Tool Detail + Token/Cost + Confirmation：ToolDetail、TokenUsageCard+recharts、ConfirmationDialog（D-06）
- [x] 05-07-PLAN.md -- End-to-End Integration + Production：Start Agent 串联、StaticFiles 生产模式、BIZ-02 端到端验证

### 阶段 6: Agent-as-Tool 多 Agent 协作
**目标**: 将任意 Agent 封装为 @tool，主 Agent 可通过工具调用委托子 Agent，前端展示嵌套调用链
**依赖**: 阶段 5
**需求**: AGT-01, AGT-02, AGT-03, AGT-04, AGT-05, BIZ-03, WEB-01, WEB-02
**成功标准**（必须为真的条件）:
  1. 主 Agent 可将"磁盘分析 Agent"和"清理 Agent"作为工具调用，子 Agent 返回结构化结果
  2. 子 Agent 在独立 Session 中运行，上下文不污染主 Agent；超过独立 budget 或超时后自动终止
  3. Dashboard 展示主 Agent 和子 Agent 的嵌套调用关系，点击子 Agent 调用可展开查看其完整时间线
  4. 磁盘诊断多 Agent 演示全流程跑通：主 Agent 委托分析 + 委托清理
**计划**: 3 plans
**Plans:**
- [x] 06-01-PLAN.md — AgentTool 核心：Agent 桥接为 @tool、独立 Session 隔离、结果结构化回传、超时/预算控制
- [x] 06-02-PLAN.md — 工具集隔离 + 子 Agent 配置：可配置子 Agent 工具范围、BIZ-03 多 Agent 演示
- [x] 06-03-PLAN.md — 前端多 Agent 可视化：调用链组件、子 Agent 时间线展开、事件 Schema 扩展

### 阶段 7: Chat 模式
**目标**: 将 loopAI 从任务模式改造为对话式 Chat 模式——底部输入框、消息气泡流、多轮对话、FSM FINISH_WAIT 状态
**依赖**: 阶段 5, 阶段 6
**需求**: CHAT-01, CHAT-02, CHAT-03, CHAT-04, CHAT-05
**成功标准**（必须为真的条件）:
  1. 用户可以看到纯对话式界面：标题栏 + 消息流 + 底部输入框
  2. 用户发送消息后，Agent 在对话气泡中实时回复（含 Markdown 渲染）
  3. Agent 回复中的工具调用可展开查看参数和结果
  4. 一轮完成后会话保持活跃，用户可以立即发送下一条消息
  5. 现有功能完整保留：Markdown 表格、确认弹窗、Token/成本追踪
**计划**: 2 plans
**Plans:**
- [x] 07-01-PLAN.md — 后端 FINISH_WAIT 状态 + 多轮对话 + 消息 API
- [x] 07-02-PLAN.md — 前端 Chat UI 布局 + 消息气泡 + 输入框

---

### 阶段 8: 动态工具创建核心 (MVP)
**目标**: Agent 能在沙箱内提议工具代码，经语法检查、危险扫描、自测验证后，通过前端确认弹窗由用户审批，按选定持久化级别注册为可用工具，后续 Agent 可通过 system prompt 和 list_tools 发现并调用
**依赖**: 阶段 7
**需求**: DYN-01, DYN-02, DYN-03, DYN-04, DYN-05, DYN-06, DYN-07, DYN-08, DYN-09, DYN-10, DYN-24, DYN-25, DYN-26
**成功标准**（必须为真的条件）:
  1. Agent 通过 `generate_tool` 内置工具提交 Python/Bash 代码后，系统自动执行语法检查（`ast.parse()` / `bash -n`），失败时返回结构化错误让 Agent 修改代码重试
  2. 危险模块/命令扫描（覆盖 30+ 入口）结果标记在确认弹窗中，用户能清楚看到风险提示
  3. 用户可在确认弹窗中查看代码（Monaco Editor 语法高亮只读）、选择持久化级别（会话级/沙箱级/项目级）、指定额外目录权限，确认或拒绝后结果通过 EventBus 回传给 Agent
  4. 语法检查通过后，Agent 在隔离沙箱中执行自测用例验证工具能正常调用并返回预期结果，自测结果（通过/失败/输出日志）展示在确认弹窗中供用户审查
  5. 确认通过的工具按用户选择的持久化级别存储（会话级内存、沙箱级 `.sandbox/tools/`、项目级 `src/loopai/tools/dynamic/`），以 `dynamic.{hash[:8]}_{name}` 命名空间注册到 ToolRegistry，Agent 后续可调用
**计划**: TBD
**Plans**: TBD
**UI hint**: yes

### 阶段 9: 安全加固与沙箱隔离
**目标**: 动态工具在独立子进程中执行，受 `resource.setrlimit` 硬限制（CPU、内存 512MB、超时 30s）和文件系统隔离保护，确保 Agent 生成的代码不会影响主进程稳定性，无法访问网络
**依赖**: 阶段 8
**需求**: DYN-11, DYN-12, DYN-13, DYN-14
**成功标准**（必须为真的条件）:
  1. 动态工具在独立子进程（`subprocess`）中执行，与主进程完全隔离，工具崩溃不影响 Agent 循环
  2. 子进程受 `resource.setrlimit` 硬限制：CPU 时间、内存上限 512MB、超时 30s（可调至 120s），超限进程被 SIGKILL 强制终止
  3. 子进程无法访问网络，尝试网络连接的操作被阻止并返回明确错误信息
  4. 文件系统访问默认限于 `.sandbox/tools_runtime/{tool_name}/` 子目录，无法读取或写入沙箱外路径；用户可在确认时授予额外目录权限
**计划**: TBD
**Plans**: TBD

### 阶段 10: 用户体验与工具管理
**目标**: 用户可通过前端"动态工具"面板集中管理所有动态工具——查看代码、启用/禁用、删除、diff 更新对比、命名冲突处理。工具发现系统确保 Agent 始终知晓可用动态工具
**依赖**: 阶段 8
**需求**: DYN-15, DYN-16, DYN-17, DYN-18, DYN-19, DYN-20, DYN-21, DYN-22, DYN-23
**成功标准**（必须为真的条件）:
  1. 用户在侧边栏"动态工具"tab 中可查看所有动态工具列表，包括名称、描述、持久化级别 Badge 和启用/禁用状态
  2. 用户点击工具项可查看完整代码（Monaco Editor 语法高亮只读）；禁用工具后，该工具不出现在 system prompt 且不可被 Agent 调用
  3. 用户可删除动态工具（含确认弹窗），系统根据持久化级别自动清理对应存储
  4. Agent 提交已有工具的新版本时，前端展示新旧代码 side-by-side Monaco DiffEditor，用户选择覆盖或拒绝；命名冲突时同样展示对比供用户决策
  5. 系统启动时自动扫描并加载所有持久化动态工具，工具名和描述注入 system prompt；Agent 可通过 `list_tools` 内置工具查询所有动态工具的详细信息（含完整 Schema）
**计划**: TBD
**Plans**: TBD
**UI hint**: yes

### 阶段 11: 集成验证与优化
**目标**: 端到端验证动态工具系统与 v1.0 所有子系统的完整集成——静态/动态工具并存、恢复管道兼容、JSONL 审计完整、异常恢复可靠、性能达标
**依赖**: 阶段 9, 阶段 10
**需求**: （集成验证阶段——无独立 DYN 需求，验证前述 DYN-01 至 DYN-26 的端到端集成）
**成功标准**（必须为真的条件）:
  1. 端到端业务场景跑通：Agent 发现磁盘问题 → 自主生成诊断工具 → 用户确认 → 工具注册 → Agent 调用动态工具 → 完成诊断并返回结果，全流程无需手动干预 Agent 循环
  2. 静态工具（`@tool` 装饰器）和动态工具（`dynamic.` 命名空间）在同一会话中共存且互不干扰，ToolRegistry 分区隔离正常，动态工具不可覆盖静态工具
  3. 动态工具执行失败时，复用现有 ToolExecutor 4 层恢复管道（外观修复 → 上下文内重试 → 完整重试 + 退避 → 人工升级），不会导致 Agent 循环崩溃
  4. 会话关闭时根据持久化级别正确清理：会话级工具从内存移除、沙箱级和项目级工具保留并在下次启动时自动加载
  5. JSONL 日志完整区分 `dynamic_tool_created` 和 `dynamic_tool_executed` 事件，审计轨迹完整可追溯；动态工具代码长度计入 token 统计
**计划**: TBD
**Plans**: TBD

## 进度

| 阶段 | 计划完成 | 状态 | 完成日期 |
|------|----------|------|----------|
| 1. Agent 核心循环 | 5/5 | 完成 | - |
| 2. 工具系统与业务验证 | 4/4 | 完成 | - |
| 3. 上下文管理 | 3/3 | 完成 | 2026-05-28 |
| 4. 韧性与恢复 | 3/3 | 完成 | - |
| 5. 可观测性与 Web 前端 | 7/7 | 完成 | 2026-05-30 |
| 6. Agent-as-Tool | 3/3 | 完成 | 2026-05-30 |
| 7. Chat 模式 | 0/2 | 进行中 | - |
| 8. 动态工具创建核心 (MVP) | 0/0 | 未开始 | - |
| 9. 安全加固与沙箱隔离 | 0/0 | 未开始 | - |
| 10. 用户体验与工具管理 | 0/0 | 未开始 | - |
| 11. 集成验证与优化 | 0/0 | 未开始 | - |
