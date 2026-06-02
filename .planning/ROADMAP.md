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
**计划**: 3 plans
**Plans**:
- [ ] 09-01-PLAN.md — 事件 Schema 契约：新增 sandbox_timeout/sandbox_violation/sandbox_resource_exceeded 事件类型（Python + TypeScript 同步）
- [ ] 09-02-PLAN.md — SandboxExecutor 三层加固：unshare 网络隔离 + 路径白名单校验 + rlimit 升级（DYN-11~DYN-14）
- [ ] 09-03-PLAN.md — DynamicToolCreator 集成：加固沙箱替换自测执行器 + D-06 闭合

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
**计划**: 3 plans
**Plans**:
- [x] 10-01-PLAN.md — 后端核心：ToolMetadata.enabled + Registry 过滤 + meta.json 持久化 + 事件类型 + 启动加载
- [ ] 10-02-PLAN.md — 后端 API：工具管理 REST 端点 + DynamicToolCreator 更新检测 + list_tools 内置工具
- [ ] 10-03-PLAN.md — 前端 UI：ToolManagementPanel 侧边栏 + ToolCreationDialog 更新模式（DiffEditor）
**UI hint**: yes
