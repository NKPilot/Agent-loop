# Phase 01: Agent Core Loop — 研究报告

**研究日期:** 2026-05-27
**领域:** ReAct Agent 状态机, LLM 流式输出, 事件驱动架构
**置信度:** HIGH

## 概述

Phase 01 交付 Agent 的基础运行时：一个驱动 LLM 推理-行动循环的 ReAct 状态机，以步骤级和 Token 级双粒度流式输出事件，通过步骤预算与安全截断强制执行限制，检测工具调用循环，并写入结构化的 JSONL 会话日志。Phase 02-05 的所有内容都建立在此循环之上。

架构采用三种经过验证的模式：(1) 使用显式枚举状态而非原始 `while` 循环的有限状态机，(2) 基于 `asyncio.Queue` 的内部 Event Bus，支持向多个消费者扇出（CLI 显示、JSONL 日志记录器、未来的 SSE 端点），(3) OpenAI `client.beta.chat.completions.stream()` API，提供 11 种类型化事件的自动累积流式响应。

标准技术栈为 Python 3.13（通过 uv 管理），配合 openai SDK 2.38.0、pydantic 2.13 用于事件模型、rich 15.0 用于 CLI 渲染、以及 stdlib asyncio 作为并发骨干。所有依赖项均在 CLAUDE.md 中指定并已在 PyPI 上确认为最新版本。

**主要建议:** 优先构建 Event Bus，然后将 ReAct FSM 接入其中。Event Bus 是主干——状态机发布事件，消费者订阅事件。这种解耦意味着 CLI 渲染器、JSONL 日志记录器和未来的 SSE 端点是彼此独立的消费者，可以隔离开发和测试。

## 架构责任分配图

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| ReAct State Machine | Backend (asyncio loop) | — | 核心 Agent 循环完全在服务端运行；它是一个纯异步状态机，不依赖 UI |
| LLM API Calls | Backend (openai SDK) | — | 所有 LLM 通信均通过 OpenAI 兼容 API 在服务端进行 |
| Token-Level Streaming | Backend (Event Bus) | — | 流式数据源自 LLM，通过内部 Event Bus 扇出到多个消费者 |
| Step Budget Enforcement | Backend (FSM guard) | — | 预算检查是状态机转换中的守卫条件 |
| Loop Detection | Backend (FSM guard) | — | 工具调用历史在 Agent 运行时内追踪；检测发生在进入 ACT 状态之前 |
| CLI Display | Backend (Rich Live) | — | Rich 使用守护线程在终端内渲染；它从 Event Bus 消费事件 |
| JSONL Logging | Backend (file I/O) | — | 文件写入器是一个 Event Bus 消费者；写入本地磁盘 |
| SSE Endpoint (未来) | Backend (FastAPI) | — | Phase 5 添加；Event Bus 消费者，将事件推送到 HTTP 客户端 |
| Event Schema Validation | Backend (pydantic) | — | 所有事件类型均为 pydantic 模型，在发布时进行验证 |

## 用户约束（来自 CONTEXT.md）

### 已锁定决策

- **D-01:** REASON 状态下，LLM 返回纯文本（无 tool_calls）时，直接转换到 FINISH。遵循 OpenAI function calling 原生行为——模型在一次调用中要么返回 tool_calls，要么返回最终答案，不存在"空 ACT"的情况。
- **D-02:** 状态机五个状态: REASON → ACT → OBSERVE → FINISH → ERROR。REASON 是入口，每次循环从 REASON 开始。
- **D-03:** 双粒度事件——步骤级事件（step_start, step_end）+ Token 级实时输出（llm_token）。CLI 可逐字打印，Web 前端可实时渲染思考过程。
- **D-04:** 分层事件结构——顶层生命周期事件包裹内层子事件流。每个步骤内嵌套 token 流和工具调用事件。
- **D-05:** 基于 `asyncio.Queue` 的内部 Event Bus（发布-订阅模式）。三个消费者: CLI（Rich 终端渲染）、JSONL Logger（结构化日志）、SSE 端点（Phase 5 使用但架构上现在预留）。
- **D-06:** 默认最大步骤数: 15-20 步。磁盘诊断等典型场景 10-15 步足够，留有余量。
- **D-07:** 预算耗尽行为: 最后一轮摘要机会——给 LLM 注入提示"预算已用完，请基于当前信息给出最终答案"，然后强制终止。
- **D-08:** "目标不可达成"判定: 系统规则检测 + LLM 自判两者结合。系统检测硬信号（连续失败、用户拒绝），LLM 也可主动声明不可达成。
- **D-09:** 80% 预算预警: 向 LLM 上下文注入提醒提示——"步骤预算已使用 80%，请在后续步骤中优先给出结论"。
- **D-10:** 事件流记录——JSONL 每行对应事件总线的一个事件，1:1 映射。支持完整会话回放。
- **D-11:** 每会话一个文件，按 `session_id` + 时间戳命名。如 `logs/sessions/2026-05-27_14a3f2.jsonl`。

### Claude 酌情决定范围

以下领域未在讨论中锁定，规划者和研究者可自主选择合理方案:
- ERROR 状态是终态还是可恢复状态
- 状态转换失败时的处理策略
- 事件 Schema 的具体字段定义（按分层结构自行设计）
- 循环检测的干预策略细节（CORE-06）
- 消息结构校验的严格程度（CORE-05）
- LLM 配置方式（环境变量 vs 配置文件 vs CLI 参数）

### 已推迟的想法（不在范围内）

无——讨论保持在阶段范围内。

## Phase 需求

| ID | Description | Research Support |
|----|-------------|------------------|
| CORE-01 | 实现 ReAct 状态机（REASON → ACT → OBSERVE → FINISH → ERROR），而非简单的 while 循环 | Architecture Patterns Pattern 1: 基于枚举的 FSM；D-01, D-02 已锁定；标准方法已在多个生产实现中验证 |
| CORE-02 | 通过 OpenAI 兼容 API 调用 LLM（可配置 base_url, api_key, model） | Standard Stack: openai SDK 2.38.0；client.chat.completions.create() 和 client.beta.chat.completions.stream() 都支持 base_url, api_key, model 参数 |
| CORE-03 | 流式输出 agent 每步的思考、调用和观察结果（async generator/SSE） | Architecture Patterns Pattern 2: Event Bus + Pattern 3: Layered Events；openai beta stream API 提供 11 种事件类型与自动累积；Rich Live 用于 CLI 渲染 |
| CORE-04 | 步骤预算 + 终止条件（目标达成 / 不可达成 / 预算耗尽 80% 预警） | Architecture Patterns Pattern 5: Step Budget Guard；D-06 至 D-09 已锁定 |
| CORE-05 | 消息结构交替校验（tool_call 和 tool_result 必须成对，防止孤立的 tool call 导致幻觉） | Don't Hand-Roll: 消息结构验证；实现为调用前守护检查，在每次 LLM 调用前验证 OpenAI API 消息格式 |
| CORE-06 | 基础循环检测（同一工具连续调用 3 次以上触发干预） | Architecture Patterns Pattern 4: Loop Detection；基于哈希的签名匹配配合滑动窗口；三级升级机制（警告/阻止/强制退出） |
| CORE-07 | 从第一轮即开启 JSONL 日志记录，格式化为结构化事件 | Architecture Patterns Pattern 6: JSONL Event Logger；D-10, D-11 已锁定；仅追加写入，每会话一个文件 |

## 标准技术栈

技术栈在 CLAUDE.md 中已定义（于 2026-05-27 审查确认）。Phase 01 使用 Python 后端子集：

### 核心技术

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|-------------|
| **Python** | 3.13.x | Runtime | CLAUDE.md 指定；3.13 改进了 asyncio 调度器和 io_uring 后端 |
| **openai** | 2.38.0 | LLM client | PyPI 最新版本 [已验证: PyPI 2026-05-27]；`client.beta.chat.completions.stream()` 提供带自动累积工具调用的类型化事件 |
| **pydantic** | 2.13.4 | Event models | Rust 后端支持的事件 schema 验证；用于 EventBus 消息类型化和 JSONL 序列化 [已验证: PyPI 2026-05-06] |
| **asyncio** | (stdlib) | Async runtime | Python 3.13 标准库；驱动 Event Bus、FSM 执行和并发消费者 [已验证: Python 文档] |
| **rich** | 15.0.0 | CLI display | Agent 思维追踪的终端实时渲染 UI；`Live` 上下文管理器、`Panel`、`Markdown` 可渲染组件 [已验证: PyPI 2026-04-12] |

### 支撑库

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| **httpx** | 0.28.x | Async HTTP client | openai 的必需依赖；也可用于工具中的直接 HTTP 调用（Phase 2+） [已验证: PyPI 依赖链] |
| **uuid** | (stdlib) | Session ID generation | 生成唯一的 session_id 值用于 JSONL 文件命名 |
| **datetime** | (stdlib) | Timestamps | JSONL 日志条目的 UTC 时间戳 |
| **json** | (stdlib) | Serialization | JSONL 行写入；pydantic 模型通过 `.model_dump_json()` 生成 JSON |
| **collections.deque** | (stdlib) | Sliding window | 循环检测历史记录（保存最近 N 次工具调用的有界窗口） |
| **pathlib** | (stdlib) | File paths | 用于 JSONL 会话文件的跨平台路径处理 |

### 开发工具

| Tool | Version | Purpose | Notes |
|------|---------|---------|-------|
| **uv** | 0.11.12 | Python package manager | 系统上可用 [已验证: 环境检查] |
| **pytest** | latest | Testing | 通过 `pytest-asyncio`、`@pytest.mark.asyncio` 支持异步测试 [假设: 尚未安装] |
| **pytest-asyncio** | latest | Async test support | 测试 Agent 循环所需 [假设: 尚未安装] |
| **ruff** | latest | Linter/formatter | 比 flake8+isort+black 快 100 倍 [假设: 尚未安装] |

### 已考虑的替代方案

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Raw `while` loop | Explicit FSM enum | 基于枚举的 FSM 提供清晰的退出条件、可测试的转换和更好的错误恢复。已锁定决策 D-02。 |
| `openai.chat.completions.create(stream=True)` | `client.beta.chat.completions.stream()` | beta stream API 提供自动累积的工具调用参数和结构化事件（`content.delta`、`tool_calls.function.arguments.done`）——如果不使用它，你必须手动从 ChatCompletionChunk 中拼凑碎片化的工具调用参数。beta API 显著减少了样板代码。 |
| `tool-loop-guard` 库 | 基于哈希的 deque | `tool-loop-guard` pip 包正好满足我们的需求，但为了学习的深度我们自行构建。实现大约 30 行代码。 |
| Redis Pub/Sub | asyncio.Queue Event Bus | Redis 为单进程 Agent 增加了运维复杂度（服务器、连接管理）。asyncio.Queue 是进程内的，零配置，且完全足够。 |

**安装命令:**
```bash
# Create virtual environment with Python 3.13 (uv will download if needed)
uv venv --python 3.13
source .venv/bin/activate

# Install core dependencies
uv pip install openai==2.38.0 pydantic==2.13.4 rich==15.0.0 httpx==0.28.1

# Install dev dependencies
uv pip install pytest pytest-asyncio ruff mypy
```

**版本验证:** 每个推荐版本已于 2026-05-27 对照 PyPI JSON API 和 importlib.metadata 检查确认。

## 架构模式

### 系统架构图

```
                          ┌───────────────────────────────────────────┐
                          │               ReAct 状态机                  │
                          │  ┌──────┐   ┌─────┐   ┌─────────┐        │
                          │  │REASON│──▶│ ACT │──▶│ OBSERVE │        │
                          │  └──┬───┘   └─────┘   └────┬────┘        │
                          │     │                       │             │
                          │     │ 无 tool_calls           │ step++     │
                          │     ▼                       ▼             │
                          │  ┌──────┐              ┌──────┐           │
                          │  │FINISH│              │REASON│ (循环)     │
                          │  └──────┘              └──────┘           │
                          │                                             │
                          │  任何状态 ──异常──▶ ERROR                    │
                          └──────────┬────────────────────────────────┘
                                     │
                                     │ publish(Event)
                                     ▼
                          ┌──────────────────────┐
                          │      Event Bus        │
                          │  (asyncio.Queue × N)  │
                          │  发布/订阅扇出         │
                          └──┬────────┬───────────┘
                             │        │
                    ┌────────┘        └────────┐
                    ▼                          ▼
          ┌─────────────────┐        ┌──────────────────┐
          │   CLI 消费者    │        │  JSONL 日志记录器 │
          │  (Rich Live)    │        │  (文件追加写入)    │
          │                 │        │                  │
          │  - step_start   │        │  logs/sessions/  │
          │  - llm_token    │        │  2026-05-27_     │
          │  - tool_call    │        │  abc123.jsonl    │
          │  - tool_result  │        │                  │
          │  - step_end     │        │  Event:1 → Line:1│
          │  - session_end  │        │  1:1 映射        │
          └─────────────────┘        └──────────────────┘

          ┌──────────────────┐ (Phase 5 — 预留位置)
          │   SSE 消费者     │
          │   (FastAPI)      │
          │   仅 Phase 5     │
          └──────────────────┘

外部边界:
  ┌──────────────┐
  │ OpenAI API   │◀──── REASON 状态: client.beta.chat.completions.stream()
  │ (或兼容 API)  │      model="...", messages=[...], tools=[...]
  └──────────────┘
```

### 推荐的项目结构

```
src/
├── loopai/
│   ├── __init__.py
│   ├── main.py              # CLI 入口点，会话编排
│   ├── config.py             # LLM 配置 (api_key, base_url, model) — Claude 酌情决定领域
│   ├── state_machine/
│   │   ├── __init__.py
│   │   ├── fsm.py            # ReActFSM: REASON→ACT→OBSERVE→FINISH→ERROR
│   │   └── guards.py          # 预算守卫、循环检测、消息验证
│   ├── events/
│   │   ├── __init__.py
│   │   ├── bus.py             # EventBus: 基于 asyncio.Queue 的发布/订阅
│   │   └── schemas.py         # Event pydantic 模型（所有事件类型）
│   ├── llm/
│   │   ├── __init__.py
│   │   └── client.py          # 封装 openai SDK 的 LLMClient
│   ├── consumers/
│   │   ├── __init__.py
│   │   ├── cli_renderer.py    # Rich Live 消费者: 步骤面板、Token 流式输出
│   │   └── jsonl_logger.py    # JSONL 文件消费者: 每次事件追加写入
│   └── session/
│       ├── __init__.py
│       └── context.py         # 会话状态: messages[], step_count, config
└── tests/
    ├── __init__.py
    ├── conftest.py            # 共享 fixtures: mock LLM, event bus, test session
    ├── test_fsm.py            # 状态机转换、退出条件
    ├── test_event_bus.py      # 发布/订阅、扇出、事件排序
    ├── test_guards.py         # 预算、循环检测、消息验证
    ├── test_jsonl_logger.py   # 日志文件创建、行格式、追加行为
    └── test_cli_renderer.py   # Rich 可渲染输出验证（捕获）
```

### Pattern 1: ReAct 有限状态机

**是什么:** 基于枚举的状态机，具有显式转换规则。每个状态对应一个异步处理方法。转换根据 LLM 响应内容以确定性方式执行。

**何时使用:** 始终使用——这是 Agent 的核心。D-01 和 D-02 锁定了五个状态和 REASON→FINISH 快捷路径。

**关键设计决策（Claude 酌情决定范围）:**

1. **ERROR 状态: Phase 1 中为终止状态。** 将 ERROR 设为终止状态简化了实现，且与 Phase 1 范围一致。恢复逻辑（在 ERROR 后重新进入 REASON）属于 Phase 4 的韧性层。理由：在没有检查点/重试基础设施的情况下，从 ERROR 中恢复是不可靠的。

2. **状态转换失败: 抛出异常并进入 ERROR。** 如果 LLM 响应格式错误（既不是文本也不是 tool_calls），或者工具执行抛出未处理的异常，则转换到 ERROR。这是硬停止——记录失败并附带完整上下文，然后终止。

**示例:**
```python
# Source: synthesized from ReAct FSM best practices verified via WebSearch
from enum import Enum
from dataclasses import dataclass, field
from typing import Any

class AgentState(Enum):
    REASON = "reason"
    ACT = "act"
    OBSERVE = "observe"
    FINISH = "finish"
    ERROR = "error"

@dataclass
class Session:
    state: AgentState = AgentState.REASON
    messages: list[dict] = field(default_factory=list)
    step_count: int = 0
    tool_history: list[tuple[str, str]] = field(default_factory=list)  # (name, args_hash)

class ReActFSM:
    """状态转换:
    REASON --[有 tool_calls]--> ACT
    REASON --[无 tool_calls]---> FINISH    (D-01)
    ACT --[工具已执行]--------> OBSERVE
    ACT --[异常]--------------> ERROR
    OBSERVE --[step < max]---> REASON
    OBSERVE --[step >= max]--> FINISH      (D-07, 强制终止)
    任何状态 --[未处理错误]--> ERROR
    """

    async def run(self, session: Session, bus: EventBus, config: Config) -> Session:
        while session.state not in (AgentState.FINISH, AgentState.ERROR):
            if session.state == AgentState.REASON:
                session = await self._handle_reason(session, bus, config)
            elif session.state == AgentState.ACT:
                session = await self._handle_act(session, bus, config)
            elif session.state == AgentState.OBSERVE:
                session = await self._handle_observe(session, bus, config)
        return session
```

### Pattern 2: asyncio.Queue Event Bus（发布/订阅）

**是什么:** 进程内的事件总线，每个订阅者拥有自己的 `asyncio.Queue`。发布操作向所有订阅者队列扇出。消费者是长时间运行的异步任务，在循环中 `await queue.get()`。

**何时使用:** 所有组件间通信的骨干。FSM 发布事件；CLI、JSONL 和未来的 SSE 消费者独立订阅。

**关键设计决策:**

1. **用于重放的事件历史。** 维护一个 `list[Event]` 历史记录。当新订阅者连接时（例如 Phase 5 中的 SSE 客户端），先重放所有过去的事件，然后流式输出实时事件。这使得 JSONL 日志记录器在需要时可以在会话中途启动。

2. **使用哨兵安全关闭。** 使用 `None` 哨兵事件通知消费者排空队列并退出。通过 `asyncio.CancelledError` 强制停止可能导致 JSONL 日志的最后几个事件丢失。

3. **通过 pydantic 进行事件 schema 验证。** 所有事件都是类型化的 pydantic 模型。总线在发布时验证。这确保了 JSONL 日志条目始终格式正确。

**示例:**
```python
# Source: synthesized from asyncio.Queue pub/sub patterns verified via WebSearch
import asyncio
from typing import Any

class EventBus:
    def __init__(self):
        self._subscribers: dict[str, list[asyncio.Queue]] = {}
        self._history: list[dict] = []
        self._lock = asyncio.Lock()  # 在订阅/取消订阅期间保护 _subscribers

    async def publish(self, topic: str, event: dict) -> None:
        """扇出：将事件推送到此主题的所有订阅者队列。"""
        self._history.append(event)
        for queue in self._subscribers.get(topic, []):
            await queue.put(event)

    async def subscribe(self, topic: str) -> asyncio.Queue:
        """注册新订阅者。返回其专属队列。"""
        queue: asyncio.Queue = asyncio.Queue(maxsize=256)  # 通过有界队列实现背压
        async with self._lock:
            self._subscribers.setdefault(topic, []).append(queue)
        return queue

    async def unsubscribe(self, topic: str, queue: asyncio.Queue) -> None:
        """移除订阅者。关闭期间安全调用。"""
        async with self._lock:
            queues = self._subscribers.get(topic, [])
            if queue in queues:
                queues.remove(queue)

    def replay(self, topic: str) -> list[dict]:
        """返回某个主题的所有历史事件（供后加入订阅者使用）。"""
        return [e for e in self._history if e.get("topic") == topic]
```

### Pattern 3: 分层事件 Schema

**是什么:** 两级事件层次结构。顶层生命周期事件（`step_start`、`step_end`、`session_end`）包裹内部流式事件（`llm_token`、`tool_call_start`、`tool_call_args`、`tool_result`）。每个步骤是一个有界区域。

**何时使用:** 这是 D-04 已锁定的决策。分层结构使 CLI 能够在流式输出 Token 的同时渲染步骤边界面板。

**事件类型（Claude 酌情决定范围——字段定义）:**

```python
# 顶层生命周期事件
StepStart:    { session_id, step_num, timestamp }
StepEnd:      { session_id, step_num, timestamp, state_transition, token_usage }
SessionEnd:   { session_id, timestamp, final_state, total_steps, exit_reason }

# 内部流式事件（仅在 step_start 和 step_end 之间发生）
LLMToken:     { session_id, step_num, content_delta }          # Token 级流式输出
LLMContentDone: { session_id, step_num, full_content }          # 文本补全完成
ToolCallStart:  { session_id, step_num, tool_name, tool_call_id }
ToolCallArgs:   { session_id, step_num, tool_name, args_delta }  # 流式工具参数
ToolCallDone:   { session_id, step_num, tool_name, tool_call_id, full_args }
ToolResult:    { session_id, step_num, tool_name, tool_call_id, result, is_error, duration_ms }

# 守卫事件
BudgetWarning: { session_id, step_num, used_pct, max_steps }
BudgetExhausted: { session_id, step_num }
LoopDetected:  { session_id, step_num, tool_name, consecutive_count }
Error:         { session_id, step_num, error_type, message, traceback }
```

### Pattern 4: 循环检测

**是什么:** 基于哈希的重复工具调用检测，使用 `(tool_name, canonical_args_hash)` 的滑动窗口。三级升级机制：3 次时警告，5 次时阻止，如果模式持续则强制退出。

**何时使用:** 在进入 ACT 状态之前的守卫检查。当 LLM 决定调用某个工具后、在执行之前，检查工具历史。

**Claude 酌情决定范围——干预策略:**

- **一级（3 次连续相同调用）：** 向 LLM 上下文注入系统消息："You have called `{tool_name}` with the same arguments 3 times in a row. The tool is producing the same result. Please try a different approach or provide your best answer based on available information."
- **二级（5 次连续相同调用）：** 拒绝执行此工具调用。改为添加带有错误内容的工具结果消息："[SYSTEM] Tool call blocked — repeated 5 times. Please provide your final answer." 强制转换到 REASON。
- **三级（二级后模式仍然持续）：** 强制转换到 FINISH。LLM 即使经过干预仍陷入循环。

**示例:**
```python
# Source: synthesized from loop detection patterns verified via WebSearch
import json
import hashlib
from collections import deque

class LoopDetector:
    def __init__(self, window_size: int = 20, warn_threshold: int = 3, block_threshold: int = 5):
        self._window: deque[tuple[str, str]] = deque(maxlen=window_size)
        self._warn_threshold = warn_threshold
        self._block_threshold = block_threshold
        self._consecutive_count = 0
        self._last_signature: str | None = None

    @staticmethod
    def _signature(tool_name: str, arguments: dict) -> str:
        """规范化哈希: (tool_name, 按键排序的 JSON args)。"""
        args_json = json.dumps(arguments, sort_keys=True, ensure_ascii=True)
        raw = f"{tool_name}:{args_json}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def check(self, tool_name: str, arguments: dict) -> tuple[bool, str]:
        """
        返回 (should_proceed, action)。
        action 为以下之一: "allow", "warn", "block", "force_exit"
        """
        sig = self._signature(tool_name, arguments)

        if sig == self._last_signature:
            self._consecutive_count += 1
        else:
            self._consecutive_count = 1
            self._last_signature = sig

        self._window.append((tool_name, sig))

        if self._consecutive_count >= self._block_threshold:
            return (False, "force_exit")
        elif self._consecutive_count >= self._warn_threshold:
            return (False, "block")
        elif self._consecutive_count >= self._warn_threshold - 1:
            return (True, "warn")  # 允许但注入警告
        return (True, "allow")

    def reset(self) -> None:
        """当新的工具调用打破重复模式时重置。"""
        self._consecutive_count = 0
        self._last_signature = None
```

### Pattern 5: 步骤预算守卫

**是什么:** 在 OBSERVE→REASON 转换时运行的守卫。检查步骤计数是否达到最大预算，在 80% 时注入上下文警告，在 100% 时强制终止。

**何时使用:** 每次从 OBSERVE 回到 REASON 的循环。也要在第一次 REASON 之前检查（边界情况：max_steps=0）。

**示例:**
```python
# Source: D-06, D-07, D-09 已锁定决策
class BudgetGuard:
    def __init__(self, max_steps: int = 15, warn_pct: float = 0.80):
        self.max_steps = max_steps
        self.warn_threshold = int(max_steps * warn_pct)

    def check(self, step_count: int, messages: list[dict]) -> tuple[bool, list[dict], str | None]:
        """
        返回 (should_continue, modified_messages, action)。
        action: None (正常), "warn" (注入预算警告), "final" (最后一次摘要机会), "exhausted" (强制结束)
        """
        if step_count >= self.max_steps:
            # D-07: 最后一次摘要机会
            final_msg = {
                "role": "system",
                "content": "Your step budget has been exhausted. Based on the information you have gathered so far, provide your best final answer. Do not call any tools."
            }
            messages.append(final_msg)
            return (True, messages, "final")  # 再进行一轮 REASON，然后强制 FINISH

        if step_count >= self.warn_threshold and step_count < self.max_steps:
            # D-09: 80% 预警
            remaining = self.max_steps - step_count
            warn_msg = {
                "role": "system",
                "content": f"Step budget at {int(step_count/self.max_steps*100)}%. {remaining} steps remaining. Prioritize reaching a conclusion."
            }
            messages.append(warn_msg)
            return (True, messages, "warn")

        return (True, messages, None)
```

### Pattern 6: JSONL 事件日志记录器

**是什么:** 一个 Event Bus 消费者，将每个事件作为一行 JSON 写入每个会话单独的文件。事件到行的 1:1 映射（D-10）。文件命名: `logs/sessions/{YYYY-MM-DD}_{session_id}.jsonl`（D-11）。

**何时使用:** 在会话开始时订阅 Event Bus，作为后台 asyncio 任务运行，在会话结束时优雅关闭。

**关键设计决策:**

1. **仅追加写入。** 绝不修改已有行。审计完整性是最高优先事项。
2. **每个事件后刷新。** 为了崩溃恢复——硬崩溃时最后几个事件可能丢失，但最后一次 `flush()` 之前的所有内容都在磁盘上。对关键事件（error、session_end）使用 `fd.flush()` + `os.fsync()`。
3. **pydantic 序列化。** 事件是 pydantic 模型。使用 `.model_dump_json()` 进行序列化。这确保所有时间戳都是 ISO 8601 格式，所有类型都是 JSON 兼容的。
4. **通过 asyncio 实现线程安全。** 由于 JSONL 日志记录器是单个消费者协程按顺序处理自己的队列，因此每会话文件不需要文件锁。

**示例:**
```python
# Source: D-10, D-11 已锁定决策；模式已通过 WebSearch 验证
import os
import json
import asyncio
from datetime import datetime, timezone
from pathlib import Path

class JSONLLogger:
    def __init__(self, session_id: str, log_dir: str = "logs/sessions"):
        self.session_id = session_id
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.filepath = self.log_dir / f"{date_str}_{session_id}.jsonl"
        self._file = None
        self._seq = 0

    async def start(self, bus: EventBus) -> None:
        self._file = open(self.filepath, "a", encoding="utf-8")
        self._queue = await bus.subscribe("*")  # 订阅所有事件
        # 启动消费者任务
        asyncio.create_task(self._consume())

    async def _consume(self) -> None:
        while True:
            event = await self._queue.get()
            if event is None:  # 关闭哨兵
                break
            await self._write(event)
            self._queue.task_done()

    async def _write(self, event: dict) -> None:
        entry = {
            "seq": self._seq,
            "ts": datetime.now(timezone.utc).isoformat(),
            "session_id": self.session_id,
            **event  # 包含 type, data, step_num 等
        }
        self._seq += 1
        self._file.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self._file.flush()  # 崩溃恢复

    async def stop(self) -> None:
        if self._file:
            os.fsync(self._file.fileno())  # 确保所有数据落盘
            self._file.close()
```

### 需要避免的反模式

- **反模式: `while True` 配合临时 break 条件。** 导致意大利面式的退出逻辑和不可测试的终止行为。应使用显式的 FSM 枚举配合每个状态的处理方法（已锁定 D-02）。
- **反模式: 用字符串格式化代替 `json.dumps()` 编写 JSONL。** 当工具输出包含引号、换行符或 Unicode 时会导致格式错误的 JSON。始终通过 stdlib `json` 或 pydantic 的 `.model_dump_json()` 进行序列化。
- **反模式: 所有消费者共享一个全局 `asyncio.Queue`。** 这会形成竞争消费模式，事件被分发而非复制——CLI 消费了事件，日志记录器就会错过它们。每个订阅者必须有自己独立的队列才能实现扇出。
- **反模式: 在会话开始后再启动 JSONL 日志记录器。** 日志记录器订阅之前发布的事件将永久丢失（没有历史重放）。应先订阅日志记录器，再启动 Agent 循环。
- **反模式: 仅在 OBSERVE 结束时检查 `step_count >= max_steps`。** LLM 可能在最后一个允许的步骤上进行工具调用，产生 OBSERVE→REASON 转换，并在下一次检查时立即超出预算。应在进入 OBSERVE→REASON 时检查，以防止"多一次工具调用"的问题。

## 不要重复造轮子

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| 流式工具调用参数累积 | 从 `ChatCompletionChunk` 增量手动累积 | `client.beta.chat.completions.stream()` | beta stream API 自动累积碎片化的工具调用参数；手动累积需要处理跨块的基于索引的 JSON 拼接——SDK 已正确实现此功能 |
| 事件对象 JSON 序列化 | 对包含不可序列化类型的 dict 使用 `json.dumps()` | pydantic `.model_dump_json()` | pydantic 自动将 datetime→ISO 8601、Enum→字符串、嵌套模型→嵌套 dict |
| 终端光标控制实现实时更新 | 直接使用 ANSI 转义码 | Rich `Live` 上下文管理器 | Rich 处理终端大小调整、光标定位、备用屏幕缓冲区和跨平台兼容性 |
| 多个后台任务的事件循环 | 手动 `asyncio.gather()` 配合临时取消操作 | `asyncio.TaskGroup` (Python 3.11+) | TaskGroup 提供结构化并发：如果一个任务失败，所有同级任务都会被取消——防止孤儿任务 |
| 文件路径构造 | 用 `/` 和 `\\` 进行字符串拼接 | `pathlib.Path` | 跨平台，处理 `mkdir(parents=True)`、路径拼接和父目录遍历 |
| 循环检测的哈希计算 | 对 dict 手动使用 `hash()` 或 `str()` | `hashlib.sha256(json.dumps(args, sort_keys=True).encode())` | Python 的 `hash()` 每个进程随机化（PYTHONHASHSEED）；需要确定性哈希才能跨会话比较 |

**核心见解:** OpenAI SDK 的 beta stream API 处理了流式工具调用中最难的部分——跨块累积部分 JSON 参数——因此我们不需要自己实现 JSON Patch 解析。仅此一点就足以证明使用 `client.beta.chat.completions.stream()` 而非 `client.chat.completions.create(stream=True)`。

## 常见陷阱

### 陷阱 1: 工具调用参数跨块碎片化到达

**可能出现的问题:** 当使用 `stream=True` 配合 `client.chat.completions.create()` 时，每个 `ChatCompletionChunk` 可能只包含工具调用 JSON 参数的部分片段。简单拼接这些片段会产生格式错误的 JSON（例如重复键、缺少括号）。

**为什么会发生:** OpenAI 以文本增量的形式流式输出工具调用参数，类似于流式文本内容。参数 `{"city": "San Francisco"}` 可能以 `{"cit`、`y":`、` "San `、`Francisco"}` 的形式到达。

**如何避免:** 使用 `client.beta.chat.completions.stream()`，它内部处理了累积。`tool_calls.function.arguments.delta` 事件同时提供 `arguments_delta`（新片段）和 `arguments`（累积的完整字符串）。`tool_calls.function.arguments.done` 事件提供 `parsed_arguments`（如果提供了 pydantic 工具 schema，则为完全解析的 JSON）。

**警告信号:** 在流式传输中期尝试解析工具参数时出现 `json.JSONDecodeError`；工具调用的参数看起来像不完整的 JSON。

### 陷阱 2: 消息列表无限制增长

**可能出现的问题:** 每个 REASON→ACT→OBSERVE 循环会增加 2-3 条消息（assistant 的 tool_calls、tool result(s)）。经过 15 个步骤，每个步骤 2 个工具调用，消息列表可能达到 45+ 条消息，占用 20K+ Token 的上下文窗口。

**为什么会发生:** ReAct 循环自然地累积消息。这是预期行为——Phase 3（上下文管理）将添加压缩功能。对于 Phase 1，我们接受这是一个已知限制。

**如何避免（Phase 1 缓解措施）:** 设置合理的步骤预算（默认 15）。对于没有压缩功能的 Phase 1 范围，将总消息数限制为辅助守卫（例如最多 50 条消息）。将此记录为 Phase 1 的已知约束。

**警告信号:** LLM 响应变慢（需要处理更多上下文）；API 返回"context length exceeded"错误。

### 陷阱 3: Event Bus 背压导致死锁

**可能出现的问题:** 如果消费者的 `asyncio.Queue` 已满（达到 maxsize），`await queue.put(event)` 会阻塞。如果发布者是 FSM 本身，整个 Agent 循环会停滞等待慢速消费者排空。

**为什么会发生:** JSONL 日志记录器执行同步文件 I/O（`file.write()` + `file.flush()`）。如果磁盘较慢或日志目录位于网络文件系统上，写入可能滞后于事件生成。

**如何避免:** 使用有界队列（`maxsize=256`）配合 put 超时: `await asyncio.wait_for(queue.put(event), timeout=1.0)`。如果超时触发，记录警告并丢弃事件（对于非关键消费者）或缓冲在内存中（对于日志记录器）。或者，为日志记录器使用无界队列并设置高水位线告警。

**警告信号:** Agent 在快速工具执行期间无故暂停；CLI 停止更新；内存使用增长。

### 陷阱 4: session_end 与日志记录器关闭之间的竞态条件

**可能出现的问题:** FSM 发布 `session_end`，转换到 FINISH，然后主协程返回。JSONL 日志记录器的 `_consume()` 任务尚未处理 `session_end` 事件。asyncio 事件循环停止，`session_end` 行永远不会写入磁盘。

**为什么会发生:** 事件发布是异步的，但主协程返回后事件循环立即关闭。后台任务可能尚未排空其队列。

**如何避免:** FSM 完成后，向所有订阅者队列发布哨兵事件（`None`），然后 `await asyncio.gather(*consumer_tasks)` 等待所有消费者排空并退出。哨兵信号表示"不再有新事件——排空你已有的内容然后停止。"

**警告信号:** JSONL 日志文件缺失最后 1-2 个事件；`session_end` 字段从未出现在日志中。

### 陷阱 5: Token 流式输出与步骤显示交错不正确

**可能出现的问题:** CLI 在步骤 1 的工具结果仍在渲染时显示了步骤 2 的内容。分层事件结构因为步骤边界未正确同步而被破坏。

**为什么会发生:** FSM 在很短时间内连续触发步骤 N 的 `step_end` 和步骤 N+1 的 `step_start`。如果 Rich `Live` 刷新发生在这两个事件之间，显示可能呈现在部分状态上。

**如何避免:** 使用 `Live.update()` 方法原子性地将整个可渲染组件替换为当前状态。不要依赖对单个面板的增量更新。在每次事件触发时从当前状态构建完整的可渲染组件树，然后执行 `live.update(renderable)`。

**警告信号:** CLI 同时显示来自不同步骤的步骤面板；"step 2/10"标签却显示步骤 1 的内容。

## 代码示例

来自官方来源的已验证模式:

### OpenAI Beta 流式输出与工具调用
```python
# Source: https://github.com/openai/openai-python/blob/main/helpers.md
# [VERIFIED: OpenAI SDK source]
from openai import AsyncOpenAI

client = AsyncOpenAI(base_url="https://api.openai.com/v1", api_key="...")

async with client.beta.chat.completions.stream(
    model='gpt-4o-2024-08-06',
    messages=[
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "What's the weather in Tokyo?"},
    ],
    tools=[{
        "type": "function",
        "function": {
            "name": "get_weather",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"]
            }
        }
    }],
) as stream:
    async for event in stream:
        if event.type == 'content.delta':
            print(event.delta, flush=True, end='')  # Token 级文本流式输出
        elif event.type == 'tool_calls.function.arguments.delta':
            # event.name, event.index, event.arguments (累积), event.arguments_delta
            pass
        elif event.type == 'tool_calls.function.arguments.done':
            # event.name, event.arguments (完整), event.parsed_arguments
            print(f"\nTool call: {event.name}({event.arguments})")

    # 流完成后
    completion = await stream.get_final_completion()
    choice = completion.choices[0]
    if choice.message.tool_calls:
        for tc in choice.message.tool_calls:
            print(f"Executing: {tc.function.name}({tc.function.arguments})")
```

### Rich Live 渲染与异步数据
```python
# Source: https://rich.readthedocs.io/en/stable/live.html
# [VERIFIED: Rich official docs]
from rich.live import Live
from rich.panel import Panel
from rich.markdown import Markdown
from rich.layout import Layout
import asyncio

class CLIAgentRenderer:
    def __init__(self, bus):
        self.bus = bus
        self.current_step = 0
        self.step_content = ""
        self.tool_calls = []

    def build_renderable(self):
        """从当前状态构建完整的终端布局。"""
        layout = Layout()
        layout.split(
            Layout(Panel(f"Step {self.current_step}", title="Progress"), size=3),
            Layout(Panel(Markdown(self.step_content), title="Thinking"), ratio=2),
            Layout(self._build_tool_panel(), size=5),
        )
        return layout

    async def run(self):
        queue = await self.bus.subscribe("*")
        with Live(self.build_renderable(), refresh_per_second=10, transient=True) as live:
            while True:
                event = await queue.get()
                if event is None:
                    break
                # 根据事件类型更新状态
                if event["type"] == "llm_token":
                    self.step_content += event["data"]["content_delta"]
                elif event["type"] == "step_start":
                    self.current_step = event["data"]["step_num"]
                    self.step_content = ""
                # 原子性地更新显示
                live.update(self.build_renderable())
```

### JSONL 会话日志记录器（最小实现）
```python
# Source: Append-per-event pattern verified via WebSearch
# [CITED: multiple production agent implementations]
import json
import os
from datetime import datetime, timezone
from pathlib import Path

class SessionRecorder:
    def __init__(self, session_id: str, log_dir: str = "logs/sessions"):
        self.session_id = session_id
        self.path = Path(log_dir) / f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}_{session_id}.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._seq = 0
        self._file = open(self.path, "a", encoding="utf-8")

    def record(self, event: dict) -> None:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "session_id": self.session_id,
            "seq": self._seq,
            **event,
        }
        self._seq += 1
        self._file.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self._file.flush()

    def close(self) -> None:
        os.fsync(self._file.fileno())
        self._file.close()
```

## 技术演进

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `client.chat.completions.create(stream=True)` 返回裸的 `Stream[ChatCompletionChunk]` | `client.beta.chat.completions.stream()` 配合类型化事件和自动累积 | openai SDK ~v2.20 (2025 年底) | 消除了手动累积工具调用参数的需求；直接提供 `parsed_arguments` |
| 原始 `while` 循环配合布尔标志 | 显式 FSM 配合 `Enum` 状态和处理方法 | 自 2025 年起成为行业最佳实践 | 可测试的转换、清晰的退出条件、更好的错误恢复 |
| `asyncio.gather(*tasks)` 配合临时取消操作 | `asyncio.TaskGroup` (结构化并发) | Python 3.11 (2022)，到 3.13 成为标准 | 如果一个消费者任务失败，所有同级任务会被干净地取消——防止孤儿后台任务 |
| 手动使用 `json.dumps` 处理临时 dict 的 JSONL | pydantic 模型配合 `.model_dump_json()` | pydantic v2 (2023) | 类型安全的事件 schema，自动 datetime/Enum 序列化，发布时验证 |

**已弃用/过时:**
- 使用 `asyncio.wait(return_when=FIRST_COMPLETED)` 管理消费者任务——改用 `asyncio.TaskGroup`（更清晰的取消语义）
- 手动对 datetime 对象进行 JSON 序列化——pydantic 自动处理 ISO 8601 转换

## 假设日志

> 列出本研究中所有标记为 `[ASSUMED]`/`[假设]` 的断言。规划者和讨论阶段使用此部分
> 来确定哪些决策需要在执行前与用户确认。

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | ERROR 状态在 Phase 1 中应为终止状态（不可恢复） | Architecture Patterns Pattern 1 | 低风险——如果用户希望 ERROR 可恢复，需要检查点基础设施，该设施要到 Phase 4 才可用 |
| A2 | `client.beta.chat.completions.stream()` 尽管带有"beta"标签，在生产环境中足够稳定 | Standard Stack | 中风险——如果 beta API 在 Phase 5 之前有破坏性变更，我们需要重构为 `create(stream=True)` 配合手动累积 |
| A3 | 在目标系统上可以通过 `uv venv --python 3.13` 安装 Python 3.13 | Environment Availability | 中风险——Python 3.13 预编译二进制文件可能并非在所有平台上都可用；回退到 3.12 无需 API 更改 |
| A4 | Phase 1 的工具 schema 格式（纯 dict）可以接受；Phase 2 将通过 `@tool` 装饰器引入 pydantic 生成的 schema | Architecture Patterns Pattern 1 | 低风险——openai SDK 同时接受 dict 和 pydantic 工具 schema；迁移路径是增量的 |
| A5 | 消息结构验证（CORE-05）应在每次 LLM 调用前验证 OpenAI API 消息格式，检查 `tool_call` assistant 消息是否有对应的 `tool` 角色消息 | Architecture Patterns Pattern 1 | 低风险——这是 OpenAI API 的标准要求；违反它无论如何都会导致 API 错误 |

## 待解决问题

1. **LLM 配置方式（Claude 酌情决定领域）**
   - 已知信息: openai SDK 支持 `base_url`、`api_key`、`model` 作为构造参数和每次调用参数。环境变量 `OPENAI_API_KEY`、`OPENAI_BASE_URL` 会被自动读取。
   - 尚不明确: 我们应该支持 CLI 参数（`--api-key`、`--model`）、配置文件（TOML/YAML），还是仅依赖环境变量？
   - 建议: **环境变量作为主要方式，CLI 参数覆盖作为辅助。** 这是最简单的方法，符合 12-factor 应用模式。配置文件增加了复杂度，对 Phase 1 没有益处。

2. **消息结构验证的严格程度（CORE-05，Claude 酌情决定领域）**
   - 已知信息: OpenAI API 要求交替使用 user/assistant/tool 角色，并有特定的配对规则。违反这些规则会导致 API 错误。
   - 尚不明确: 我们应该严格验证（拒绝并阻止发送）还是宽容处理（尝试通过插入虚拟消息来修复）？
   - 建议: **严格验证——在发送前拒绝格式错误的消息。** 宽容修复可能掩盖 Agent 逻辑中的 bug。错误应该被明确地暴露，以便从根源上解决问题。

3. **现在是否应该将 openai 客户端封装在 LLMClient 抽象层中？**
   - 已知信息: CLAUDE.md 建议在 v2 中使用 Provider Adapter 模式（`LLMClient` 协议）以支持多提供商。Phase 1 仅使用 OpenAI。
   - 尚不明确: 这个抽象层对 Phase 1 来说是否值得增加一层间接调用，还是应该直接调用 openai，等到 Phase 2 或扩展时再添加适配器？
   - 建议: **在 Phase 1 中直接调用 openai。** 适配器模式增加了一层，在初始开发期间会使调试更加复杂。当真正需要第二个提供商时（v2）再添加抽象层。FSM 应该引用一个具体的 `LLMClient` 类，以后可以改为抽象类。

4. **Event Bus 是否应该支持通配符主题订阅？**
   - 已知信息: 所有三个计划中的消费者（CLI、JSONL、SSE）都需要所有事件。通配符（例如 `step.*`、`llm.*`）允许更细粒度的订阅。但 Phase 1 的消费者都"订阅所有内容"。
   - 尚不明确: 通配符匹配的实现复杂度现在是否合理？
   - 建议: **从仅支持精确主题匹配开始，配合一个 `"*"` 通配符表示"所有主题"。** 这实现起来很简单，覆盖了所有 Phase 1 的用例。当有消费者需要选择性订阅时，再添加分层通配符（`step.*`）。

## 环境可用性

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | Entire project | YES | 3.12.3 (system) | uv 可按需安装 3.13 |
| Python 3.13 | CLAUDE.md specified | NO | — | Python 3.12 完全兼容；3.13 增加了调度器改进但不需要 API 更改 |
| uv | Package management | YES | 0.11.12 | pip + venv |
| openai SDK | LLM calls (CORE-02, CORE-03) | NO | — | 必须通过 uv 安装 |
| pydantic | Event schemas | NO | — | 必须通过 uv 安装 |
| rich | CLI display | YES (system) | 13.7.1 | CLAUDE.md 要求 15.0.0 — 通过 uv 升级 |
| httpx | openai SDK dependency | NO | — | 随 openai 自动安装 |
| pytest | Testing | NO | — | 必须通过 uv 安装 |
| pytest-asyncio | Async testing | NO | — | 必须通过 uv 安装 |
| ruff | Linting | NO | — | 必须通过 uv 安装 |
| Node.js | Not needed in Phase 1 | YES | v24.15.0 | — |
| OpenAI API key | LLM calls | UNKNOWN | — | 用户必须提供；环境变量 `OPENAI_API_KEY` |

**无回退方案的缺失依赖:**
- **openai SDK (2.38.0):** 必须安装——阻塞项。无回退方案；整个 Agent 循环依赖它。
- **pydantic (2.13.4):** 必须安装——阻塞项。事件 schema 验证需要它。
- **Python 3.13:** 非严格要求。Python 3.12.3 对所有 Phase 1 代码都能完全相同地工作。CLAUDE.md 推荐 3.13 是为了调度器改进和 io_uring（性能方面，而非功能方面）。如果可用，使用 `uv venv --python 3.13`；否则 3.12 也可以接受。

**有回退方案的缺失依赖:**
- **rich 15.0.0:** 系统有 13.7.1。`Live` 上下文管理器在两个版本中都存在。建议升级到 15.0.0 以获得最新功能，但对 Phase 1 不是阻塞项。

## 验证架构

### 测试框架

| Property | Value |
|----------|-------|
| Framework | pytest + pytest-asyncio |
| Config file | 无——见 Wave 0 |
| Quick run command | `python -m pytest tests/ -x --timeout=10` |
| Full suite command | `python -m pytest tests/ -v --cov=loopai --cov-report=term-missing` |

### Phase 需求——测试映射表

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| CORE-01 | FSM 转换: 无 tool_calls 时 REASON→FINISH | unit | `pytest tests/test_fsm.py::test_reason_to_finish_no_tool_calls -x` | no (Wave 0) |
| CORE-01 | FSM 转换: REASON→ACT→OBSERVE→REASON 循环 | unit | `pytest tests/test_fsm.py::test_full_react_cycle -x` | no (Wave 0) |
| CORE-01 | FSM 转换: 未处理异常 → ERROR | unit | `pytest tests/test_fsm.py::test_error_state_on_exception -x` | no (Wave 0) |
| CORE-02 | LLM 客户端: 可配置 base_url 和 api_key | unit | `pytest tests/test_llm_client.py::test_client_configuration -x` | no (Wave 0) |
| CORE-02 | LLM 客户端: 发送正确消息并接收响应 | integration | `pytest tests/test_llm_client.py::test_chat_completion -x` | no (Wave 0) |
| CORE-03 | 流式输出: 内容增量产生 llm_token 事件 | unit | `pytest tests/test_event_bus.py::test_llm_token_streaming -x` | no (Wave 0) |
| CORE-03 | 流式输出: step_start 和 step_end 事件界定每个循环 | unit | `pytest tests/test_fsm.py::test_step_events_emitted -x` | no (Wave 0) |
| CORE-04 | 预算: 80% 警告已注入消息中 | unit | `pytest tests/test_guards.py::test_budget_warning_at_80_percent -x` | no (Wave 0) |
| CORE-04 | 预算: 预算耗尽时提供最终摘要机会 | unit | `pytest tests/test_guards.py::test_budget_exhausted_final_summary -x` | no (Wave 0) |
| CORE-05 | 验证: 包含孤立 tool_call 的消息被拒绝 | unit | `pytest tests/test_guards.py::test_orphan_tool_call_rejected -x` | no (Wave 0) |
| CORE-05 | 验证: 合法的交替消息通过验证 | unit | `pytest tests/test_guards.py::test_valid_messages_pass -x` | no (Wave 0) |
| CORE-06 | 循环检测: 3 次以上相同工具调用 → 触发干预 | unit | `pytest tests/test_guards.py::test_loop_detection_warns_at_3 -x` | no (Wave 0) |
| CORE-06 | 循环检测: 5 次以上相同工具调用 → 执行被阻止 | unit | `pytest tests/test_guards.py::test_loop_detection_blocks_at_5 -x` | no (Wave 0) |
| CORE-07 | JSONL: 会话开始时创建日志文件 | unit | `pytest tests/test_jsonl_logger.py::test_log_file_created -x` | no (Wave 0) |
| CORE-07 | JSONL: 每个事件产生一行格式正确的日志 | unit | `pytest tests/test_jsonl_logger.py::test_event_to_line_mapping -x` | no (Wave 0) |

### 采样频率

- **每次任务提交时:** `python -m pytest tests/ -x --timeout=10` (快速，遇到第一个失败即停止)
- **每次 Wave 合并时:** `python -m pytest tests/ -v` (完整套件)
- **Phase 关卡:** 完整套件全绿色 + 覆盖率报告，在 `/gsd-verify-work` 之前

### Wave 0 待办事项

- [ ] `tests/conftest.py` — 共享 fixtures: mock EventBus、mock AsyncOpenAI、带受控状态的 test Session
- [ ] `tests/test_fsm.py` — CORE-01 状态机转换 (6 个测试用例)
- [ ] `tests/test_event_bus.py` — CORE-03 事件发布/订阅、扇出、排序、关闭 (5 个测试用例)
- [ ] `tests/test_guards.py` — CORE-04 预算、CORE-05 消息验证、CORE-06 循环检测 (8 个测试用例)
- [ ] `tests/test_jsonl_logger.py` — CORE-07 日志文件创建、格式、追加行为 (4 个测试用例)
- [ ] `tests/test_llm_client.py` — CORE-02 配置、模拟响应 (3 个测试用例)
- [ ] `tests/test_cli_renderer.py` — Rich 可渲染输出验证 (3 个测试用例)
- [ ] 框架安装: `uv pip install pytest pytest-asyncio pytest-cov pytest-timeout`
- [ ] `pytest.ini` 或 `pyproject.toml` — 配置 asyncio 模式、测试路径、超时

## 安全领域

### 适用的 ASVS 分类

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | 适用 | OpenAI API 密钥管理——必须从环境变量或安全配置中读取，绝不硬编码 |
| V3 Session Management | 不适用 | Phase 5 (Web 前端) 将需要会话认证；Phase 1 仅 CLI，无会话 |
| V4 Access Control | 不适用 | Phase 1 是单用户 CLI；无需多用户访问控制 |
| V5 Input Validation | 适用 | pydantic 事件 schema 验证在发布时进行；LLM 发送前进行消息结构验证 |
| V6 Cryptography | 不适用 | Phase 1 中没有加密操作 |

### Python + LLM 已知威胁模式

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| 源代码或 git 历史中的 API 密钥 | 信息泄露 | 仅从环境变量读取；将 `.env` 和 `.env.*` 添加到 `.gitignore` |
| LLM 输出被当作可执行代码处理 | 权限提升 | 绝不 `eval()` 或 `exec()` LLM 输出；使用 `json.loads()` 解析；CLAUDE.md 明确禁止 `eval()/exec()` |
| 通过工具输出进行提示注入 | 欺骗 | 工具结果包裹在 `tool` 角色消息中并附带 `tool_call_id`——永不合并到用户消息中 |
| 事件日志包含敏感数据（API 密钥、PII） | 信息泄露 | JSONL 日志记录器应从记录的事件中脱敏或排除 `api_key` 字段；日志文件权限应为 `0o600` |
| 无界队列导致无限制内存增长 | 拒绝服务 | 使用有界队列 `maxsize=256`；在溢出时丢弃或告警 |

## 来源

### 一手来源（高置信度）
- [OpenAI Python SDK GitHub](https://github.com/openai/openai-python/blob/main/helpers.md) — 已验证流式 API、事件类型、异步用法 [Context7: /openai/openai-python]
- [OpenAI Python SDK 源码](https://raw.githubusercontent.com/openai/openai-python/main/src/openai/lib/streaming/chat/_completions.py) — 已验证 11 种事件类型、ChatCompletionStreamManager、事件属性 [WebFetch]
- [PyPI: openai 2.38.0](https://pypi.org/project/openai/) — 最新版本于 2026-05-27 通过 JSON API 确认
- [Rich 官方文档](https://rich.readthedocs.io/en/stable/live.html) — 已验证 Live、Panel、Markdown、update、console API [Context7: /websites/rich_readthedocs_io_en_stable]
- [Rich 源码](https://rich.readthedocs.io/en/stable/reference/live.html) — Live 类参数和方法 [Context7]
- [PyPI: pydantic 2.13.4](https://pypi.org/project/pydantic/) — 版本于 2026-05-06 验证
- [PyPI: rich 15.0.0](https://pypi.org/project/rich/) — 版本于 2026-04-12 验证
- [Python 3.13 发布说明](https://www.python.org/downloads/release/python-31313/) — asyncio 改进已验证

### 二手来源（中等置信度）
- ReAct FSM 最佳实践——多个来源一致认同基于枚举的状态机、并发工具执行、超时守卫 [WebSearch: 2026 生产实现]
- asyncio.Queue 发布/订阅模式——在多个技术文章中验证 [WebSearch]
- JSONL 追加写入事件模式——在多个 Agent 框架实现中验证 [WebSearch]
- 循环检测模式——`tool-loop-guard`、Katalyst ToolRepetitionDetector、OpenDerisk DoomLoopDetector 均使用基于哈希的签名匹配 [WebSearch]

### 三手来源（低置信度）
- `client.beta.chat.completions.stream()` 的稳定性声明——"beta"标签表明可能存在 API 变更；已标记为假设 A2

## 元数据

**置信度说明:**
- 标准技术栈: 高——所有版本已对照 PyPI 验证，所有 API 已通过 Context7 或 SDK 源码确认
- 架构: 高——FSM 和 Event Bus 模式已相当成熟；beta stream API 已从 SDK 源码确认
- 陷阱: 中——陷阱来自社区经验和 SDK 源码分析；Phase 1 范围限制了问题产生面积

**研究日期:** 2026-05-27
**有效期至:** 2026-06-27 (30 天——稳定的库，openai SDK 更新的风险较小)
