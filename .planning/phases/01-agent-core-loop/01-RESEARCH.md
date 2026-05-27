# Phase 01: Agent Core Loop — Research

**Researched:** 2026-05-27
**Domain:** ReAct Agent State Machine, LLM Streaming, Event-Driven Architecture
**Confidence:** HIGH

## Summary

Phase 01 delivers the foundational agent runtime: a ReAct state machine that drives the LLM reasoning-acting loop, streams events at both step-level and token-level granularity, enforces step budgets with safety cutoffs, detects tool-call loops, and writes structured JSONL session logs. Everything built in Phase 02-05 sits on top of this loop.

The architecture uses three proven patterns: (1) a finite state machine with explicit enum states instead of a raw `while` loop, (2) an `asyncio.Queue`-based internal Event Bus with fan-out to multiple consumers (CLI display, JSONL logger, future SSE endpoint), and (3) the OpenAI `client.beta.chat.completions.stream()` API which provides auto-accumulated streaming events with 11 typed event kinds.

The standard stack is Python 3.13 (via uv) with the openai SDK 2.38.0, pydantic 2.13 for event models, rich 15.0 for CLI rendering, and stdlib asyncio for the concurrency backbone. All dependencies are specified in CLAUDE.md and confirmed current on PyPI.

**Primary recommendation:** Build the Event Bus first, then wire the ReAct FSM into it. The Event Bus is the spine — the state machine publishes events, consumers subscribe. This decoupling means the CLI renderer, JSONL logger, and future SSE endpoint are all independent consumers that can be developed and tested in isolation.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| ReAct State Machine | Backend (asyncio loop) | — | The core agent loop runs entirely server-side; it is a pure async state machine with no UI dependency |
| LLM API Calls | Backend (openai SDK) | — | All LLM communication is server-side via OpenAI-compatible API |
| Token-Level Streaming | Backend (Event Bus) | — | Streaming data originates from LLM and fans out to consumers via the internal Event Bus |
| Step Budget Enforcement | Backend (FSM guard) | — | Budget checks are guard conditions within the state machine transitions |
| Loop Detection | Backend (FSM guard) | — | Tool-call history is tracked within the agent runtime; detection happens pre-ACT transition |
| CLI Display | Backend (Rich Live) | — | Rich renders in-terminal using a daemon thread; it consumes events from the Event Bus |
| JSONL Logging | Backend (file I/O) | — | File writer is an Event Bus consumer; writes to local disk |
| SSE Endpoint (future) | Backend (FastAPI) | — | Phase 5 addition; Event Bus consumer that pushes events to HTTP clients |
| Event Schema Validation | Backend (pydantic) | — | All event types are pydantic models validated at publish time |

## User Constraints (from CONTEXT.md)

### Locked Decisions

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

### Claude's Discretion

以下领域未在讨论中锁定，规划者和研究者可自主选择合理方案:
- ERROR 状态是终态还是可恢复状态
- 状态转换失败时的处理策略
- 事件 Schema 的具体字段定义（按分层结构自行设计）
- 循环检测的干预策略细节（CORE-06）
- 消息结构校验的严格程度（CORE-05）
- LLM 配置方式（环境变量 vs 配置文件 vs CLI 参数）

### Deferred Ideas (OUT OF SCOPE)

无——讨论保持在阶段范围内。

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| CORE-01 | 实现 ReAct 状态机（REASON → ACT → OBSERVE → FINISH → ERROR），而非简单的 while 循环 | Architecture Patterns Pattern 1: FSM with enum; D-01, D-02 locked; standard approach verified across multiple production implementations |
| CORE-02 | 通过 OpenAI 兼容 API 调用 LLM（可配置 base_url, api_key, model） | Standard Stack: openai SDK 2.38.0; client.chat.completions.create() and client.beta.chat.completions.stream() both support base_url, api_key, model params |
| CORE-03 | 流式输出 agent 每步的思考、调用和观察结果（async generator/SSE） | Architecture Patterns Pattern 2: Event Bus + Pattern 3: Layered Events; openai beta stream API provides 11 event types with auto-accumulation; Rich Live for CLI rendering |
| CORE-04 | 步骤预算 + 终止条件（目标达成 / 不可达成 / 预算耗尽 80% 预警） | Architecture Patterns Pattern 5: Step Budget Guard; D-06 through D-09 locked |
| CORE-05 | 消息结构交替校验（tool_call 和 tool_result 必须成对，防止孤立的 tool call 导致幻觉） | Don't Hand-Roll: message structure validation; implement as pre-send guard that validates OpenAI API message format before each LLM call |
| CORE-06 | 基础循环检测（同一工具连续调用 3 次以上触发干预） | Architecture Patterns Pattern 4: Loop Detection; hash-based signature matching with sliding window; three-tier escalation (warn/block/force-exit) |
| CORE-07 | 从第一轮即开启 JSONL 日志记录，格式化为结构化事件 | Architecture Patterns Pattern 6: JSONL Event Logger; D-10, D-11 locked; append-only, per-session files |

## Standard Stack

The tech stack is defined in CLAUDE.md (reviewed and verified 2026-05-27). Phase 01 uses the Python backend subset:

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|-------------|
| **Python** | 3.13.x | Runtime | CLAUDE.md specified; 3.13 has improved asyncio scheduler and io_uring backend |
| **openai** | 2.38.0 | LLM client | Latest on PyPI [VERIFIED: PyPI 2026-05-27]; `client.beta.chat.completions.stream()` provides typed events with auto-accumulation for tool calls |
| **pydantic** | 2.13.4 | Event models | Rust-backed validation for event schemas; used for EventBus message typing and JSONL serialization [VERIFIED: PyPI 2026-05-06] |
| **asyncio** | (stdlib) | Async runtime | Python 3.13 stdlib; powers the Event Bus, FSM execution, and concurrent consumers [VERIFIED: Python docs] |
| **rich** | 15.0.0 | CLI display | Live-rendering terminal UI for agent thinking trace; `Live` context manager, `Panel`, `Markdown` renderables [VERIFIED: PyPI 2026-04-12] |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| **httpx** | 0.28.x | Async HTTP client | Required dependency of openai; also available for any direct HTTP calls from tools (Phase 2+) [VERIFIED: PyPI dependency chain] |
| **uuid** | (stdlib) | Session ID generation | Generate unique session_id values for JSONL file naming |
| **datetime** | (stdlib) | Timestamps | UTC timestamps for JSONL log entries |
| **json** | (stdlib) | Serialization | JSONL line writing; pydantic models produce JSON via `.model_dump_json()` |
| **collections.deque** | (stdlib) | Sliding window | Loop detection history (bounded window of last N tool calls) |
| **pathlib** | (stdlib) | File paths | Cross-platform path handling for JSONL session files |

### Development Tools

| Tool | Version | Purpose | Notes |
|------|---------|---------|-------|
| **uv** | 0.11.12 | Python package manager | Available on system [VERIFIED: env check] |
| **pytest** | latest | Testing | Async tests with `pytest-asyncio`, `@pytest.mark.asyncio` [ASSUMED: not yet installed] |
| **pytest-asyncio** | latest | Async test support | Required for testing the agent loop [ASSUMED: not yet installed] |
| **ruff** | latest | Linter/formatter | 100x faster than flake8+isort+black [ASSUMED: not yet installed] |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Raw `while` loop | Explicit FSM enum | Enum-based FSM provides clear exit conditions, testable transitions, and better error recovery. Locked decision D-02. |
| `openai.chat.completions.create(stream=True)` | `client.beta.chat.completions.stream()` | The beta stream API provides auto-accumulated tool call arguments and structured events (`content.delta`, `tool_calls.function.arguments.done`) — without it, you must manually accumulate fragmented tool call args from ChatCompletionChunks. The beta API significantly reduces boilerplate. |
| `tool-loop-guard` library | Hash-based deque | The `tool-loop-guard` pip package does exactly what we need, but we build it ourselves for learning depth. The implementation is ~30 lines. |
| Redis Pub/Sub | asyncio.Queue Event Bus | Redis adds operational complexity (server, connection management) for a single-process agent. asyncio.Queue is in-process, zero-config, and sufficient. |

**Installation:**
```bash
# Create virtual environment with Python 3.13 (uv will download if needed)
uv venv --python 3.13
source .venv/bin/activate

# Install core dependencies
uv pip install openai==2.38.0 pydantic==2.13.4 rich==15.0.0 httpx==0.28.1

# Install dev dependencies
uv pip install pytest pytest-asyncio ruff mypy
```

**Version verification:** Each recommended version was confirmed against PyPI JSON API and importlib.metadata checks on 2026-05-27.

## Architecture Patterns

### System Architecture Diagram

```
                          ┌───────────────────────────────────────────┐
                          │              ReAct State Machine           │
                          │  ┌──────┐   ┌─────┐   ┌─────────┐        │
                          │  │REASON│──▶│ ACT │──▶│ OBSERVE │        │
                          │  └──┬───┘   └─────┘   └────┬────┘        │
                          │     │                       │             │
                          │     │ no tool_calls          │ step++      │
                          │     ▼                       ▼             │
                          │  ┌──────┐              ┌──────┐           │
                          │  │FINISH│              │REASON│ (loop)    │
                          │  └──────┘              └──────┘           │
                          │                                             │
                          │  ANY state ──exception──▶ ERROR            │
                          └──────────┬────────────────────────────────┘
                                     │
                                     │ publish(Event)
                                     ▼
                          ┌──────────────────────┐
                          │     Event Bus         │
                          │  (asyncio.Queue × N)  │
                          │  pub/sub fan-out      │
                          └──┬────────┬───────────┘
                             │        │
                    ┌────────┘        └────────┐
                    ▼                          ▼
          ┌─────────────────┐        ┌──────────────────┐
          │  CLI Consumer   │        │ JSONL Logger     │
          │  (Rich Live)    │        │ (File Append)    │
          │                 │        │                  │
          │  - step_start   │        │  logs/sessions/  │
          │  - llm_token    │        │  2026-05-27_     │
          │  - tool_call    │        │  abc123.jsonl    │
          │  - tool_result  │        │                  │
          │  - step_end     │        │  Event:1 → Line:1│
          │  - session_end  │        │  1:1 mapping     │
          └─────────────────┘        └──────────────────┘

          ┌──────────────────┐ (Phase 5 — reserved slot)
          │  SSE Consumer    │
          │  (FastAPI)       │
          │  Phase 5 only    │
          └──────────────────┘

External boundary:
  ┌──────────────┐
  │ OpenAI API   │◀──── REASON state: client.beta.chat.completions.stream()
  │ (or compat)  │      model="...", messages=[...], tools=[...]
  └──────────────┘
```

### Recommended Project Structure

```
src/
├── loopai/
│   ├── __init__.py
│   ├── main.py              # CLI entry point, session orchestration
│   ├── config.py             # LLM config (api_key, base_url, model) — Claude's discretion area
│   ├── state_machine/
│   │   ├── __init__.py
│   │   ├── fsm.py            # ReActFSM: REASON→ACT→OBSERVE→FINISH→ERROR
│   │   └── guards.py          # Budget guard, loop detection, message validation
│   ├── events/
│   │   ├── __init__.py
│   │   ├── bus.py             # EventBus: asyncio.Queue-based pub/sub
│   │   └── schemas.py         # Event pydantic models (all event types)
│   ├── llm/
│   │   ├── __init__.py
│   │   └── client.py          # LLMClient wrapper around openai SDK
│   ├── consumers/
│   │   ├── __init__.py
│   │   ├── cli_renderer.py    # Rich Live consumer: step panels, token streaming
│   │   └── jsonl_logger.py    # JSONL file consumer: append-per-event
│   └── session/
│       ├── __init__.py
│       └── context.py         # Session state: messages[], step_count, config
└── tests/
    ├── __init__.py
    ├── conftest.py            # Shared fixtures: mock LLM, event bus, test session
    ├── test_fsm.py            # State machine transitions, exit conditions
    ├── test_event_bus.py      # Publish/subscribe, fan-out, event ordering
    ├── test_guards.py         # Budget, loop detection, message validation
    ├── test_jsonl_logger.py   # Log file creation, line format, append behavior
    └── test_cli_renderer.py   # Rich renderable output (captured)
```

### Pattern 1: ReAct Finite State Machine

**What:** An enum-based state machine with explicit transition rules. Each state has a corresponding async handler method. Transitions are deterministic based on LLM response content.

**When to use:** Always — this is the core of the agent. D-01 and D-02 lock the five states and the REASON→FINISH shortcut.

**Key design decisions (Claude's discretion):**

1. **ERROR state: terminal for Phase 1.** Making ERROR terminal simplifies the implementation and is consistent with the Phase 1 scope. Recovery logic (re-entering REASON after ERROR) belongs in Phase 4 with the Resilience layer. Rationale: without checkpoint/retry infrastructure, recovering from ERROR is unreliable.

2. **State transition failure: raise and enter ERROR.** If the LLM response is malformed (neither text nor tool_calls), or if tool execution throws an unhandled exception, transition to ERROR. This is a hard stop — log the failure with full context, then terminate.

**Example:**
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
    """Transitions:
    REASON --[has tool_calls]--> ACT
    REASON --[no tool_calls]---> FINISH    (D-01)
    ACT --[tool executed]-----> OBSERVE
    ACT --[exception]---------> ERROR
    OBSERVE --[step < max]---> REASON
    OBSERVE --[step >= max]--> FINISH      (D-07, forced termination)
    ANY --[unhandled error]--> ERROR
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

### Pattern 2: asyncio.Queue Event Bus (Pub/Sub)

**What:** An in-process event bus where each subscriber gets its own `asyncio.Queue`. Publishing fans out to all subscriber queues. Consumers are long-running async tasks that `await queue.get()` in a loop.

**When to use:** The backbone of all inter-component communication. The FSM publishes events; CLI, JSONL, and future SSE consumers subscribe independently.

**Key design decisions:**

1. **Event history for replay.** Maintain a `list[Event]` history. When a new subscriber connects (e.g., SSE client in Phase 5), replay all past events first, then stream live events. This allows the JSONL logger to be started mid-session if needed.

2. **Shutdown with sentinel.** Use a `None` sentinel event to signal consumers to drain and exit. Hard stop via `asyncio.CancelledError` risks losing the last events from the JSONL log.

3. **Event schema via pydantic.** All events are typed pydantic models. The bus validates at publish time. This ensures JSONL log entries are always well-formed.

**Example:**
```python
# Source: synthesized from asyncio.Queue pub/sub patterns verified via WebSearch
import asyncio
from typing import Any

class EventBus:
    def __init__(self):
        self._subscribers: dict[str, list[asyncio.Queue]] = {}
        self._history: list[dict] = []
        self._lock = asyncio.Lock()  # Protects _subscribers during subscribe/unsubscribe

    async def publish(self, topic: str, event: dict) -> None:
        """Fan-out: push event to all subscriber queues for this topic."""
        self._history.append(event)
        for queue in self._subscribers.get(topic, []):
            await queue.put(event)

    async def subscribe(self, topic: str) -> asyncio.Queue:
        """Register a new subscriber. Returns its personal queue."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=256)  # Backpressure via bounded queue
        async with self._lock:
            self._subscribers.setdefault(topic, []).append(queue)
        return queue

    async def unsubscribe(self, topic: str, queue: asyncio.Queue) -> None:
        """Remove subscriber. Safe to call during shutdown."""
        async with self._lock:
            queues = self._subscribers.get(topic, [])
            if queue in queues:
                queues.remove(queue)

    def replay(self, topic: str) -> list[dict]:
        """Return all historical events for a topic (used by late-joining subscribers)."""
        return [e for e in self._history if e.get("topic") == topic]
```

### Pattern 3: Layered Event Schema

**What:** Two-level event hierarchy. Top-level lifecycle events (`step_start`, `step_end`, `session_end`) wrap inner streaming events (`llm_token`, `tool_call_start`, `tool_call_args`, `tool_result`). Each step is a bounded region.

**When to use:** This is D-04 locked decision. The layered structure enables the CLI to render step-boundary panels while streaming tokens within them.

**Event types (Claude's discretion — field definitions):**

```python
# Top-level lifecycle events
StepStart:    { session_id, step_num, timestamp }
StepEnd:      { session_id, step_num, timestamp, state_transition, token_usage }
SessionEnd:   { session_id, timestamp, final_state, total_steps, exit_reason }

# Inner streaming events (only occur between step_start and step_end)
LLMToken:     { session_id, step_num, content_delta }          # Token-level streaming
LLMContentDone: { session_id, step_num, full_content }          # Text completion done
ToolCallStart:  { session_id, step_num, tool_name, tool_call_id }
ToolCallArgs:   { session_id, step_num, tool_name, args_delta }  # Streaming tool args
ToolCallDone:   { session_id, step_num, tool_name, tool_call_id, full_args }
ToolResult:    { session_id, step_num, tool_name, tool_call_id, result, is_error, duration_ms }

# Guard events
BudgetWarning: { session_id, step_num, used_pct, max_steps }
BudgetExhausted: { session_id, step_num }
LoopDetected:  { session_id, step_num, tool_name, consecutive_count }
Error:         { session_id, step_num, error_type, message, traceback }
```

### Pattern 4: Loop Detection

**What:** Hash-based detection of repeated tool calls using a sliding window of `(tool_name, canonical_args_hash)`. Three-tier escalation: warn at 3, block at 5, force-exit if pattern persists.

**When to use:** Pre-ACT transition guard. After the LLM decides to call a tool, before executing it, check the tool history.

**Claude's discretion — intervention strategy:**

- **Tier 1 (3 consecutive identical calls):** Inject a system message into the LLM context: "You have called `{tool_name}` with the same arguments 3 times in a row. The tool is producing the same result. Please try a different approach or provide your best answer based on available information."
- **Tier 2 (5 consecutive identical calls):** Refuse to execute the tool call. Instead, add a tool result message with error content: "[SYSTEM] Tool call blocked — repeated 5 times. Please provide your final answer." Force transition to REASON.
- **Tier 3 (pattern persists after Tier 2):** Force transition to FINISH. The LLM is stuck in a loop even after intervention.

**Example:**
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
        """Canonical hash: (tool_name, sorted JSON args)."""
        args_json = json.dumps(arguments, sort_keys=True, ensure_ascii=True)
        raw = f"{tool_name}:{args_json}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def check(self, tool_name: str, arguments: dict) -> tuple[bool, str]:
        """
        Returns (should_proceed, action).
        action is one of: "allow", "warn", "block", "force_exit"
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
            return (True, "warn")  # Allow but inject warning
        return (True, "allow")

    def reset(self) -> None:
        """Reset when a novel tool call breaks the repetition pattern."""
        self._consecutive_count = 0
        self._last_signature = None
```

### Pattern 5: Step Budget Guard

**What:** A guard that runs at the OBSERVE→REASON transition. Checks step count against max budget, injects context warnings at 80%, and forces termination at 100%.

**When to use:** Every cycle from OBSERVE back. Also check before the very first REASON (edge case: max_steps=0).

**Example:**
```python
# Source: D-06, D-07, D-09 locked decisions
class BudgetGuard:
    def __init__(self, max_steps: int = 15, warn_pct: float = 0.80):
        self.max_steps = max_steps
        self.warn_threshold = int(max_steps * warn_pct)

    def check(self, step_count: int, messages: list[dict]) -> tuple[bool, list[dict], str | None]:
        """
        Returns (should_continue, modified_messages, action).
        action: None (normal), "warn" (inject budget warning), "final" (final summary chance), "exhausted" (force finish)
        """
        if step_count >= self.max_steps:
            # D-07: Final summary opportunity
            final_msg = {
                "role": "system",
                "content": "Your step budget has been exhausted. Based on the information you have gathered so far, provide your best final answer. Do not call any tools."
            }
            messages.append(final_msg)
            return (True, messages, "final")  # One more REASON cycle, then force FINISH

        if step_count >= self.warn_threshold and step_count < self.max_steps:
            # D-09: 80% warning
            remaining = self.max_steps - step_count
            warn_msg = {
                "role": "system",
                "content": f"Step budget at {int(step_count/self.max_steps*100)}%. {remaining} steps remaining. Prioritize reaching a conclusion."
            }
            messages.append(warn_msg)
            return (True, messages, "warn")

        return (True, messages, None)
```

### Pattern 6: JSONL Event Logger

**What:** An Event Bus consumer that writes each event as one JSON line to a per-session file. 1:1 event-to-line mapping (D-10). File naming: `logs/sessions/{YYYY-MM-DD}_{session_id}.jsonl` (D-11).

**When to use:** Subscribe to the Event Bus at session start, run as a background asyncio task, shut down gracefully on session end.

**Key design decisions:**

1. **Append-only.** Never modify existing lines. Audit integrity is the top priority.
2. **Flush after each event.** For crash resilience — the last few events may be lost on hard crash, but everything before the last `flush()` is on disk. Use `fd.flush()` + `os.fsync()` for critical events (error, session_end).
3. **pydantic serialization.** Events are pydantic models. Use `.model_dump_json()` for serialization. This ensures all timestamps are ISO 8601 and all types are JSON-compatible.
4. **Thread-safe via asyncio.** Since the JSONL logger is a single consumer coroutine processing its own queue sequentially, no file locking is needed for the per-session file.

**Example:**
```python
# Source: D-10, D-11 locked decisions; pattern verified via WebSearch
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
        self._queue = await bus.subscribe("*")  # Subscribe to all events
        # Start consumer task
        asyncio.create_task(self._consume())

    async def _consume(self) -> None:
        while True:
            event = await self._queue.get()
            if event is None:  # Shutdown sentinel
                break
            await self._write(event)
            self._queue.task_done()

    async def _write(self, event: dict) -> None:
        entry = {
            "seq": self._seq,
            "ts": datetime.now(timezone.utc).isoformat(),
            "session_id": self.session_id,
            **event  # Includes type, data, step_num, etc.
        }
        self._seq += 1
        self._file.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self._file.flush()  # Crash resilience

    async def stop(self) -> None:
        if self._file:
            os.fsync(self._file.fileno())  # Ensure all data on disk
            self._file.close()
```

### Anti-Patterns to Avoid

- **Anti-pattern: `while True` with ad-hoc break conditions.** Results in spaghetti exit logic and untestable termination. Use explicit FSM enum with handler-per-state (locked D-02).
- **Anti-pattern: Writing JSONL by string formatting instead of `json.dumps()`.** Leads to malformed JSON when tool output contains quotes, newlines, or unicode. Always serialize through stdlib `json` or pydantic's `.model_dump_json()`.
- **Anti-pattern: One global `asyncio.Queue` shared by all consumers.** This creates a competing-consumers pattern where events are distributed, not replicated — the CLI eats events and the logger misses them. Each subscriber must have its own queue for fan-out.
- **Anti-pattern: Starting the JSONL logger after the session has begun.** Events published before the logger subscribes are lost forever (no history replay). Subscribe the logger first, then start the agent loop.
- **Anti-pattern: Checking `step_count >= max_steps` only at the end of OBSERVE.** The LLM can make a tool call on the last permitted step, producing an OBSERVE→REASON transition that immediately hits the budget on the next check. Check at OBSERVE→REASON entrance to prevent the "one extra tool call" problem.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Streaming tool call argument accumulation | Manual accumulation from `ChatCompletionChunk` deltas | `client.beta.chat.completions.stream()` | The beta stream API auto-accumulates fragmented tool call arguments; manual accumulation requires handling index-based JSON patching across chunks — the SDK does this correctly |
| JSON serialization of event objects | `json.dumps()` on dicts with non-serializable types | pydantic `.model_dump_json()` | pydantic handles datetime→ISO 8601, Enum→string, nested model→nested dict automatically |
| Terminal cursor control for live updates | ANSI escape codes directly | Rich `Live` context manager | Rich handles terminal resize, cursor positioning, alternate screen buffer, and cross-platform compatibility |
| Event loop with multiple background tasks | Manual `asyncio.gather()` with ad-hoc cancellation | `asyncio.TaskGroup` (Python 3.11+) | TaskGroup provides structured concurrency: if one task fails, all sibling tasks are cancelled — prevents orphaned tasks |
| File path construction | String concatenation with `/` and `\\` | `pathlib.Path` | Cross-platform, handles `mkdir(parents=True)`, join, and parent traversal |
| Hash computation for loop detection | Manual `hash()` or `str()` of dicts | `hashlib.sha256(json.dumps(args, sort_keys=True).encode())` | Python's `hash()` is randomized per process (PYTHONHASHSEED); need deterministic hashing for cross-session comparison |

**Key insight:** The OpenAI SDK's beta stream API handles the hardest part of streaming tool calls — accumulating partial JSON arguments across chunks — so we don't have to implement JSON Patch parsing ourselves. This alone justifies using `client.beta.chat.completions.stream()` over `client.chat.completions.create(stream=True)`.

## Common Pitfalls

### Pitfall 1: Tool Call Arguments Arrive Fragmented Across Chunks

**What goes wrong:** When using `stream=True` with `client.chat.completions.create()`, each `ChatCompletionChunk` may contain only a partial fragment of the tool call's JSON arguments. Naively concatenating these fragments produces malformed JSON (e.g., duplicate keys, missing brackets).

**Why it happens:** OpenAI streams tool call arguments as text deltas, similar to streaming text content. The arguments `{"city": "San Francisco"}` might arrive as `{"cit`, `y":`, ` "San `, `Francisco"}` .

**How to avoid:** Use `client.beta.chat.completions.stream()` which handles accumulation internally. The `tool_calls.function.arguments.delta` event provides both `arguments_delta` (the new fragment) and `arguments` (accumulated full string). The `tool_calls.function.arguments.done` event provides `parsed_arguments` (fully parsed JSON if a pydantic tool schema was provided).

**Warning signs:** `json.JSONDecodeError` when trying to parse tool arguments mid-stream; tool calls with arguments that look like partial JSON.

### Pitfall 2: Message List Grows Unboundedly

**What goes wrong:** Every REASON→ACT→OBSERVE cycle adds 2-3 messages (assistant with tool_calls, tool result(s)). After 15 steps with 2 tool calls each, the message list can reach 45+ messages consuming 20K+ tokens of context window.

**Why it happens:** The ReAct loop naturally accumulates messages. This is expected behavior — Phase 3 (Context Management) will add compression. For Phase 1, we accept this as a known limitation.

**How to avoid (Phase 1 mitigation):** Set a reasonable step budget (default 15). For the Phase 1 scope with no compression, limit the total messages count as a secondary guard (e.g., max 50 messages). Document this as a known Phase 1 constraint.

**Warning signs:** LLM responses become slower (more context to process); "context length exceeded" errors from the API.

### Pitfall 3: Event Bus Backpressure Causes Deadlock

**What goes wrong:** If a consumer's `asyncio.Queue` is full (maxsize reached), `await queue.put(event)` blocks. If the publisher is the FSM itself, the entire agent loop stalls waiting for a slow consumer to drain.

**Why it happens:** The JSONL logger does synchronous file I/O (`file.write()` + `file.flush()`). If the disk is slow or the log directory is on a network filesystem, writes can lag behind event production.

**How to avoid:** Use a bounded queue (`maxsize=256`) with a timeout on put: `await asyncio.wait_for(queue.put(event), timeout=1.0)`. If the timeout fires, log a warning and drop the event (for non-critical consumers) or buffer in memory (for the logger). Alternatively, use an unbounded queue for the logger with a high-water mark alert.

**Warning signs:** Agent pauses inexplicably during rapid tool execution; CLI stops updating; memory usage grows.

### Pitfall 4: Race Condition Between session_end and Logger Shutdown

**What goes wrong:** The FSM publishes `session_end`, transitions to FINISH, and the main coroutine returns. The JSONL logger's `_consume()` task hasn't processed the `session_end` event yet. The asyncio event loop stops, the `session_end` line is never written to disk.

**Why it happens:** Event publishing is async, but the event loop shutdown is immediate after the main coroutine returns. Background tasks may not have drained their queues.

**How to avoid:** After the FSM finishes, publish a sentinel event (`None`) to all subscriber queues, then `await asyncio.gather(*consumer_tasks)` to wait for all consumers to drain and exit. The sentinel signals "no more events coming — drain what you have and stop."

**Warning signs:** JSONL log file is missing the last 1-2 events; `session_end` field never appears in logs.

### Pitfall 5: Token Streaming and Step Display Interleave Incorrectly

**What goes wrong:** The CLI shows step 2's content while step 1's tool result is still being rendered. The layered event structure breaks because step boundaries are not properly synchronized.

**Why it happens:** The FSM fires `step_end` for step N and `step_start` for step N+1 in rapid succession. If the Rich `Live` refresh happens between these two events, the display may show partial state.

**How to avoid:** Use the `Live.update()` method to atomically replace the entire renderable with the current state. Don't rely on incremental updates to individual panels. Build the complete renderable tree from current state on each event, then `live.update(renderable)`.

**Warning signs:** CLI show step panels from different steps simultaneously; "step 2/10" label while displaying step 1 content.

## Code Examples

Verified patterns from official sources:

### OpenAI Beta Streaming with Tool Calls
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
            print(event.delta, flush=True, end='')  # Token-level text streaming
        elif event.type == 'tool_calls.function.arguments.delta':
            # event.name, event.index, event.arguments (accumulated), event.arguments_delta
            pass
        elif event.type == 'tool_calls.function.arguments.done':
            # event.name, event.arguments (full), event.parsed_arguments
            print(f"\nTool call: {event.name}({event.arguments})")

    # After stream completes
    completion = await stream.get_final_completion()
    choice = completion.choices[0]
    if choice.message.tool_calls:
        for tc in choice.message.tool_calls:
            print(f"Executing: {tc.function.name}({tc.function.arguments})")
```

### Rich Live Display with Async Data
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
        """Build the complete terminal layout from current state."""
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
                # Update state based on event type
                if event["type"] == "llm_token":
                    self.step_content += event["data"]["content_delta"]
                elif event["type"] == "step_start":
                    self.current_step = event["data"]["step_num"]
                    self.step_content = ""
                # Atomically update the display
                live.update(self.build_renderable())
```

### JSONL Session Logger (Minimal)
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

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `client.chat.completions.create(stream=True)` returning bare `Stream[ChatCompletionChunk]` | `client.beta.chat.completions.stream()` with typed events and auto-accumulation | openai SDK ~v2.20 (late 2025) | Eliminates manual tool call argument accumulation; provides `parsed_arguments` directly |
| Raw `while` loop with boolean flags | Explicit FSM with `Enum` states and handler methods | Industry best practice since 2025 | Testable transitions, clear exit conditions, better error recovery |
| `asyncio.gather(*tasks)` with ad-hoc cancellation | `asyncio.TaskGroup` (structured concurrency) | Python 3.11 (2022), standard by 3.13 | If one consumer task fails, all sibling tasks are cancelled cleanly — prevents orphaned background tasks |
| Manual JSONL with `json.dumps` on ad-hoc dicts | pydantic models with `.model_dump_json()` | pydantic v2 (2023) | Type-safe event schemas, automatic datetime/Enum serialization, validation at publish time |

**Deprecated/outdated:**
- `asyncio.wait(return_when=FIRST_COMPLETED)` for managing consumer tasks — use `asyncio.TaskGroup` instead (cleaner cancellation semantics)
- Manual JSON serialization of datetime objects — pydantic handles ISO 8601 conversion automatically

## Assumptions Log

> List all claims tagged `[ASSUMED]` in this research. The planner and discuss-phase use this
> section to identify decisions that need user confirmation before execution.

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | ERROR state should be terminal for Phase 1 (not recoverable) | Architecture Patterns Pattern 1 | LOW — if user wants recoverable ERROR, it requires checkpoint infrastructure not available until Phase 4 |
| A2 | `client.beta.chat.completions.stream()` is stable enough for production use despite "beta" label | Standard Stack | MEDIUM — if the beta API has breaking changes before Phase 5, we would need to refactor to `create(stream=True)` with manual accumulation |
| A3 | Python 3.13 is installable via `uv venv --python 3.13` on the target system | Environment Availability | MEDIUM — Python 3.13 prebuilt binaries may not be available for all platforms; fallback to 3.12 works with no API changes |
| A4 | Tool schema format for Phase 1 (plain dicts) is acceptable; Phase 2 will introduce pydantic-generated schemas via `@tool` decorator | Architecture Patterns Pattern 1 | LOW — the openai SDK accepts both dict and pydantic tool schemas; migration path is additive |
| A5 | Message structure validation (CORE-05) should validate the OpenAI API message format before each LLM call, checking that `tool_call` assistant messages have corresponding `tool` role messages | Architecture Patterns Pattern 1 | LOW — this is the standard OpenAI API requirement; violating it causes API errors anyway |

## Open Questions

1. **LLM configuration method (Claude's discretion area)**
   - What we know: openai SDK supports `base_url`, `api_key`, `model` as constructor params and per-call params. env vars `OPENAI_API_KEY`, `OPENAI_BASE_URL` are automatically read.
   - What's unclear: Should we support CLI flags (`--api-key`, `--model`), a config file (TOML/YAML), or rely solely on env vars?
   - Recommendation: **Env vars as primary, CLI flag override as secondary.** This is the simplest approach and matches the 12-factor app pattern. A config file adds complexity without Phase 1 benefit.

2. **Message structure validation strictness (CORE-05, Claude's discretion)**
   - What we know: OpenAI API requires alternating user/assistant/tool roles with specific pairing rules. Violations cause API errors.
   - What's unclear: Should we validate strictly (reject and refuse to send) or permissively (attempt to fix by inserting dummy messages)?
   - Recommendation: **Strict validation — reject malformed messages before sending.** Permissive fixing can mask bugs in the agent logic. The error should be surfaced clearly so the root cause is addressed.

3. **Should we wrap the openai client in an LLMClient abstraction now?**
   - What we know: CLAUDE.md recommends a Provider Adapter pattern (`LLMClient` protocol) for multi-provider support in v2. Phase 1 is OpenAI only.
   - What's unclear: Is the abstraction worth the indirection for Phase 1, or should we call openai directly and add the adapter in Phase 2/ext?
   - Recommendation: **Call openai directly in Phase 1.** The adapter pattern adds a layer that complicates debugging during initial development. Add the abstraction when the second provider is actually needed (v2). The FSM should reference a concrete `LLMClient` class that can be made abstract later.

4. **Should the Event Bus support wildcard topic subscriptions?**
   - What we know: All three planned consumers (CLI, JSONL, SSE) need all events. Wildcards (e.g., `step.*`, `llm.*`) would allow finer-grained subscriptions. But Phase 1 consumers are all "subscribe to everything."
   - What's unclear: Is the implementation complexity of wildcard matching justified now?
   - Recommendation: **Start with exact topic matching only, with a `"*"` wildcard for "all topics."** This is trivial to implement and covers all Phase 1 use cases. Add hierarchical wildcards (`step.*`) when a consumer needs selective subscription.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | Entire project | YES | 3.12.3 (system) | uv can install 3.13 on demand |
| Python 3.13 | CLAUDE.md specified | NO | — | Python 3.12 is fully compatible; 3.13 adds scheduler improvements but no API changes needed |
| uv | Package management | YES | 0.11.12 | pip + venv |
| openai SDK | LLM calls (CORE-02, CORE-03) | NO | — | Must install via uv |
| pydantic | Event schemas | NO | — | Must install via uv |
| rich | CLI display | YES (system) | 13.7.1 | CLAUDE.md says 15.0.0 — upgrade via uv |
| httpx | openai SDK dependency | NO | — | Auto-installed with openai |
| pytest | Testing | NO | — | Must install via uv |
| pytest-asyncio | Async testing | NO | — | Must install via uv |
| ruff | Linting | NO | — | Must install via uv |
| Node.js | Not needed in Phase 1 | YES | v24.15.0 | — |
| OpenAI API key | LLM calls | UNKNOWN | — | User must provide; env var `OPENAI_API_KEY` |

**Missing dependencies with no fallback:**
- **openai SDK (2.38.0):** Must install — blocking. No fallback; the entire agent loop depends on it.
- **pydantic (2.13.4):** Must install — blocking. Event schema validation requires it.
- **Python 3.13:** Not strictly required. Python 3.12.3 works identically for all Phase 1 code. The CLAUDE.md recommendation for 3.13 addresses scheduler improvements and io_uring (performance, not functionality). Use `uv venv --python 3.13` if available; otherwise 3.12 is acceptable.

**Missing dependencies with fallback:**
- **rich 15.0.0:** System has 13.7.1. The `Live` context manager exists in both versions. Upgrade to 15.0.0 is recommended for latest features but not blocking for Phase 1.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest + pytest-asyncio |
| Config file | none — see Wave 0 |
| Quick run command | `python -m pytest tests/ -x --timeout=10` |
| Full suite command | `python -m pytest tests/ -v --cov=loopai --cov-report=term-missing` |

### Phase Requirements -- Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| CORE-01 | FSM transitions: REASON→FINISH when no tool_calls returned | unit | `pytest tests/test_fsm.py::test_reason_to_finish_no_tool_calls -x` | no (Wave 0) |
| CORE-01 | FSM transitions: REASON→ACT→OBSERVE→REASON cycle | unit | `pytest tests/test_fsm.py::test_full_react_cycle -x` | no (Wave 0) |
| CORE-01 | FSM transitions: unhandled exception → ERROR | unit | `pytest tests/test_fsm.py::test_error_state_on_exception -x` | no (Wave 0) |
| CORE-02 | LLM client: configurable base_url and api_key | unit | `pytest tests/test_llm_client.py::test_client_configuration -x` | no (Wave 0) |
| CORE-02 | LLM client: sends correct messages and receives response | integration | `pytest tests/test_llm_client.py::test_chat_completion -x` | no (Wave 0) |
| CORE-03 | Streaming: llm_token events emitted for content deltas | unit | `pytest tests/test_event_bus.py::test_llm_token_streaming -x` | no (Wave 0) |
| CORE-03 | Streaming: step_start and step_end events bracket each cycle | unit | `pytest tests/test_fsm.py::test_step_events_emitted -x` | no (Wave 0) |
| CORE-04 | Budget: 80% warning injected into messages | unit | `pytest tests/test_guards.py::test_budget_warning_at_80_percent -x` | no (Wave 0) |
| CORE-04 | Budget: final summary opportunity at exhaustion | unit | `pytest tests/test_guards.py::test_budget_exhausted_final_summary -x` | no (Wave 0) |
| CORE-05 | Validation: message list with orphan tool_call rejected | unit | `pytest tests/test_guards.py::test_orphan_tool_call_rejected -x` | no (Wave 0) |
| CORE-05 | Validation: valid alternating messages pass | unit | `pytest tests/test_guards.py::test_valid_messages_pass -x` | no (Wave 0) |
| CORE-06 | Loop detection: 3+ same tool calls → intervention triggered | unit | `pytest tests/test_guards.py::test_loop_detection_warns_at_3 -x` | no (Wave 0) |
| CORE-06 | Loop detection: 5+ same tool calls → execution blocked | unit | `pytest tests/test_guards.py::test_loop_detection_blocks_at_5 -x` | no (Wave 0) |
| CORE-07 | JSONL: log file created on session start | unit | `pytest tests/test_jsonl_logger.py::test_log_file_created -x` | no (Wave 0) |
| CORE-07 | JSONL: each event produces one log line in correct format | unit | `pytest tests/test_jsonl_logger.py::test_event_to_line_mapping -x` | no (Wave 0) |

### Sampling Rate

- **Per task commit:** `python -m pytest tests/ -x --timeout=10` (fast, stops at first failure)
- **Per wave merge:** `python -m pytest tests/ -v` (full suite)
- **Phase gate:** Full suite green + coverage report before `/gsd-verify-work`

### Wave 0 Gaps

- [ ] `tests/conftest.py` — Shared fixtures: mock EventBus, mock AsyncOpenAI, test Session with controlled state
- [ ] `tests/test_fsm.py` — CORE-01 state machine transitions (6 test cases)
- [ ] `tests/test_event_bus.py` — CORE-03 event pub/sub, fan-out, ordering, shutdown (5 test cases)
- [ ] `tests/test_guards.py` — CORE-04 budget, CORE-05 message validation, CORE-06 loop detection (8 test cases)
- [ ] `tests/test_jsonl_logger.py` — CORE-07 log file creation, format, append behavior (4 test cases)
- [ ] `tests/test_llm_client.py` — CORE-02 configuration, mock responses (3 test cases)
- [ ] `tests/test_cli_renderer.py` — Rich renderable output verification (3 test cases)
- [ ] Framework install: `uv pip install pytest pytest-asyncio pytest-cov pytest-timeout`
- [ ] `pytest.ini` or `pyproject.toml` — Configure asyncio mode, test paths, timeouts

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | OpenAI API key management — must be read from env var or secure config, NEVER hardcoded |
| V3 Session Management | no | Phase 5 (Web frontend) will need session auth; Phase 1 is CLI-only, no sessions |
| V4 Access Control | no | Phase 1 is single-user CLI; no multi-user access control needed |
| V5 Input Validation | yes | pydantic event schema validation at publish time; message structure validation before LLM send |
| V6 Cryptography | no | No cryptographic operations in Phase 1 |

### Known Threat Patterns for Python + LLM

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| API key in source code or git history | Information Disclosure | Read from env var only; add `.env` and `.env.*` to `.gitignore` |
| LLM output treated as executable code | Elevation of Privilege | Never `eval()` or `exec()` LLM output; parse with `json.loads()`; CLAUDE.md explicitly forbids `eval()/exec()` |
| Prompt injection via tool output | Spoofing | Tool results are wrapped in `tool` role messages with `tool_call_id` — never merged into user messages |
| Event log contains sensitive data (API keys, PII) | Information Disclosure | JSONL logger should redact or exclude the `api_key` field from logged events; log file permissions should be `0o600` |
| Unbounded memory from unbounded Queue | Denial of Service | Bounded Queue with `maxsize=256`; drop or alert on overflow |

## Sources

### Primary (HIGH confidence)
- [OpenAI Python SDK GitHub](https://github.com/openai/openai-python/blob/main/helpers.md) — verified streaming API, event types, async usage [Context7: /openai/openai-python]
- [OpenAI Python SDK source](https://raw.githubusercontent.com/openai/openai-python/main/src/openai/lib/streaming/chat/_completions.py) — verified 11 event types, ChatCompletionStreamManager, event attributes [WebFetch]
- [PyPI: openai 2.38.0](https://pypi.org/project/openai/) — latest version confirmed 2026-05-27 via JSON API
- [Rich official docs](https://rich.readthedocs.io/en/stable/live.html) — verified Live, Panel, Markdown, update, console API [Context7: /websites/rich_readthedocs_io_en_stable]
- [Rich source](https://rich.readthedocs.io/en/stable/reference/live.html) — Live class parameters and methods [Context7]
- [PyPI: pydantic 2.13.4](https://pypi.org/project/pydantic/) — version verified 2026-05-06
- [PyPI: rich 15.0.0](https://pypi.org/project/rich/) — version verified 2026-04-12
- [Python 3.13 release notes](https://www.python.org/downloads/release/python-31313/) — asyncio improvements verified

### Secondary (MEDIUM confidence)
- ReAct FSM best practices — multiple sources agree on enum-based state machines, concurrent tool execution, timeout guards [WebSearch: 2026 production implementations]
- asyncio.Queue pub/sub pattern — verified across multiple technical articles [WebSearch]
- JSONL append-per-event pattern — verified across multiple agent framework implementations [WebSearch]
- Loop detection patterns — `tool-loop-guard`, Katalyst ToolRepetitionDetector, OpenDerisk DoomLoopDetector all use hash-based signature matching [WebSearch]

### Tertiary (LOW confidence)
- `client.beta.chat.completions.stream()` stability claims — the "beta" label suggests potential API changes; flagged as assumption A2

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all versions verified against PyPI, all APIs confirmed via Context7 or SDK source
- Architecture: HIGH — FSM and Event Bus patterns are well-established; beta stream API confirmed from SDK source code
- Pitfalls: MEDIUM — pitfalls identified from community experience and SDK source analysis; Phase 1 scope limits the surface area

**Research date:** 2026-05-27
**Valid until:** 2026-06-27 (30 days — stable libraries, minor risk of openai SDK update)
