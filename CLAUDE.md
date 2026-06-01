<!-- GSD:project-start source:PROJECT.md -->
## 项目

**loopAI**
<!-- GSD:project-end -->

<!-- GSD:stack-start source:research/STACK.md -->
## 技术栈

### 核心技术
| 技术 | 版本 | 用途 | 选型理由 |
|------|------|------|----------|
| **Python** | 3.13.x | 运行时 | 最新稳定版，asyncio 大幅改进：重新设计的事件循环调度器（O(log n) 任务操作），实验性 io_uring 后端（减少 60% 系统调用），自由线程模式（PEP 703）。所有库均支持 3.13。 |
| **openai** | 2.38.0 | LLM 客户端 | 官方 OpenAI SDK。直接使用（不通过封装层）以保持对 agent 循环的完全控制。v2 SDK 具有成熟的流式、工具调用和响应 API。异步客户端（`openai.AsyncOpenAI`）是一等公民。 |
| **FastAPI** | 0.136.3 | Web 框架 | 异步 Python API 的标准选择。原生 SSE 支持（`EventSourceResponse`）、WebSocket 支持、自动 Pydantic 校验、OpenAPI 文档。用于向仪表盘实时推送 agent 状态。 |
| **Pydantic** | 2.13.4 | 数据模型 | Python 数据校验的行业标准。支撑 FastAPI 和 Pydantic AI。用于工具 schema、agent 状态模型和结构化输出。Rust 核心（`pydantic-core`）比 v1 快 5-50 倍。 |
| **React** | 19.x | 前端 UI | React Compiler 已稳定，自动 memoization（不再需要手动 `useMemo`/`useCallback`）。`use()` API 用于异步数据读取。用于构建带实时事件渲染的可观测性仪表盘。 |
| **TypeScript** | 5.7+ | 前端语言 | 仪表盘的类型安全。在编译期捕获 SSE 事件与 UI 组件之间的数据形状不匹配。 |
| **Vite** | 8.0.14 | 前端构建工具 | Rolldown（基于 Rust 的打包器）替代 Rollup，构建速度大幅提升。通用插件系统。2024 年以来新 React 项目的实际标准。 |
| **Tailwind CSS** | 4.3.0 | 前端样式 | CSS-first 配置（无需 `tailwind.config.js`）。Oxide 引擎实现 5 倍构建速度提升。`@theme` 指令定义设计 token。适合快速构建自定义仪表盘 UI，无需与组件库纠缠。 |

### Agent 循环 — 方案决策

**从零构建。** Agent 循环是手写的 ReAct 有限状态机（`ReActFSM`）——一个 `while` 循环在 REASON → ACT → OBSERVE 状态间轮转，加上 FINISH_WAIT 支持多轮对话，ERROR 表示终止状态。不使用 LangChain、LangGraph、CrewAI。循环通过薄封装 `LLMClient` 与 LLM 通信（底层是 OpenAI SDK），将结构化事件发送到 `EventBus` 供解耦的消费者（CLI 渲染器、JSONL 日志、SSE 桥接）订阅。

**为什么从零构建：** 核心目标是 harness engineering 学习——理解 agent 系统的每一层。亲手构建循环、工具系统、守卫和恢复管道，才能直接面对框架替你隐藏的设计决策。

### Python 后端辅助库
| 库 | 版本 | 用途 | 使用场景 |
|----|------|------|----------|
| **httpx** | 0.28.x | 异步 HTTP 客户端 | `openai` 的依赖（用于 API 调用）。也可用于工具的任意 HTTP 请求。 |
| **psutil** | 7.2.2 | 系统监控 | 磁盘空间诊断（首个业务场景）。无需 shell 调用 `df`/`du`，直接提供 `disk_usage()`、`disk_partitions()`、`disk_io_counters()`。跨平台。 |
| **rich** | 15.0.0 | CLI 显示 | 终端/CLI 模式下渲染 agent 思考过程。渲染表格、markdown、语法高亮。Web 仪表盘的替代方案。 |
| **asyncio** | (标准库) | 异步运行时 | Python 3.13 包含改进的任务调度（二叉堆优先队列）、优化的取消机制和实验性 io_uring。 |
| **subprocess** | (标准库) | Bash 执行 | 使用 `subprocess.run(args_list, timeout=N, capture_output=True)` 且 `shell=False`。严禁对 LLM 生成的命令使用 `shell=True`。 |
| **shlex** | (标准库) | 命令安全 | `shlex.quote()` 和 `shlex.split()` 用于安全处理用户/LLM 提供的命令字符串。 |
| **json** | (标准库) | 序列化 | Agent 状态持久化到 JSONL。对于学习项目比 SQLite 更简单。JSONL 日志 = 内置审计追踪。 |

### 前端辅助库
| 库 | 版本 | 用途 | 使用场景 |
|----|------|------|----------|
| **shadcn/ui** | CLI v4 | UI 组件库 | 复制即拥有的组件。Card、Dialog、Badge、Tooltip 用于仪表盘。无 npm 依赖——代码在你的仓库中。 |
| **@tanstack/react-query** | 5.100.14 | 服务端状态管理 | Agent 会话状态、历史缓存。`queryClient.setQueryData()` 用于 SSE 事件的乐观更新。 |
| **zustand** | 5.x | 客户端状态管理 | 仪表盘 UI 状态（选中的 agent 运行、筛选设置、主题切换）。比 Redux 更简单，无样板代码。 |
| **recharts** | 2.x | 图表 | 磁盘使用可视化（分区用量饼图/柱状图，I/O 时序折线图）。React 友好的 API。 |
| **lucide-react** | (latest) | 图标 | 干净统一的图标集，shadcn/ui 使用。disk、terminal、alert 图标用于仪表盘。 |

### 开发工具
| 工具 | 用途 | 备注 |
|------|------|------|
| **uv** | Python 包管理器 | 比 pip 快 10-100 倍。`uv pip install` 或 `uv sync` 管理依赖。基于 Rust，可替代 pip + venv。 |
| **pytest** | Python 测试 | 通过 `pytest-asyncio` 支持异步。测试 agent 循环、工具执行、沙箱的必需品。 |
| **pytest-asyncio** | 异步测试支持 | 用 `@pytest.mark.asyncio` 标记异步测试。测试 agent 循环的必需品。 |
| **ruff** | Python 格式化/检查 | 比 flake8 + isort + black 快 100 倍。单一工具，零配置。 |
| **mypy** | Python 类型检查 | 严格模式捕获工具 schema 和 agent 状态中的数据形状不匹配。 |
| **node** (22.x+) | JS 运行时 | Vite 8 要求。使用最新 LTS。 |
| **pnpm** | JS 包管理器 | 比 npm 更快，基于内容寻址存储的磁盘效率更高。 |

## 安装

```bash
# 克隆并安装所有依赖
make install

# 或手动安装：
uv sync                          # Python 后端 + 开发依赖
cd frontend && pnpm install      # 前端

# 配置环境变量
cp .env.example .env             # 编辑填入 API key/model
```

### 运行

```bash
make dev       # 并行启动后端 (端口 8000) + 前端 (端口 5173)
make start     # 后台模式（PID 文件）
make stop      # 停止后台进程
make test      # 单元测试
make test-all  # 全部测试，含 API 集成测试
make demo      # 搭建沙箱演示场景
```

## 方案对比

| 推荐方案 | 替代方案 | 何时用替代方案 |
|----------|----------|----------------|
| **从零构建 agent 循环** | **Pydantic AI v1.103.0** | 如果快速迭代 > 学习深度。Pydantic AI 提供类型安全的工具抽象、事件流、依赖注入。v2 beta 已可用但尚未稳定。 |
| **从零构建 agent 循环** | **OpenAI Agents SDK v0.7+** | 如果需要加速走向多 agent 和 handoff。锁定 OpenAI。抽象层极薄，但增加了 handoff 模型和内置追踪。 |
| **从零构建 agent 循环** | **LangChain / LangGraph** | 永不。重度抽象，频繁破坏性变更，隐藏 prompt 注入。与 harness engineering 的学习目标直接冲突。 |
| **FastAPI** | **Django + Channels** | 如果需要 Django ORM、admin 面板、生态系统。对此项目过重。Channels 比 FastAPI 原生 SSE 更复杂。 |
| **React + Vite** | **Next.js** | 如果需要 SSR、文件路由、前后端一体。单页仪表盘不需要。 |
| **shadcn/ui** | **MUI (Material UI)** | 如果需要全面、有主见的设计系统和预建复杂组件（数据表格、日期选择器）。MUI 包体更大且组件不属于你。 |
| **SSE** | **WebSocket** | 如果仪表盘需要双向通信（如在 agent 运行中发送命令）。对于单向观察，SSE 更简单。 |

## 禁止使用

| 避免 | 原因 | 替代方案 |
|------|------|----------|
| **LangChain** | 重度抽象掩盖 agent 循环内部机制。频繁破坏性变更。隐藏 prompt 工程。直接违背学习 harness 设计的目标。 | 直接用 `openai` SDK |
| **LangGraph** | 图编排对单 agent 系统是过度设计。增加了状态机复杂度，而简单的 `while` 循环完全够用。 | `while` 循环 + 手动状态 |
| **CrewAI** | 多 agent 编排超出当前范围。基于角色的设计难以定制。 | 需要多 agent 时从零构建 |
| **Django** | 同步 ORM，对轻量 API 来说框架太重。Channels 增加实时通信的复杂度。 | FastAPI |
| **Flask** | 仅支持同步。无原生 async/await，需要扩展。 | FastAPI |
| **Redux** | 仪表盘状态（选中运行、筛选、主题）不需要那么多样板代码。 | Zustand |
| **Styled Components** | 运行时 CSS-in-JS 增加包体积和运行时开销。比 utility CSS 慢。 | Tailwind CSS |
| **Celery** | 分布式任务队列对单进程 agent 是过早架构。 | `asyncio.create_task()` |
| **SQLAlchemy** | 对 JSONL 日志来说 ORM 是过度设计。学习项目不需要 schema 迁移。 | JSONL 日志，简单文件存储 |
| **Docker**（初始阶段） | 在核心逻辑稳定之前增加运维复杂度。先学会，再容器化。 | 虚拟环境 |
| **`shell=True`** | 通过 LLM 生成的字符串注入命令。LLM 可能生成 `; rm -rf /`。 | `subprocess.run([cmd, arg1, arg2], timeout=N)` 且 `shell=False` |
| **`eval()` / `exec()`** | 任意代码执行。LLM 输出永远不应被求值执行。 | `json.loads()` 处理结构化数据，`shlex.split()` 处理命令 |

## 已实现与未来规划

### 已实现
- ✅ **ReAct Agent 循环** — 手写 `ReActFSM`，REASON→ACT→OBSERVE 状态流转
- ✅ **事件驱动发布/订阅** — `EventBus` 基于 asyncio.Queue，支持重放和多消费者
- ✅ **守卫管道** — 可组合的安全检查（预算、循环检测、token、成本、速率限制）
- ✅ **Agent 作为工具** — 子 agent 通过 `AgentTool` 桥接封装为工具
- ✅ **JSONL 审计追踪** — 每个事件一行 JSON，完整会话可重放
- ✅ **对话模式** — 多轮对话，FINISH_WAIT 状态支持
- ✅ **SSE 流式推送** — 通过 EventSourceResponse 实时推送 agent 状态到 React 仪表盘
- ✅ **共享组件工厂** — `create_agent_components()` 确保 CLI 和 Web 路径一致

### 未来 / 可选
- **WebSocket** — 双向通信（FastAPI 原生 `@app.websocket("/ws")`）
- **多 Provider 适配器** — `LLMClient` 基类，按 provider 实现（Anthropic 等）
- **Docker** — 容器化部署，uvicorn workers 配合 nginx
- **数据库** — SQLite/PostgreSQL 持久化会话存储（目前仅内存 + JSONL）
- **认证** — 仪表盘用户认证/授权

## 版本兼容性
| 包 A | 兼容版本 | 备注 |
|------|----------|------|
| openai 2.38.0 | Python 3.9+ | 异步客户端完全支持。与 3.13 无已知问题。 |
| fastapi 0.136.x | pydantic 2.x | 基于 pydantic v2。无兼容性问题。 |
| pydantic 2.13.x | pydantic-ai 1.x | pydantic-ai 1.x 锁定 pydantic v2。 |
| rich 15.0.0 | Python 3.9+ | 放弃 Python 3.8 支持。Python 3.13 正常。 |
| psutil 7.2.2 | 全部 Python 3.x | v7 系列稳定。 |
| Vite 8.0.x | Node 20.19+ 或 22.12+ | 需要较新 Node.js。推荐 Node 22 LTS。 |
| React 19.2.x | Vite 8.x | Vite 8 使用 Rolldown，完全兼容。 |
| Tailwind 4.3.x | Vite 8.x | 使用 `@tailwindcss/vite` 插件，无需 PostCSS 配置。 |
| shadcn/ui CLI v4 | React 19.x + Tailwind 4.x | 已适配 Tailwind v4。交互式 `init` 设置。 |

## 参考来源
- [PyPI: pydantic-ai 1.103.0](https://pypi.org/project/pydantic-ai/) — 最新稳定版，验证于 2026-05-27
- [PyPI: openai 2.38.0](https://pypi.org/project/openai/) — 最新版验证于 2026-05-21
- [PyPI: fastapi 0.136.3](https://pypi.org/project/fastapi/) — 最新版验证于 2026-05-23
- [PyPI: pydantic 2.13.4](https://pypi.org/project/pydantic/) — 最新版验证于 2026-05-06
- [PyPI: psutil 7.2.2](https://pypi.org/project/psutil/) — 最新版验证于 2026-01-28
- [PyPI: rich 15.0.0](https://pypi.org/project/rich/) — 最新版验证于 2026-04-12
- [npm: vite 8.0.14](https://www.npmjs.com/package/vite) — 通过 npm view 验证
- [npm: react 19.2.6](https://www.npmjs.com/package/react) — 通过 npm view 验证
- [npm: @tanstack/react-query 5.100.14](https://www.npmjs.com/package/@tanstack/react-query) — 通过 npm view 验证
- [npm: tailwindcss 4.3.0](https://www.npmjs.com/package/tailwindcss) — 通过 npm view 验证
- [FastAPI SSE 文档](https://fastapi.tiangolo.com/advanced/custom-response/#streamingresponse) — 已确认 EventSourceResponse 支持
- [Pydantic AI 文档](https://ai.pydantic.dev/) — agent 框架事件流、工具抽象
- [OpenAI Python SDK 文档](https://github.com/openai/openai-python) — 异步客户端、流式、工具调用
- [shadcn/ui CLI v4 更新日志](https://ui.shadcn.com/docs/changelog/2026-03-cli-v4) — Tailwind v4 支持、monorepo 特性
- [Tailwind CSS v4.3 发布说明](https://tailwindcss.com/blog/tailwindcss-v4-3) — 滚动条工具类、容器查询
- [Python 3.13 发布说明](https://www.python.org/downloads/release/python-31313/) — 已确认异步改进
- [PEP 787 — 更安全的 subprocess（t-strings）](https://peps.python.org/pep-0787/) — 推迟到 Python 3.15，暂不可用
- [AI Agent 框架对比 2026](https://dev.to/alexcloudstar/ai-agent-frameworks-in-2026-langgraph-vs-mastra-vs-vercel-ai-sdk-vs-openai-agents-sdk-vs-pydantic-539b) — 框架权衡分析
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## 编码规范

### 代码风格
- **Python:** ruff 格式化（100 字符行宽），mypy 严格模式，Python 3.13+
- **TypeScript:** 严格模式，`@/*` 路径别名对应 `src/*`，ES2023 编译目标
- **命名:** Python 用 snake_case，TypeScript 用 camelCase，React 组件用 PascalCase
- **文档:** 模块/类/函数的文档字符串用中文

### Git
- **提交语言:** 中文
- **提交风格:** conventional commits — `feat(范围):`、`fix(范围):`、`chore(范围):`、`docs(范围):`
- **分支:** `master`（主开发分支），`main`（远程默认分支）

### 测试
- **框架:** pytest + pytest-asyncio（auto 模式），pytest-cov
- **位置:** `tests/` 镜像 `src/loopai/` 的结构
- **模式:** 每个源模块对应一个测试文件，共享夹具在 `conftest.py`
- **API 测试:** `tests/api/`，使用 `TestClient` 夹具

### 项目结构
- **后端:** `src/loopai/` — 单一 Python 包，按关注点分子包
- **前端:** `frontend/src/` — 组件、hooks、stores、lib
- **测试:** `tests/` — 镜像源码结构
- **规划:** `.planning/` — 所有 GSD 产物（阶段、计划、状态）
- **沙箱:** `.sandbox/` — gitignore，工具执行工作区

### 架构规则
- 所有组件通信必须通过 `EventBus` — 禁止直接耦合
- 守卫必须无状态且可组合
- 工具必须声明 `PermissionLevel` 并接受 `user_confirm` 回调
- 新增事件类型必须同时更新 Python `events/schemas.py` 和 TypeScript `lib/eventTypes.ts`
- API 路由遵循 REST 规范：`/api/sessions/` 用于 CRUD，`/api/sessions/{id}/stream` 用于 SSE
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## 架构

### 整体结构

```
┌─────────────┐     ┌──────────────────────────┐     ┌──────────────┐
│  React SPA  │◄───►│  FastAPI (SSE + REST)     │     │  CLI (rich)  │
│  (Vite 8)   │     │  /api/sessions/*          │     │  loopai run   │
└─────────────┘     └──────────┬───────────────┘     └──────┬───────┘
                               │                            │
                        ┌──────▼────────────────────────────▼───────┐
                        │           EventBus (发布/订阅)             │
                        │    ┌──────────────────────────────┐        │
                        │    │        ReActFSM               │        │
                        │    │  REASON → ACT → OBSERVE       │        │
                        │    │       ↓                       │        │
                        │    │  FINISH_WAIT / ERROR          │        │
                        │    └──────────────────────────────┘        │
                        │              │         │                   │
                        │    ┌─────────▼──┐ ┌─────▼──────────┐      │
                        │    │ LLMClient   │ │ ToolExecutor    │      │
                        │    │ (OpenAI)    │ │ (4级恢复)       │      │
                        │    └────────────┘ └────────────────┘      │
                        └───────────────────────────────────────────┘
```

### 包地图 (`src/loopai/`)

| 包 | 职责 |
|----|------|
| `state_machine/` | `ReActFSM`（核心循环），`guards.py`（BudgetGuard、LoopDetector、TokenGuard 等） |
| `events/` | `EventBus`（asyncio.Queue 发布/订阅），`schemas.py`（22 种事件类型，可区分联合） |
| `llm/` | `LLMClient` — OpenAI 流式封装，向 EventBus 发送事件 |
| `tools/` | `@tool` 装饰器、`ToolRegistry`、`ToolExecutor`（4 级恢复）、`BashTool`、`disk_tools.py`、`CommandClassifier` |
| `session/` | `Session` 数据类、`AgentState` 枚举（6 种状态） |
| `context/` | `TokenCounter`（tiktoken）、`ContextCompressor`（滑动窗口 + LLM 摘要） |
| `resilience/` | `CheckpointManager`（JSONL）、`CircuitBreaker`、`FailureRegistry` |
| `agents/` | `@agent` 装饰器、`AgentRegistry`、`AgentTool`（agent 作为工具的桥接） |
| `api/` | FastAPI 应用工厂、SSE 桥接、REST 路由（sessions、control、stream） |
| `consumers/` | `CLIRenderer`（Rich 终端渲染）、`JSONLLogger`（文件持久化） |

### 核心模式

1. **事件驱动发布/订阅。** 所有组件通过 `EventBus` 通信。FSM 发布事件；消费者（CLI、JSONL 日志、SSE 桥接）独立订阅。支持事件重放和多消费者观察。

2. **ReAct 有限状态机。** `ReActFSM` 实现严格的状态机：
   - `REASON` — 调用 LLM，校验消息，检查守卫
   - `ACT` — 通过工具管道执行工具
   - `OBSERVE` — 检查可达性，递增步数计数器
   - `FINISH_WAIT` — 暂停等待多轮用户输入（对话模式）
   - `ERROR` — 终止状态

3. **守卫管道。** 可插拔、可组合的安全检查：`BudgetGuard`、`LoopDetector`、`MessageValidator`、`TokenGuard`、`CostGuard`、`RateLimitGuard`。首个失败即短路。

4. **三级工具安全。** 每个 bash 命令经过：(1) `shlex.split()` 解析（shell=False），(2) `CommandClassifier` 白名单/黑名单，(3) shell 元字符扫描。危险命令需要用户确认。

5. **四级恢复。** `ToolExecutor`：第 1 级（JSON 格式修复），第 2 级（上下文内 FSM 重试），第 3 级（指数退避 + 抖动），第 4 级（人工介入）。

6. **Agent 作为工具。** 子 agent（`@agent` 装饰器）由 `AgentTool` 封装并实现 `ToolMetadata`，主 agent 可将其作为工具调用。每个子 agent 拥有独立的 EventBus 和 Session。

7. **共享组件工厂。** `create_agent_components()` 在 `main.py` 中统一组装所有组件，CLI 和 Web 路径一致。

### 数据流

```
用户输入 → ReActFSM → LLMClient (流式) → EventBus ─┬─→ CLI Renderer
                   │                               ├─→ JSONL Logger
                   ▼                               └─→ SSE Bridge → Frontend
             ToolExecutor → BashTool / DiskTools / AgentTool
```

### 阶段完成情况

| 阶段 | 状态 |
|------|------|
| 1 — Agent 核心循环 | ✅ 已完成 |
| 2 — 工具系统与业务验证 | ✅ 已完成 |
| 3 — 上下文管理 | ✅ 已完成 |
| 4 — 弹性与恢复 | ✅ 已完成 |
| 5 — 可观测性与 Web 前端 | ✅ 已完成 |
| 6 — Agent 作为工具（多 Agent） | ✅ 已完成 |
| 7 — 对话模式 | ✅ 已完成 |
<!-- GSD:architecture-end -->

<!-- GSD:skills-start source:skills/ -->
## 项目技能

未找到项目技能。将技能添加到以下任一目录：`.claude/skills/`、`.agents/skills/`、`.cursor/skills/`、`.github/skills/` 或 `.codex/skills/`，并包含 `SKILL.md` 索引文件。
<!-- GSD:skills-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD 工作流强制规则

使用 Edit、Write 或其他文件修改工具前，必须通过 GSD 命令启动工作，确保规划产物和执行上下文保持同步。

使用以下入口：
- `/gsd-quick` — 小修复、文档更新和临时任务
- `/gsd-debug` — 问题排查和 bug 修复
- `/gsd-execute-phase` — 按计划执行阶段工作

除非用户明确要求跳过，否则不要在 GSD 工作流之外直接编辑仓库。
<!-- GSD:workflow-end -->



<!-- GSD:profile-start -->
## 开发者档案

> 尚未配置。运行 `/gsd-profile-user` 生成开发者档案。
> 此部分由 `generate-claude-profile` 管理 -- 请勿手动编辑。
<!-- GSD:profile-end -->
