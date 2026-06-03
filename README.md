# loopAI

**从零构建的 AI Agent 系统** — 手写 ReAct 循环、事件驱动架构、动态工具系统，用于深入理解 agent harness 工程的每一层。

[![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.136-green.svg)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-19-61dafb.svg)](https://react.dev/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.7-3178c6.svg)](https://www.typescriptlang.org/)
[![Vite](https://img.shields.io/badge/Vite-8-ffc425.svg)](https://vite.dev/)
[![Tailwind CSS](https://img.shields.io/badge/Tailwind-4-38bdf8.svg)](https://tailwindcss.com/)

---

## 概览

loopAI 是一个学习驱动的 AI Agent 平台。不从 LangChain、CrewAI 等框架拿现成的——**agent 循环、工具系统、守卫管道全部从零手写**，目的是面对框架替你隐藏的设计决策，亲手解决。

### 核心能力

- **ReAct Agent 循环** — 手写有限状态机（REASON → ACT → OBSERVE），不依赖任何 agent 框架
- **事件驱动架构** — 基于 asyncio.Queue 的发布/订阅 EventBus，CLI / JSONL 日志 / Web 仪表盘解耦消费
- **动态工具系统 (v1.1)** — Agent 在沙箱内自主编写 Python/Bash 代码，经用户确认后注册为新工具
- **三层安全防御** — AST 扫描 + subprocess 子进程隔离 + 用户确认门
- **实时可观测仪表盘** — React 19 + SSE 流式推送，可视化 agent 思考过程
- **对话模式** — 多轮人机对话，Agent 可主动提问澄清需求
- **Agent 作为工具** — 子 agent 封装为父 agent 的可调用工具
- **四级恢复管道** — JSON 修复 → 上下文内重试 → 指数退避 → 人工介入

## 快速开始

### 环境要求

| 依赖 | 版本 |
|------|------|
| Python | 3.13+ |
| Node.js | 22+ |
| pnpm | latest |
| uv | latest |

### 安装

```bash
# 一键安装所有依赖
make install

# 或分步安装：
uv sync                          # Python 后端 + 开发依赖
cd frontend && pnpm install      # 前端
```

### 配置

```bash
cp .env.example .env
```

编辑 `.env` 填入 OpenAI API key 和模型配置。

### 运行

```bash
make dev       # 开发模式 — 后端 :8000 + 前端 :5173
make start     # 后台运行（PID 文件）
make stop      # 停止后台进程
```

打开 http://localhost:5173 查看仪表盘。

### 测试

```bash
make test       # 单元测试
make test-all   # 全部测试（含 API 集成测试）
make demo       # 搭建沙箱演示场景
```

## 架构

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

## 技术栈

### 后端
| 技术 | 用途 |
|------|------|
| **Python 3.13** | 运行时 — 改进的 asyncio，实验性 io_uring |
| **FastAPI** | Web 框架 — 原生 SSE、WebSocket、自动 OpenAPI |
| **Pydantic 2** | 数据模型 — Rust 核心，类型安全 |
| **openai** | LLM 客户端 — 流式、工具调用、异步 |
| **Rich** | CLI 终端渲染 |
| **psutil** | 系统监控（磁盘空间等） |

### 前端
| 技术 | 用途 |
|------|------|
| **React 19** | UI 框架 — React Compiler 自动 memoization |
| **TypeScript 5.7** | 类型安全 |
| **Vite 8** | 构建工具 — Rolldown (Rust) |
| **Tailwind CSS 4** | 样式 — Oxide 引擎 |
| **shadcn/ui** | 组件库 — 复制即拥有 |
| **Zustand** | 客户端状态管理 |
| **React Query** | 服务端状态 + SSE 乐观更新 |
| **Recharts** | 图表可视化 |

## 项目结构

```
loopai/
├── src/loopai/           # Python 后端包
│   ├── state_machine/    # ReActFSM 核心循环 + 守卫管道
│   ├── events/           # EventBus 发布/订阅 + 事件 schema
│   ├── llm/              # LLMClient (OpenAI 流式封装)
│   ├── tools/            # 工具系统 (装饰器、注册表、执行器)
│   ├── session/          # 会话状态管理
│   ├── context/          # Token 计数 + 上下文压缩
│   ├── resilience/       # 检查点、断路器、故障注册
│   ├── agents/           # Agent 装饰器 + Agent 作为工具
│   ├── api/              # FastAPI 应用 + SSE 桥接
│   └── consumers/        # CLI 渲染器 + JSONL 日志
├── frontend/src/         # React 前端
│   ├── components/       # UI 组件
│   ├── hooks/            # 自定义 hooks
│   ├── stores/           # Zustand stores
│   └── lib/              # 工具函数 + 类型定义
├── tests/                # pytest 测试
└── .planning/            # GSD 规划产物
```

## 方案对比

| 推荐 | 替代方案 | 理由 |
|------|----------|------|
| **从零构建 agent 循环** | LangChain/LangGraph | 框架掩盖 agent 内部机制，与学习目标冲突 |
| **从零构建 agent 循环** | CrewAI | 多 agent 编排超出当前范围 |
| **FastAPI** | Django | 同步 ORM，对轻量 API 过重 |
| **React + Vite** | Next.js | 单页仪表盘不需要 SSR |
| **shadcn/ui** | MUI | 组件更重，不属于你的代码 |
| **SSE** | WebSocket | 单向观察 SSE 更简单 |
| **Zustand** | Redux | 仪表盘状态不需要那么多样板 |
| **JSONL 日志** | SQLite/PostgreSQL | 学习项目不需要 schema 迁移 |

## 开发

```bash
# 代码检查
ruff check src/ tests/
mypy src/

# 前端检查
cd frontend && pnpm lint
```

### 提交规范

- 中文提交信息
- Conventional commits：`feat(范围):`、`fix(范围):`、`docs(范围):`、`chore(范围):`
- 分支：`master`（主开发分支）

### 编码风格

- Python：ruff 格式化（100 字符行宽），mypy 严格模式
- TypeScript：严格模式，`@/*` 别名 → `src/*`
- 文档字符串：中文
- 命名：Python `snake_case`，TypeScript `camelCase`，React 组件 `PascalCase`

## 阶段完成情况

| 阶段 | 内容 | 状态 |
|------|------|------|
| 1 | Agent 核心循环 | ✅ |
| 2 | 工具系统与业务验证 | ✅ |
| 3 | 上下文管理 | ✅ |
| 4 | 弹性与恢复 | ✅ |
| 5 | 可观测性与 Web 前端 | ✅ |
| 6 | Agent 作为工具（多 Agent） | ✅ |
| 7 | 对话模式 | ✅ |
| 8 | 动态工具创建核心 | ✅ |
| 9 | 安全加固与沙箱隔离 | ✅ |
| 10 | 用户体验与工具管理 | ✅ |

## 许可

MIT
