# Architecture Research: ReAct Agent Harness System

**Domain:** AI Agent framework with harness engineering focus
**Researched:** 2026-05-27
**Confidence:** HIGH (confirmed across multiple production implementations including OpenAI Agents SDK, LangGraph, dataact, AG2, Microsoft Agent Framework)

## Standard Architecture

### System Overview

The architecture follows a **layered harness** pattern where each layer wraps and constrains the layer below, and all layers feed events upward to observability:

```
┌──────────────────────────────────────────────────────────────────┐
│                    OBSERVABILITY LAYER                            │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────────┐  │
│  │ Web Frontend │  │ SSE/WS Event │  │ JSONL Logger +       │  │
│  │ (React/SSE)  │  │ Stream       │  │ Langfuse / Traces    │  │
│  └──────┬───────┘  └──────┬───────┘  └───────────┬───────────┘  │
├─────────┴─────────────────┴─────────────────────┴───────────────┤
│                    ERROR RECOVERY LAYER                           │
│  ┌──────────────────────┐  ┌────────────────────────────────┐   │
│  │ Checkpoint Manager   │  │ Loop Detector + Retry Chain    │   │
│  ├──────────────────────┤  ├────────────────────────────────┤   │
│  │ Serializes state to  │  │ Detects infinite loops,        │   │
│  │ disk/S3; enables     │  │ applies domain-aware recovery  │   │
│  │ pause/resume after   │  │ (error re-injection)           │   │
│  │ crash                │  │                                │   │
│  └──────────────────────┘  └────────────────────────────────┘   │
├──────────────────────────────────────────────────────────────────┤
│                    CONTEXT MANAGEMENT LAYER                        │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  Token Tracker │ Compaction Engine │ Overflow File Store  │  │
│  │  (tiktoken)    │ (85-92% threshold)│ (>80K chars)          │  │
│  └─────────────────────────┬──────────────────────────────────┘  │
│                            │ appends                             │
├────────────────────────────┴─────────────────────────────────────┤
│                    TOOL ABSTRACTION LAYER                          │
│  ┌───────────┐  ┌───────────────┐  ┌────────────────────────┐   │
│  │ Tool Reg. │  │ Sandbox Exec  │  │ Permission Middleware   │   │
│  │ (name →   │  │ (timeout,     │  │ (safe/moderate/        │   │
│  │  callable,│  │  size limit,  │  │  dangerous, with       │   │
│  │  schema,  │  │  error isol.) │  │  HITL approval gates)  │   │
│  │  tier)    │  │               │  │                        │   │
│  └─────┬─────┘  └───────┬───────┘  └───────────┬────────────┘   │
│        └────────────────┴──────────────────────┘                 │
│                            │ calls                                │
├────────────────────────────┴─────────────────────────────────────┤
│                    AGENT LOOP (CORE)                               │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  State Machine: START → REASON → ACT → OBSERVE → FINISH   │  │
│  │                                   └── ERROR ←────────────  │  │
│  │  Provider Adapter: OpenAI / Anthropic / Compatible          │  │
│  │  Max iterations: configurable (50-100), budget tracking     │  │
│  └────────────────────────────────────────────────────────────┘  │
│                            │ reads                                │
├────────────────────────────┴─────────────────────────────────────┤
│                    MESSAGE HISTORY (Append-Only Store)             │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  List[Message] — system prompt + user msgs + tool calls    │  │
│  │  + results. Nothing is ever mutated; append-only design    │  │
│  │  for KV-cache reuse (>80% hit rate) and clean audit trail  │  │
│  └────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | Typical Implementation |
|-----------|----------------|------------------------|
| **Agent Loop** | State machine managing the ReAct cycle (REASON → ACT → OBSERVE). Controls iteration budget, delegates to Provider Adapter. | Python state machine (Enum + dataclass for context). `while` loop over states, not raw `while` over turns. |
| **Provider Adapter** | Normalized interface to LLM providers. Converts internal message format to provider SDK, handles streaming vs non-streaming. | `def get_response(messages, tools) -> Response`. Subclasses for OpenAI, Anthropic. FakeAdapter for tests. |
| **Tool Registry** | Central registry mapping tool names to callable + schema + metadata (permission tier, domain tag). Supports progressive disclosure. | `dict[str, ToolDef]` where ToolDef is a Pydantic model with `name`, `description`, `parameters` (JSON Schema), `func`, `permission_tier`. |
| **Sandbox Executor** | Safe tool execution with timeout, result size limits, exception isolation per tool. | `asyncio.wait_for(func(**args), timeout=30.0)`. Catches exceptions and returns error as tool result (error re-injection). |
| **Permission Middleware** | Intercepts tool requests and enforces tier-based approval: safe (auto), moderate (whitelist check), dangerous (HITL gate). | Middleware wrapping every tool call. Tier 3 pauses loop, surfaces UI, resumes on human approval. |
| **Context Manager** | Tracks total token count via tiktoken. Triggers compaction at 85-92% threshold. Manages file-based overflow for large outputs. | `count_tokens(messages)` → if > threshold: `compact(messages)` via summarization (preserving tool call+result pairs). |
| **Checkpoint Manager** | Serializes full agent state (message history, task pointer, tool permission log) to disk at each iteration. Enables crash recovery. | Serialize to `session-state.json` at every iteration. On restart, detect last checkpoint and resume. Git checkpoints for code tasks. |
| **Loop Detector** | Detects infinite/dead loops via similar-call counting, output similarity, progress audits (no state change across N turns). | Track hash of tool call signatures. If same call seen >3 times in 60s, trigger recovery (summarize, ask LLM to change approach). |
| **Error Re-injector** | On tool failure (error, timeout, invalid params), returns structured error back into LLM context for self-correction. | Tool execution returns `{"error": True, "message": "...", "guidance": "try X instead"}` as tool result. |
| **Event Emitter** | Emits structured events at every state transition, tool call, permission check, compaction event. Feeds both JSONL logger and streaming web frontend. | Python callback or asyncio queue. Each event: `{type, timestamp, session_id, step, data}`. |
| **JSONL Logger** | Appends every turn (with latency, token counts, cache hit/miss) to a structured log file from first turn. Never retrofitted. | `logging` or `json.dumps` per line. Rotating files. |
| **SSE/WebSocket Stream** | Pushes real-time agent state to web frontend: current state, tool calls (with status badges), thoughts, errors. | Async generator → asyncio.Queue → WebSocket/SSE → frontend EventSource. |
| **Web Frontend** | Real-time visualization of agent reasoning chain, tool calls, state transitions, approval gates. | React (or similar) consuming SSE events. Timeline / graph / compact views. |

## Recommended Project Structure

```
loopai/
├── agent/                          # Core agent harness
│   ├── __init__.py
│   ├── loop.py                     # ReAct state machine (Agent Loop)
│   ├── state.py                    # AgentState enum, StepContext dataclass
│   ├── adapters/                   # Provider abstraction
│   │   ├── __init__.py
│   │   ├── base.py                 # Abstract ProviderAdapter interface
│   │   ├── openai.py               # OpenAI-compatible API adapter
│   │   └── fake.py                 # FakeAdapter for testing
│   └── scheduling/                 # Loop execution control
│       ├── __init__.py
│       ├── budget.py               # Token/cost/iteration budget tracking
│       └── scheduling.py           # Concurrency, async runner
│
├── tools/                          # Tool abstraction layer
│   ├── __init__.py
│   ├── registry.py                 # Tool registry (name → ToolDef)
│   ├── types.py                    # ToolDef, ToolResult, PermissionTier
│   ├── sandbox.py                  # Safe execution (timeout, size limit, isolation)
│   ├── permissions.py              # Permission middleware (tiers, HITL gates)
│   └── builtin/                    # Built-in tool implementations
│       ├── __init__.py
│       ├── shell.py                 # Shell command execution (tier 3)
│       ├── filesystem.py           # File I/O tools (tier 2/3)
│       └── diagnostic.py           # Disk/CPU/port diagnostic tools (tier 1-3)
│
├── context/                        # Context management
│   ├── __init__.py
│   ├── token_tracker.py            # Token counting + threshold monitoring
│   ├── compaction.py               # Compaction strategies (sliding window, summarization)
│   ├── overflow.py                 # File-based overflow for large outputs
│   └── history.py                  # Append-only message store
│
├── resilience/                     # Error recovery + safety
│   ├── __init__.py
│   ├── checkpoint.py               # State serialization + crash recovery
│   ├── loop_detector.py            # Infinite loop detection
│   ├── retry.py                    # Backoff + retry chain
│   ├── error_taxonomy.py           # Error classification (5 domains)
│   └── guardrails/                 # Safety guardrails
│       ├── __init__.py
│       ├── input.py                # Input filtering (prompt injection, PII)
│       └── output.py               # Output scanning (PII redaction, safety eval)
│
├── observability/                  # Observability layer
│   ├── __init__.py
│   ├── events.py                   # Event types + emitter (central event bus)
│   ├── logger.py                   # JSONL structured logging
│   ├── stream.py                   # SSE/WebSocket streaming to frontend
│   ├── metrics.py                  # Latency, token usage, error rate collection
│   └── replay.py                   # Session replay for debugging
│
├── web/                            # Web frontend (React or similar)
│   ├── index.html
│   ├── package.json
│   └── src/
│       ├── App.jsx                 # Main UI shell
│       ├── components/
│       │   ├── AgentTimeline.jsx   # Real-time thought/action/observation timeline
│       │   ├── ToolCallCard.jsx    # Tool call visualization with status badges
│       │   ├── ApprovalGate.jsx    # HITL approval gate UI (dangerous operations)
│       │   ├── StateMachine.jsx    # Current state visualization
│       │   └── LogViewer.jsx       # Raw log stream for debugging
│       └── hooks/
│           └── useEventStream.js   # SSE/WebSocket consumer hook
│
├── examples/                       # Business verification scenarios
│   ├── __init__.py
│   └── disk_diagnostics.py         # Disk space diagnosis & cleanup flow
│
└── tests/                          # Tests mirror the source structure
    ├── test_loop.py
    ├── test_tools/
    ├── test_context/
    ├── test_resilience/
    └── test_observability/
```

### Structure Rationale

- **agent/**: The core loop and provider adapter are the foundational components. Separating adapters from the loop enables testing and provider switching without touching the state machine.
- **tools/**: Tool registry and sandbox execution are distinct concerns. Registry is about discoverability and metadata; sandbox is about safety. Permission middleware bridges them and connects to the agent loop's pause/resume mechanism.
- **context/**: Self-contained with its own token counting and compaction strategies. The agent loop calls into it before each LLM call; it owns the message history and decides what to keep.
- **resilience/**: Encompasses both error recovery (checkpoints, loop detection, retry) and proactive safety (guardrails). Co-located because both are about keeping the agent in a safe operating envelope.
- **observability/**: The only layer that reads from all others. Events emitted by every other layer flow through a central event bus here. Web streaming and JSONL logging are separate outputs from the same event stream.
- **web/**: Separate from the Python backend because it's a different technology and deployment model. Communicates with the backend only through the SSE/WebSocket stream and REST APIs.

## Architectural Patterns

### Pattern 1: Layered Harness (Control Plane Separation)

**What:** Each layer of the harness wraps the layer below, adding constraints and capabilities without modifying the lower layer. The agent loop does not know about permissions; the permission middleware does not know about context management.

**When to use:** Always. This is the defining architectural pattern for harness engineering. It enables independent evolution of each concern.

**Trade-offs:**
- More indirection than a flat loop (but indirection here is the point -- it creates safe boundaries)
- Each layer adds latency (sub-millisecond per layer, negligible vs LLM call latency)
- Requires disciplined interface design to avoid leaky abstractions

**Example (permission middleware wrapping tool call):**
```python
class AgentLoop:
    async def execute_tool(self, tool_call: ToolCall) -> ToolResult:
        # Layer 3: Permission check (before execution)
        await self.permission_middleware.check(tool_call)

        # Layer 2: Sandbox execution
        result = await self.sandbox.execute(tool_call)

        # Layer 1: Context management appends result
        await self.context_manager.append(result)

        # Layer 0: Events emitted everywhere
        self.events.emit(ToolExecuted(tool_call, result))
        return result
```

### Pattern 2: State Machine Agent Loop

**What:** Replace the raw while-loop with an explicit state machine. Each state (REASON, ACT, OBSERVE, FINISH, ERROR) has a clear entry condition, execution logic, and next-state transition. This gives precise control flow and trivial observability (just log state transitions).

**When to use:** Any agent beyond the "hello world" ReAct demo. The raw while-loop collapses as soon as you need error recovery, human-in-the-loop, or observability hooks.

**Trade-offs:**
- More boilerplate than a while-loop
- Easier to reason about and debug ("we failed in ACT state because...")
- Natural integration point for async operations and streaming

**Example:**
```python
class AgentState(Enum):
    START = "start"
    REASON = "reason"
    ACT = "act"
    OBSERVE = "observe"
    FINISH = "finish"
    ERROR = "error"

class StepContext:
    step_id: str
    state: AgentState
    messages: list[Message]
    pending_tool_calls: list[ToolCall]
    budget_remaining: float
    retry_count: int

class ReActLoop:
    async def step(self, ctx: StepContext) -> StepContext:
        self.events.emit(StateChanged(ctx.state))

        if ctx.state == AgentState.REASON:
            response = await self.provider.get_response(
                self.context_manager.compact(ctx.messages),
                self.tool_registry.schemas()
            )
            ctx.pending_tool_calls = response.tool_calls
            ctx.messages.append(response.message)
            ctx.budget_remaining -= response.usage.total_tokens

            if response.is_final:
                return ctx.transition(AgentState.FINISH)
            elif ctx.pending_tool_calls:
                return ctx.transition(AgentState.ACT)
            else:
                return ctx.transition(AgentState.OBSERVE)

        elif ctx.state == AgentState.ACT:
            for tc in ctx.pending_tool_calls:
                result = await self.execute_tool(tc)
                ctx.messages.append(result)
            ctx.pending_tool_calls = []
            return ctx.transition(AgentState.OBSERVE)

        elif ctx.state == AgentState.OBSERVE:
            if ctx.budget_remaining <= 0:
                return ctx.transition(AgentState.ERROR)
            return ctx.transition(AgentState.REASON)

        # ... FINISH and ERROR handled similarly
```

### Pattern 3: Append-Only Message Store + Prefix-Stable Prompt

**What:** The message history is a linear, append-only list. Nothing is ever mutated or deleted (even compaction produces new summary messages that are appended, not inserted into the old position). The system prompt is a fixed prefix that never changes between turns; dynamic context is appended as messages at the end of the list.

**When to use:** Every agent. This pattern is the foundation for KV-cache reuse (>80% hit rate), clean audit trails, and reproducible session replay.

**Trade-offs:**
- Appending forever would exhaust context (handled by compaction which summarises old content into new messages, appended to the end)
- Requires discipline to never mutate the system prompt (tempting but destroys KV-cache)
- Compaction trades completeness for cost -- summarised history has information loss

**Example:**
```python
class MessageStore:
    def __init__(self, system_prompt: str):
        self._messages: list[Message] = [Message(role="system", content=system_prompt)]

    def append(self, message: Message):
        self._messages.append(message)

    def get_prefix_stable(self) -> list[Message]:
        """System prompt must never change for KV-cache discipline."""
        first = self._messages[0]
        assert first.role == "system", "Must maintain prefix-stable system prompt"
        return self._messages

    def compact(self, strategy: CompactionStrategy) -> list[Message]:
        """Summarize oldest messages, preserving tool call+result pairs in full."""
        if self.token_count <= self.compaction_threshold:
            return self._messages
        return strategy.apply(self._messages)
```

### Pattern 4: Error Re-Injection (Deterministic Bridge Over Probabilistic Model)

**What:** When a tool call fails, the error is returned as a structured tool result -- not as a Python exception that crashes the loop. The LLM sees the error in its context and can self-correct. Error messages follow a "what went wrong + how to fix it" format that guides the model toward recovery.

**When to use:** All tool execution failures. This is the primary error recovery mechanism for LLM agents. Reserve exceptions for infrastructure failures (network down, provider 500).

**Trade-offs:**
- The LLM might not self-correct (requires loop detection as a fallback)
- Error messages must be carefully crafted to guide without leaking system internals
- Works well for parameter errors and tool execution failures; does not help with system-level errors (rate limits, provider failures)

**Example:**
```python
async def sandbox_execute(tool_call: ToolCall, tool_def: ToolDef) -> ToolResult:
    try:
        result = await asyncio.wait_for(
            tool_def.func(**tool_call.args),
            timeout=tool_def.timeout_seconds
        )
        return ToolResult.ok(result)
    except asyncio.TimeoutError:
        return ToolResult.error(
            message=f"Tool '{tool_call.name}' timed out after {tool_def.timeout_seconds}s",
            guidance=f"Try a smaller input or a different approach"
        )
    except TypeError as e:
        return ToolResult.error(
            message=f"Invalid parameters: {e}",
            guidance=f"Use the tool schema: {tool_def.schema}"
        )
    except Exception as e:
        return ToolResult.error(
            message=f"{tool_call.name} failed: {type(e).__name__}: {e}",
            guidance="Try a different approach"
        )
```

## Data Flow

### Request Flow (Single Turn)

```
User Input
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ REASON                                                            │
│                                                                   │
│  1. Context Manager: check token count, compact if > threshold    │
│  2. Agent Loop: call Provider Adapter with messages + tools       │
│  3. Provider Adapter: normalize to provider format, send to LLM   │
│  4. Response parsed into tool_calls[] or final_answer             │
│  5. Messages appended to MessageStore                             │
│  6. Event emitted: ThoughtGenerated(response)                     │
│  7. SSE stream: push to web frontend                              │
└──────────────────────────────────────────────────────────────────┘
    │
    ▼ (if tool_calls present)
┌─────────────────────────────────────────────────────────────────┐
│ ACT                                                               │
│                                                                   │
│  For each tool_call in parallel or sequentially:                  │
│    1. Permission Middleware: check tier (safe/moderate/dangerous) │
│       a. safe → proceed                                           │
│       b. moderate → check whitelist → proceed or deny             │
│       c. dangerous → emit approval request, PAUSE loop            │
│    2. Sandbox Executor: run with timeout + size limit             │
│    3. On success: return ToolResult                               │
│    4. On failure: Error Re-injector returns structured error      │
│    5. Event emitted: ToolCalled(tool_call_id, status, duration)   │
│    6. SSE stream: update tool call badge (running → done/error)   │
│    7. Result appended to MessageStore                             │
└──────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ OBSERVE                                                           │
│                                                                   │
│  1. Check budget (tokens, iterations, cost)                       │
│     a. Budget exhausted → transition to ERROR / FINISH            │
│     b. Can continue → transition back to REASON                   │
│  2. Looping detection: check for repeated patterns                │
│     a. Detected → inject "change approach" guidance               │
│  3. Checkpoint: serialize full state to disk                      │
│  4. Event emitted: TurnCompleted(summary, latency)                │
│  5. JSONL: append one log line                                    │
└──────────────────────────────────────────────────────────────────┘
    │
    ▼ (loop back to REASON or proceed to FINISH)
┌─────────────────────────────────────────────────────────────────┐
│ FINISH                                                            │
│                                                                   │
│  1. Final output guardrails (PII scan, schema validation)         │
│  2. Return final answer to user                                   │
│  3. Event emitted: SessionComplete(summary)                       │
│  4. SSE stream: final state to frontend                           │
│  5. Checkpoint: final state serialized (for replay)               │
└─────────────────────────────────────────────────────────────────┘
```

### Event Flow (Observability)

```
Every component emits structured events via a central EventBus:

EventBus (asyncio.Queue)
    │
    ├─▶ JSONL Logger (disk) — all events, structured, archival
    │     append to session-{id}.jsonl
    │
    ├─▶ SSE/WebSocket Stream (web frontend) — real-time events only
    │     filters: state_changed, tool_call, tool_result, error, thought
    │     format: { type, timestamp, data }
    │
    └─▶ Metrics Collector (in-memory)
          aggregates: latency p50/p95/p99, error rate, token usage
          periodic flush to log or dashboard
```

### Key Data Flow Rules

1. **Messages flow down and up**: Agent Loop passes messages down (to Provider Adapter → LLM) and receives results up. All messages are append-only in the MessageStore.

2. **Tool calls are intercepted, not executed by the loop**: The loop delegates to Permission Middleware → Sandbox Executor. Results (or errors) flow back as structured ToolResult objects.

3. **Events flow outward only**: Components emit events but never consume them from other layers. The EventBus is a unidirectional dispatch point. This prevents circular dependencies and keeps layers decoupled.

4. **State flows through checkpoints**: The Checkpoint Manager reads full state at the end of each OBSERVE state and writes serialized snapshots. On crash recovery, it reads the latest checkpoint to bootstrap the MessageStore.

5. **Web frontend is a read-only observer**: It receives events but never sends commands back to the loop (except approval gate responses, which are a controlled exception via a dedicated API endpoint).

## Build Order (Phase Dependencies)

The build order follows both dependency constraints and the project's stated "depth directions" (Resilience → Context Engineering → Observability → Memory) while mapping to practical implementation phases:

```
Phase 1: Core Agent Loop
  │
  ▼
Phase 2: Tool Abstraction Layer    ─── (needs loop to call tools)
  │
  ▼
Phase 3: Context Management         ─── (needs working loop + tools to have context worth managing)
  │
  ▼
Phase 4: Error Recovery             ─── (needs context for state persistence)
  │
  ▼
Phase 5: Observability + Frontend   ─── (needs everything to have events worth observing)
  │
  ▼
Phase 6: Memory                     ─── (needs observability to understand memory requirements)
```

### Phase 1: Core Agent Loop
**What:** Minimal ReAct loop with Provider Adapter. Hardcoded system prompt, no tools, just a single mocked tool to prove the loop works.
**Deliverable:** `agent/loop.py`, `agent/state.py`, `agent/adapters/*.py` — a working state machine that calls an LLM and processes tool call responses.
**Does NOT include:** Sandboxing, permissions, context management, error recovery, observability (beyond print debugging).
**Dependency for:** Everything else.

### Phase 2: Tool Abstraction Layer
**What:** Tool registry, sandbox execution, permission tiers (safe/moderate/dangerous with HITL gates for dangerous ops). First real tools: shell execution, filesystem operations, disk diagnostics.
**Deliverable:** `tools/registry.py`, `tools/sandbox.py`, `tools/permissions.py`, `tools/builtin/*.py`.
**Depends on:** Phase 1 (the loop needs to exist to call tools).
**Dependency for:** Phase 3 (context only matters when tools produce real results).

### Phase 3: Context Management
**What:** Token counting, compaction (sliding window then summarization), overflow file store. Append-only message store with prefix-stable system prompt.
**Deliverable:** `context/*.py`.
**Depends on:** Phase 2 (needs real tool output sizes and patterns to calibrate compaction thresholds).
**Dependency for:** Phase 4 (checkpointing needs context state).

### Phase 4: Error Recovery + Resilience
**What:** Checkpoint manager (state serialization + crash recovery), loop detector (infinite loop detection), retry chain with exponential backoff, guardrails (input/output scanning).
**Deliverable:** `resilience/*.py`.
**Depends on:** Phase 3 (checkpointing serializes context state; loop detection needs message history).
**Dependency for:** Phase 5 (observability is most valuable when there are errors to observe).

### Phase 5: Observability + Web Frontend
**What:** Event bus + emitters in all layers, JSONL structured logging, SSE streaming endpoint, React web frontend with timeline/tool call cards/approval gates.
**Deliverable:** `observability/*.py`, `web/` (frontend).
**Depends on:** Phases 1-4 (all layers must emit events).
**Note:** Basic JSONL logging can (and should) be added as early as Phase 1, even if the full observability layer is built here. The recommendation is "JSONL logging from turn 1" — but the structured event bus and web frontend come at this phase.

### Phase 6: Memory (Cross-Session)
**What:** Session persistence beyond a single conversation, intermediate (Redis-backed) and long-term (RAG-backed) memory patterns.
**Depends on:** Phase 5 (observability informs what memory patterns are needed; frontend can visualize memory state).
**Note:** Explicitly deferred per PROJECT.md — not in scope for v1.

### Phase Ordering Rationale

The ordering follows a strict "build bottom-up" dependency chain. Each phase depends on the previous one being stable:

- **Phase 1 must go first** because the loop is the entry point for everything. No loop, no agent.
- **Phase 2 before Phase 3** because compaction thresholds and overflow patterns depend on knowing what real tool outputs look like. Compaction designed in a vacuum (no real tools) would produce wrong thresholds.
- **Phase 3 before Phase 4** because checkpointing needs a well-defined context state to serialize. Loop detection needs the message history that context management provides.
- **Phase 4 before Phase 5** because the most important things to observe are error states and recovery events. Building observability first (before error handling exists) would miss the most interesting events.
- **Phase 5 before Phase 6** because memory patterns need observability data to understand what's worth remembering and what the model actually uses.

## Scaling Considerations

This project is explicitly a learning/exploration project (not production-deployed at scale). However, the architecture is designed to scale to production needs without rewrites:

| Scale | Architecture Adjustments |
|-------|--------------------------|
| Prototype (1 user, local) | All components in-process. SQLite for checkpoints. stdout for logging. |
| Team (5-50 users) | JSONL logs to shared filesystem. Redis for session state. Basic web dashboard. |
| Production (100+ concurrent sessions) | Separate observability collector service. S3 for checkpoints. OpenTelemetry + Langfuse/Arize for tracing. Load-balanced agent runners. |

### Scaling Priorities

1. **First bottleneck: Context window exhaustion in long sessions.** If sessions exceed ~50 turns, compaction frequency becomes critical. Solution: tune compaction threshold, add summarization strategy, implement file-based overflow. All handled in Phase 3 architecture.

2. **Second bottleneck: Observability data volume.** JSONL per-session logging is fine for demos but becomes unwieldy at scale. Solution: structured collector service (Phase 5) that aggregates and samples events before storage.

## Anti-Patterns

### Anti-Pattern 1: The God Loop

**What people do:** One monolithic while-loop that handles tool calls, error recovery, context formatting, and logging in 200+ lines of inline code. This is the default output of most ReAct tutorials.

**Why it's wrong:** Impossible to test individual concerns (need to mock the whole loop). Any change risks breaking everything. Adding error recovery requires untangling the flow. Adding observability means adding print() calls that become tech debt.

**Do this instead:** State machine decomposition (Pattern 2). Each concern is one state or one middleware layer. Test each state in isolation. Compose them in the loop.

### Anti-Pattern 2: Silent Context Loss

**What people do:** Relying on LLM context window to hold everything, without monitoring token counts. When the window fills, the oldest messages silently drop off. The agent loses its task context and produces nonsensical results, but no one knows why.

**Why it's wrong:** Silent data loss with no observable signal. The model keeps producing output, so there is no error to investigate. Debugging requires manually counting tokens across the session.

**Do this instead:** Explicit token tracking with configurable compaction threshold (85-92%). Log compaction events. Never let the model see a truncated context without knowing about it. File-based overflow for large outputs.

### Anti-Pattern 3: Bolted-On Observability

**What people do:** Building the agent first, adding "real logging" later. When production issues arise, there is no baseline data to compare against. The logging infrastructure added later inevitably misses critical events that weren't anticipated.

**Why it's wrong:** You cannot retroactively capture events you didn't anticipate. Building observability first (even simple JSONL logging from turn 1) gives you baseline data and shapes the event taxonomy before the agent is complex enough to hide its behavior.

**Do this instead:** Add JSONL logging in Phase 1. Even if it's just "turn N: REASON state, sent N tokens, got 2 tool calls." The schema will evolve, but the habit and infrastructure are there from day one.

### Anti-Pattern 4: Over-Tooling

**What people do:** Adding 20+ tools to the agent because "the model might need them." The model makes worse decisions with a longer tool list. Erroneous tool selection increases.

**Why it's wrong:** Multiple studies (Vercel, Stripe, Atlan) converge on the same finding: performance degrades with more than ~10 visible tools. The model spends attention budget parsing irrelevant options.

**Do this instead:** Start with 4-5 atomic tools. Use progressive disclosure (register tools but only load relevant ones per task). Apply the Stripe pattern: one agent, one bounded task. If a task needs >5 tools, it's probably two tasks.

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| **OpenAI-compatible API** | Provider Adapter → HTTP POST with JSON body. Handles streaming (SSE) and non-streaming. | Provider selection via config, not import. Adapter pattern enables switching without touching loop. |
| **Web frontend (browser)** | SSE stream from `observability/stream.py`. REST endpoints for HITL approval gates. | Read-only observer model. Approval gates are the only control input from frontend. |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| Agent Loop ↔ Provider Adapter | `ProviderAdapter.get_response(messages, tools) → Response` | Clean interface contract. Adapter owns provider SDK imports. |
| Agent Loop ↔ Tool Registry | `ToolRegistry.resolve(name) → ToolDef` | Tool schema flows into messages; tool function flows into sandbox. |
| Agent Loop ↔ Permission Middleware | `PermissionMiddleware.check(tool_call) → Approval | Deny | PendingHITL` | Three return states: auto-approve, deny, or pause-for-approval. |
| Agent Loop ↔ Context Manager | `ContextManager.get_context(messages) → List[Message]` | Compaction is transparent to the loop. Loop passes full history, gets back compacted version. |
| All Layers ↔ Event Bus | `EventBus.emit(event: AgentEvent)` | Unidirectional. Components never consume events; they only emit. |
| Event Bus ↔ SSE Stream | `StreamWriter.write(event) → None` | Filter for real-time-relevant events only (state transitions, tool status updates, errors). |
| Event Bus ↔ JSONL Logger | `Logger.write(event) → None` | Archives all events. Used for replay, debugging, metrics. |
| SSE Stream ↔ Web Frontend | `EventSource` (browser) consuming SSE stream | Standard HTTP SSE. No custom protocol. Frontend uses declarative React hooks. |
| Web Frontend ↔ HITL Approval API | `POST /approve {session_id, tool_call_id, approved: bool}` | Separate REST endpoint from the event stream. Idempotent. |

## Sources

- **Atlan, "How to Build an AI Agent Harness: A 2026 Complete Guide"** — 10-step harness build process with permission tiers, context compaction at 85-92%, JSONL logging from turn 1, LLM-as-judge verification, and the finding that harness quality (not model quality) determines agent reliability (13.7 benchmark point gain from harness improvements alone). https://atlan.com/know/how-to-build-ai-agent-harness/
- **OpenAI Agents SDK (v0.14+, April 2026)** — Harness/Compute separation architecture, 7-layer model (Runner → AgentRunner → Agent → SandboxAgent → RunState → Session → Model), 5-category tool types. https://openai.com/zh-Hans-CN/index/the-next-evolution-of-the-agents-sdk/
- **DeepWiki: openai/openai-agents-python** — Architecture overview covering the AgentRunner turn loop, sandbox persistence, and manifest abstraction. https://deepwiki.com/openai/openai-agents-python/1-overview
- **LangGraph architecture (Baidu Developer deep-dives)** — State-graph model (State ↔ Node ↔ Edge), three-node ReAct as state machine, checkpoint-based pause/resume, streaming with intermediate state yields, topo-sort scheduling with cycle detection. https://developer.baidu.com/article/detail.html?id=6990984
- **harness-engineering Python toolkit (dr-gareth-roberts)** — Open-source reference implementation with Pydantic-backed Tool + async Dispatcher, last-N compaction, summarization-based compaction, typed lifecycle hooks, PathScope sandbox, ReplayRunner, and PrivacyBoundary. https://github.com/dr-gareth-roberts/harness-engineering
- **dataact (PyPI)** — Minimal production reference harness with handle/snapshot pattern, prefix-stable system prompt, progressive connector disclosure, JSONL turn logging, and explicit adapter boundary. https://pypi.org/project/dataact/
- **Microsoft Agent Framework (March 2026)** — Built-in compaction system with composable strategies (ToolResultCompactionStrategy, SlidingWindowCompactionStrategy, TruncationCompactionStrategy). https://devblogs.microsoft.com/agent-framework/agent-harness-in-agent-framework/
- **arXiv 2509.25370: Agent Error Taxonomy** — 5-domain failure classification (Memory, Reflection, Planning, Action, System) with domain-aware recovery. 24% task completion improvement. https://github.com/bug-ops/zeph/issues/2253
- **agenttrace-ui (Vercel Community)** — React component library for reasoning traces, timeline/graph/compact views, approval gates, built on AI SDK v6. https://community.vercel.com/t/agenttrace-ui-human-in-the-loop-approval-gates-and-reasoning-traces-built-on-ai-sdk-v6/37962
- **Blueprint for Modern Agentic Harness (2026, GitHub Gist)** — Four-tier context management policy (structured outputs → immediate eviction → deferred eviction → compaction → fresh-window restart), cache-first design. https://gist.github.com/amazingvince/52158d00fb8b3ba1b8476bc62bb562e3
- **App.build: Six Principles for Production AI Agents** — Tool minimalism (<10 tools), one agent per bounded task, failure cheap via checkpointing, infrastructure as context. https://www.zenml.io/llmops-database/six-principles-for-building-production-ai-agents
- **Steve Kinney: Designing an AI Gateway** — Gateway as provider abstraction layer, routing strategies (static/weighted/content-based/cost-based), retry chains with fallback. https://stevekinney.com/writing/ai-gateway-durable-workflows
- **AG2 Agent Harness** — Configurable compaction triggers, periodic memory aggregation, bootstrap for initial knowledge seeding. https://docs.ag2.ai/latest/docs/beta/agent_harness/

---
*Architecture research for: loopAI — ReAct Agent Harness*
*Researched: 2026-05-27*
