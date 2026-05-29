# Phase 4: 韧性与恢复 (Resilience and Recovery) - Research

**Researched:** 2026-05-29
**Domain:** Agent resilience, checkpointing, fault tolerance, circuit breaker, layered recovery
**Confidence:** HIGH

## Summary

Phase 4 builds on the existing retry logic in `ToolExecutor`, guard infrastructure in `guards.py`, and EventBus to construct a comprehensive resilience layer. The phase has six requirements (RES-01 through RES-06) that decompose into four major subsystems: (1) JSONL incremental checkpoint manager, (2) upgraded loop detection with classification and metacognitive prompts, (3) guard pipeline (CostGuard + RateLimitGuard + existing TokenGuard), and (4) per-tool circuit breaker. The 4-layer recovery in ToolExecutor (RES-05) is the central integration point where these subsystems converge.

The existing codebase provides strong foundations: `EventBus` for publishing state changes, `Guard` pattern (`check()` returns `(signal, ...)` tuple), `ToolExecutor._execute_with_retry` as the retry loop anchor, and `Session` as the serialization source. The key architectural decision is to keep each subsystem decoupled — the CheckpointManager writes after each FSM step, the circuit breaker wraps tool execution in `_handle_act`, and the guard pipeline lives in `_handle_reason` — all communicating exclusively through the EventBus.

**Primary recommendation:** Create one new module per subsystem (`checkpoint_manager.py`, `circuit_breaker.py`, `failure_registry.py`, `guard_pipeline.py`) plus upgrade existing modules (`executor.py` for 4-layer recovery, `guards.py` for LoopDetector upgrade and new guards). Wire via FSM constructor parameters, keeping the existing dependency injection pattern.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** JSONL 增量追加模式。每步结束后将 Session 状态序列化为一行 JSON 追加写入检查点文件。恢复时重放最后一条记录。
- **D-02:** 检查点文件与 JSONL 日志共用目录结构，通过 session_id 关联。
- **D-03:** 升级现有 ToolExecutor 重试为四层恢复：
  1. **外观修复** — 参数格式修正后重试（如 LLM 给的 JSON 有小错误）
  2. **上下文内重试** — LLM 看到结构化错误信息后自行修正调用
  3. **完整重试+退避** — 已有，IndexError + jitter
  4. **人工升级** — 多次失败后暂停 agent，等用户指令
- **D-04:** 每层有独立的进入条件和升级阈值（连续失败次数）。
- **D-05:** 滑动窗口计数。最近 N 次调用同一工具，失败率 > 50% 则熔断（open），30s 冷却后放行一次试探（half-open），成功则恢复（closed）。
- **D-06:** 熔断状态变化发布事件到 EventBus（circuit_opened / circuit_closed）。

### Claude's Discretion
- 滑动窗口 N 值和冷却时间
- 检查点序列化字段选择
- 四层恢复的具体阈值参数
- 失败注册表的存储格式

### Deferred Ideas (OUT OF SCOPE)
- 跨会话检查点恢复（从历史会话恢复）— Phase 6
- 分布式熔断器（多实例共享状态）— 不在范围内
- 熔断器自动调参 — v2
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| RES-01 | 检查点管理器——关键节点状态序列化 + 崩溃恢复 | Checkpoint JSONL append-only pattern verified. Session dataclass fields identified. Recovery by replaying last record. |
| RES-02 | 循环检测升级——基于分类的干预策略，附元认知提示 | LoopDetector `_consecutive_count` tracked. Need classification (full repeat vs similar vs stuck). Metacognitive prompt injection via system messages. |
| RES-03 | 失败注册表——持久化"不再重复"的操作列表 | Tool name + signature + error. Persist to JSONL. Inject as context block before _handle_reason LLM call. |
| RES-04 | 守卫阶段管道——token 预算守卫、成本守卫、速率限制守卫 | TokenGuard already exists (Phase 3). GuardPipeline orchestrates sequence. CostGuard estimates cost from token count. RateLimitGuard tracks call frequency per tool. |
| RES-05 | 分层自愈恢复——外观修复 → 上下文内重试 → 完整重试 + 退避 → 人工升级 | Refactor `_execute_with_retry` into layered escalation. Layer 1 = JSON repair in executor. Layer 2 = structured error + LLM re-call. Layer 3 = existing backoff. Layer 4 = EventBus event + pause. |
| RES-06 | 熔断器——某工具连续失败后暂停该工具 | Sliding window per tool. Count failures in last N calls. >50% = open. 30s = half-open. Publish state changes. Filter tool from schema when open. |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Checkpoint serialization | API / Backend (FSM) | Storage (JSONL) | Session state is managed by FSM; checkpoint writes after each step. File management alongside JSONL logs. |
| Loop detection upgrade | API / Backend (guards) | — | LoopDetector already runs in FSM._handle_act. Classification logic is a guard enhancement. |
| Failure registry | API / Backend (FSM) | Storage (JSONL) | Persist "never repeat" entries. FSM checks before act. Storage is a simple JSONL file. |
| Guard pipeline | API / Backend (guards) | — | All guards run synchronously in _handle_reason before LLM call. No storage needed. |
| 4-layer recovery | API / Backend (executor) | LLM (layer 2) | ToolExecutor owns retry logic. Layer 2 re-calls LLM. Layer 4 pauses via EventBus. |
| Circuit breaker | API / Backend (executor / FSM) | — | Per-tool state in memory. FSM._handle_act checks before execution. Events published to bus. |

## Standard Stack

### Core — No new external libraries needed

All resilience components are custom implementations building on existing infrastructure:

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `json` | (stdlib) | Checkpoint serialization, failure registry persistence | Already used in JSONLLogger. JSONL format for all persistence. |
| `asyncio` | (stdlib) | Circuit breaker cooldown timers, recovery layer delays | Existing async infrastructure. `asyncio.create_task` for background timers. |
| `collections.deque` | (stdlib) | Circuit breaker sliding window, LoopDetector history | Already used in LoopDetector. Fixed-size deque = natural sliding window. |
| `dataclasses` | (stdlib) | Checkpoint state container, circuit breaker state | Existing Session dataclass pattern. |
| `time` | (stdlib) | Circuit breaker cooldown tracking, rate limiting | `time.monotonic()` for elapsed-time calculations. |

### Supporting — Existing infrastructure extended

| Component | Purpose | Integration Point |
|-----------|---------|-------------------|
| `EventBus` | Publish checkpoint events, circuit state changes, escalation events | Each subsystem publishes via bus |
| `Session` | Serialization source for checkpoint | `session.to_checkpoint_dict()` + `Session.from_checkpoint()` |
| `LoopDetector` | Upgraded with classification + metacognitive prompts | Extended `check()` return signature |
| `ToolExecutor._execute_with_retry` | Upgraded to 4-layer recovery | Refactored into layered escalation |
| `TokenGuard` | Existing, reused in GuardPipeline | No changes needed |
| `ToolRegistry` | Circuit breaker filters schemas for open tools | `get_schemas(exclude_open_tools=set())` |
| `FSM._handle_reason` | GuardPipeline integration point | Wire guards as sequential pipeline |
| `FSM._handle_act` | Circuit breaker + 4-layer recovery integration | Check circuit before executor, handle human escalation |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Custom circuit breaker | `pybreaker` (PyPI) | Pybreaker uses consecutive-fail count, not sliding-window failure rate. Not async-compatible. Custom implementation is required by D-05 spec. |
| Custom circuit breaker | `circuitbreaker` (PyPI) | Supports async but uses consecutive-fail count, not sliding window. Not suitable for D-05. |
| Custom checkpoint | `cloudpickle` + `dill` | Full Python object serialization is fragile across code changes. JSONL with Session dataclass fields is simpler, safer, aligns with D-01. |

**Installation:**
No new packages needed. All dependencies are stdlib or already in `pyproject.toml`.

## Architecture Patterns

### System Architecture Diagram

```
FSM Loop (per step)
     │
     ├── _handle_reason
     │   ├── MessageValidator.validate()
     │   ├── GuardPipeline.check()
     │   │   ├── TokenGuard       (existing, Phase 3)
     │   │   ├── CostGuard        (NEW: token cost estimation)
     │   │   └── RateLimitGuard    (NEW: call frequency per tool)
     │   ├── BudgetGuard.check()
     │   ├── LLM call (client.complete)
     │   └── CheckpointManager.save()  (NEW: after LLM call)
     │
     ├── _handle_act
     │   ├── LoopDetector.check() [UPGRADED: classification + meta prompts]
     │   ├── FailureRegistry.check()  (NEW: skip known-failed operations)
     │   ├── CircuitBreaker.check(tool_name)  (NEW: open → skip)
     │   ├── PermissionGuard.check()
     │   ├── ToolExecutor.execute() [UPGRADED: 4-layer recovery]
     │   │   ├── Layer 1: Cosmetic repair (JSON arg fix)
     │   │   ├── Layer 2: In-context retry (structured error → LLM)
     │   │   ├── Layer 3: Full retry + backoff (existing RetryConfig)
     │   │   └── Layer 4: Human escalation (EventBus → pause)
     │   └── CheckpointManager.save()  (NEW: after tool result)
     │
     └── _handle_observe
         └── BudgetGuard.check_unreachable()
```

**Data flow:** Each step begins in `_handle_reason` where guards validate + guard. The LLM call produces either a final answer (FINISH) or tool calls (ACT). In ACT state, the pipeline checks loop detection, failure registry, circuit breaker, and permission before executing. The ToolExecutor's 4-layer recovery handles tool-level errors. After each state transition, `CheckpointManager` persists the session state. All subsystems publish events to `EventBus` for observability (consumed by JSONL logger and future dashboard).

### Recommended Project Structure

```
src/loopai/
├── resilience/
│   ├── __init__.py
│   ├── checkpoint.py      # CheckpointManager (RES-01)
│   ├── circuit_breaker.py # CircuitBreaker (RES-06)
│   └── failure_registry.py # FailureRegistry (RES-03)
├── state_machine/
│   ├── fsm.py             # [MODIFIED] Wire in new components
│   ├── guards.py           # [MODIFIED] LoopDetector upgrade + CostGuard + RateLimitGuard + GuardPipeline
│   └── ...
├── tools/
│   ├── executor.py         # [MODIFIED] 4-layer recovery (RES-05)
│   └── ...
└── events/
    └── schemas.py          # [MODIFIED] Add new event types
```

### Pattern 1: Guard Pipeline — Sequential check with short-circuit

**What:** Run multiple guards in sequence. Each guard returns `(signal, ...)` tuple. If any guard returns a blocking signal, the pipeline short-circuits and reports the first blocking guard.

**When to use:** TokenGuard, CostGuard, RateLimitGuard all run before LLM call in `_handle_reason`. Each guard must independently pass for the pipeline to proceed.

**Source:** Existing `BudgetGuard.check()` / `TokenGuard.check()` pattern — all follow `check(messages) → (action, ...)` signature.

```python
class GuardPipeline:
    """Sequential guard pipeline with short-circuit on first block."""

    def __init__(self, guards: list[Guard]) -> None:
        self._guards = guards

    def check(self, messages: list[dict]) -> GuardResult:
        """Run each guard in sequence. Short-circuit on first non-ok result.

        Returns:
            GuardResult with action="ok" if all pass, or action="blocked",
            "warn", "compress" with the blocking guard's name and message.
        """
        for guard in self._guards:
            action, *rest = guard.check(messages)
            if action != "ok":
                return GuardResult(
                    action=action,
                    guard_name=guard.__class__.__name__,
                    detail=rest[0] if rest else None,
                )
        return GuardResult(action="ok", guard_name=None, detail=None)
```

### Pattern 2: Circuit Breaker — Sliding window + state machine

**What:** Per-tool state machine (closed → open → half-open → closed) driven by sliding window failure rate.

**When to use:** Wraps tool execution in `_handle_act`. Check before execution. Record success/failure after execution.

**Source:** D-05 specification. Standard circuit breaker pattern adapted for sliding window.

```python
class CircuitState(StrEnum):
    CLOSED = "closed"       # Normal operation
    OPEN = "open"           # Tool paused
    HALF_OPEN = "half_open" # Trial probe

class CircuitBreaker:
    """Per-tool circuit breaker with sliding window failure rate."""

    def __init__(self, window_size: int = 10,
                 failure_threshold: float = 0.5,
                 cooldown_seconds: float = 30.0) -> None:
        self._window: dict[str, deque[bool]] = {}  # tool_name → [success/fail]
        self._state: dict[str, CircuitState] = {}
        self._opened_at: dict[str, float] = {}  # tool_name → timestamp
        self._window_size = window_size
        self._failure_threshold = failure_threshold
        self._cooldown_seconds = cooldown_seconds

    def check(self, tool_name: str) -> tuple[bool, CircuitState]:
        """Check if tool is allowed to execute.

        Returns:
            (allowed, state). If open, tool is blocked.
        """
        state = self._state.get(tool_name, CircuitState.CLOSED)

        if state == CircuitState.OPEN:
            elapsed = time.monotonic() - self._opened_at.get(tool_name, 0)
            if elapsed >= self._cooldown_seconds:
                self._state[tool_name] = CircuitState.HALF_OPEN
                return (True, CircuitState.HALF_OPEN)  # Allow probe
            return (False, CircuitState.OPEN)

        return (True, state)  # CLOSED or HALF_OPEN

    def record(self, tool_name: str, success: bool, bus: EventBus) -> None:
        """Record a tool execution outcome and update state."""
        if tool_name not in self._window:
            self._window[tool_name] = deque(maxlen=self._window_size)
        self._window[tool_name].append(success)

        # Calculate failure rate
        window = self._window[tool_name]
        failures = sum(1 for r in window if not r)
        rate = failures / len(window) if window else 0.0

        state = self._state.get(tool_name, CircuitState.CLOSED)

        if state == CircuitState.HALF_OPEN:
            if success:
                self._state[tool_name] = CircuitState.CLOSED
                bus.publish("circuit_closed", {...})
            else:
                self._state[tool_name] = CircuitState.OPEN
                self._opened_at[tool_name] = time.monotonic()
                bus.publish("circuit_opened", {...})
        elif state == CircuitState.CLOSED and rate > self._failure_threshold:
            self._state[tool_name] = CircuitState.OPEN
            self._opened_at[tool_name] = time.monotonic()
            bus.publish("circuit_opened", {...})
```

### Pattern 3: 4-Layer Recovery — Esclation chain with independent thresholds

**What:** Each layer has its own entry condition. Failures escalate through layers in sequence. Each layer has its own `max_attempts` counter.

**When to use:** Inside `ToolExecutor._execute_with_retry`. The retry loop becomes a state machine that escalates through layers.

**Source:** D-03/D-04 specification.

```python
class RecoveryLayer(IntEnum):
    COSMETIC = 1    # Fix arg formatting, retry
    IN_CONTEXT = 2  # LLM sees error, self-corrects
    BACKOFF = 3     # Existing retry with exponential backoff
    ESCALATE = 4    # Pause, wait for human

class RecoveryConfig:
    """Per-layer thresholds (independent per D-04)."""
    cosmetic_max_attempts: int = 1
    in_context_max_attempts: int = 2
    backoff_max_attempts: int = 3
    escalate_timeout: float = 120.0  # Wait for human
```

### Pattern 4: Checkpoint — JSONL append-only, recover by replay

**What:** After each FSM step, serialize `Session` state as one JSON line. Recover by reading the last line and deserializing.

**When to use:** After every state machine transition step (both `_handle_reason` and `_handle_act`).

**Source:** D-01/D-02 specification. Pattern follows existing `JSONLLogger`.

```python
class CheckpointManager:
    """Append-only JSONL checkpoint writer with crash recovery.

    Checkpoint files live in logs/sessions/ alongside JSONL event logs,
    differentiated by .ckpt.jsonl suffix (D-02).
    """

    def __init__(self, session_id: str, log_dir: str = "logs/sessions") -> None:
        self.filepath = Path(log_dir) / f"{date_str}_{session_id}.ckpt.jsonl"

    def save(self, session: Session) -> None:
        """Serialize session state as single JSON line."""
        state = {
            "session_id": session.session_id,
            "state": session.state.value,
            "step_count": session.step_count,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            # Claude's Discretion: which message subset to include
            "messages": session.messages,
            "tool_history": session.tool_history,
        }
        # Append + flush
        self._file.write(json.dumps(state, ensure_ascii=False) + "\n")
        self._file.flush()

    @classmethod
    def recover(cls, session_id: str) -> Session | None:
        """Read last checkpoint line and reconstruct Session."""
        # ... read file, find last line, parse JSON, build Session ...
```

### Anti-Patterns to Avoid

- **Inline circuit breaker logic in FSM:** Circuit breaker state management is complex enough to warrant its own class. Inlining it in `_handle_act` would make FSM unreadable.
- **Checkpointer coupled to event logger:** Checkpoint and JSONL event log serve different purposes. Checkpoint = state recovery. JSONL = audit trail. Keep separate files as D-02 specifies.
- **Layer 4 escalation as infinite blocking:** Must have a timeout (default 120s matches `PermissionGuard.confirmation_timeout`). Agent should not hang indefinitely waiting for human input.
- **Recursive LLM calls in Layer 2:** In-context retry (Layer 2) calls the LLM again. Must guard against infinite loops — Layer 2 has its own attempt ceiling.
- **Circuit breaker as global singleton:** Per-tool circuit breaker instances (one dict with `tool_name` key). Global state would conflate different tools' failure patterns.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Circuit breaker state machine | Custom state transitions (already being built, but follow standard pattern) | Standard closed→open→half-open→closed pattern | Well-understood, proven in production systems. Deviating creates confusion. |
| Sliding window data structure | Custom ring buffer | `collections.deque(maxlen=N)` | Already used in LoopDetector. O(1) append, auto-evicts old entries. |
| Exponential backoff | Custom backoff formula | Existing `RetryConfig.compute_delay()` | Already implemented in `tools/types.py`. Reuse for Layer 3. |
| JSON arg repair | Custom heuristic for all LLM JSON bugs | Use existing JSON parsing error + `pydantic.ValidationError` details | LLM JSON errors are diverse (missing commas, trailing commas, unquoted keys). Let `json.JSONDecodeError` guide targeted repairs. |

**Key insight:** The Phase 4 subsystems are primarily *orchestration* of existing patterns, not novel algorithms. The circuit breaker follows a 50-year-old pattern. The layered recovery mirrors Kubernetes Pod lifecycle. JSONL checkpoints are standard event sourcing. Focus implementation effort on correct integration points (FSM wiring, EventBus events, threshold configuration) rather than inventing new patterns.

## Common Pitfalls

### Pitfall 1: Circuit breaker race condition on half-open probe
**What goes wrong:** Two concurrent `execute()` calls both see half-open state and both proceed as probe. Both fail, circuit opens immediately again.
**Why it happens:** Half-open state should allow exactly one probe. Without synchronization, concurrent tasks both pass the `check()`.
**How to avoid:** Use `asyncio.Lock` per tool in the circuit breaker. Transition `HALF_OPEN → OPEN` immediately when a probe starts; transition to `CLOSED` only on probe success. Alternatively, set a `_probing: set[str]` tracking tools currently in probe.
**Warning signs:** Two half-open probes observed in logs for same tool.

### Pitfall 2: Checkpoint serialization of non-serializable fields
**What goes wrong:** `Session` contains `AgentConfig` dataclass (which includes `SecretStr` for API key). Direct `json.dumps()` will fail on this field.
**Why it happens:** Session fields are designed for runtime, not serialization. `config` field has Pydantic `SecretStr` and other non-JSON-serializable objects.
**How to avoid:** `CheckpointManager.save()` should serialize only a whitelist of fields: `session_id`, `state`, `step_count`, `messages`, `tool_history`. Exclude `config` (can be reconstructed). Store `created_at` as string.
**Warning signs:** `TypeError: Object of type SecretStr is not JSON serializable` during save.

### Pitfall 3: Layer 2 recursion without escalation guard
**What goes wrong:** Layer 2 (in-context retry) re-calls the LLM with a structured error message. If the LLM keeps calling the same tool with the same args, Layer 2 loops forever.
**Why it happens:** The LLM may not understand the error from the structured feedback. Each LLM call looks like a new attempt.
**How to avoid:** Layer 2 has its own `max_attempts` counter (default 2). After exhausting Layer 2, escalate to Layer 3 even if the error type is still "repairable."
**Warning signs:** Multiple consecutive Layer 2 attempts with identical tool calls.

### Pitfall 4: Failure registry blocks legitimate retries
**What goes wrong:** A tool fails transiently. Failure registry records it. Later, when conditions change (e.g., network recovers), the tool is still blocked.
**Why it happens:** Failure registry is append-only with no expiration. Good for permanent "don't repeat" decisions, bad for transient conditions.
**How to avoid:** Two-tier registry: (1) session-level transient failure list (reset per session), (2) permanent failure registry (persistent across sessions). The checker checks session-level first, then permanent.
**Warning signs:** Tool is never retried despite changed conditions.

### Pitfall 5: Circuit breaker resets on schema regeneration
**What goes wrong:** FSM generates tool schemas fresh each step. Circuit breaker state is in-memory. If circuit breaker is recreated each step, state is lost.
**Why it happens:** `get_schemas()` is called each REASON cycle. If circuit breaker is passed as a new instance, previous failure history is gone.
**How to avoid:** CircuitBreaker instance must be a singleton for the session (stored as FSM attribute). `get_schemas(exclude_open=list_of_open_tools)` filters registered schemas.
**Warning signs:** Circuit opens but tool still appears in LLM's available tools.

## Code Examples

### Example 1: GuardPipeline orchestration in FSM._handle_reason

**Source:** Follows existing `TokenGuard.check()` pattern from Phase 3. Wires guards sequentially.

```python
# In FSM._handle_reason, after message validation:

# GuardPipeline: run all guards sequentially
if self.guard_pipeline is not None:
    pipeline_result = self.guard_pipeline.check(session.messages)

    if pipeline_result.action == "compress":
        # Existing compression logic (Phase 3)
        ...
    elif pipeline_result.action == "blocked":
        # Inject guard violation into messages
        session.add_message(
            "system",
            content=(
                f"[{pipeline_result.guard_name}] {pipeline_result.detail}. "
                "请调整策略后重试。"
            ),
        )
        session.state = AgentState.OBSERVE
        return
    # "ok" or "warn" → continue
```

### Example 2: Circuit breaker integration in FSM._handle_act

**Source:** D-05/D-06 specification. Circuit check before tool execution, record after.

```python
# In FSM._handle_act, before permission check:

# Circuit breaker check (RES-06)
if self.circuit_breaker is not None:
    allowed, state = self.circuit_breaker.check(tool_name)
    if not allowed:
        session.add_message(
            "tool",
            content=(
                f"[SYSTEM] 工具 '{tool_name}' 当前不可用 "
                f"(熔断器状态: {state.value})。请尝试其他方法。"
            ),
            tool_call_id=tool_call_id,
        )
        any_blocked = True
        continue

    # After execution, record outcome
    # (moved after result handling):
    self.circuit_breaker.record(
        tool_name, success=not result.is_error, bus=self.bus
    )
```

### Example 3: 4-layer recovery in ToolExecutor

**Source:** D-03/D-04 specification. Refactored `_execute_with_retry`.

```python
async def _execute_with_recovery(
    self, metadata: ToolMetadata, validated_args: dict,
    session_id: str = "", tool_call_id: str = "",
) -> ToolResult:
    """4-layer recovery escalation (D-03, D-04)."""

    # Layer 1: Cosmetic repair (fix JSON formatting issues)
    for attempt in range(self._recovery_cfg.cosmetic_max_attempts):
        try:
            return await self._execute_once(metadata, validated_args, ...)
        except json.JSONDecodeError as exc:
            # Attempt cosmetic fix
            repaired = self._cosmetic_repair(validated_args, exc)
            if repaired is not None:
                validated_args = repaired
                continue
            # Cannot repair → escalate to Layer 2
            break
        except (TimeoutError, ConnectionError):
            # Not a cosmetic issue → skip to Layer 3
            break
        except Exception as exc:  # TOOL_EXECUTION
            break  # Not retryable → return error

    # Layer 3: Full retry + backoff (existing RetryConfig logic)
    ... (existing code from _execute_with_retry)

    # Layer 4: Human escalation
    return await self._escalate_to_human(metadata.name, validated_args, ...)
```

### Example 4: FailureRegistry check in FSM._handle_act

**Source:** RES-03. Check before execution, record on failure.

```python
# In FSM._handle_act, after loop detection:

# Failure registry check (RES-03)
if self.failure_registry is not None:
    sig = LoopDetector._signature(tool_name, raw_args)
    if self.failure_registry.should_skip(tool_name, sig):
        session.add_message(
            "tool",
            content=(
                f"[SYSTEM] 操作 '{tool_name}({sig[:8]}...)' 之前已失败并被注册。"
                "请尝试不同的方法或参数。"
            ),
            tool_call_id=tool_call_id,
        )
        any_blocked = True
        continue

# After execution, if result.is_error and non-transient:
if self.failure_registry is not None and result.is_error:
    sig = LoopDetector._signature(tool_name, raw_args)
    self.failure_registry.record(tool_name, sig, result.error_message)
```

### Example 5: CheckpointManager save after each step

**Source:** D-01/D-02. Save in FSM run loop after state transition.

```python
# In ReActFSM.run(), after each state handler returns:

while session.state not in (AgentState.FINISH, AgentState.ERROR):
    prev_state = session.state
    if session.state == AgentState.REASON:
        await self._handle_reason(session)
    elif session.state == AgentState.ACT:
        await self._handle_act(session)
    elif session.state == AgentState.OBSERVE:
        await self._handle_observe(session)

    # Checkpoint after every state transition (RES-01)
    if self.checkpoint_manager is not None:
        await self.checkpoint_manager.save(session)
        await self.bus.publish("checkpoint_saved", {
            "event_type": "checkpoint_saved",
            "session_id": session.session_id,
            "step_count": session.step_count,
            "state": session.state.value,
        })
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| LoopDetector: binary allow/block | Upgraded LoopDetector: classify + metacognitive prompts | Phase 4 | LLM receives contextual feedback about WHY its call is looping |
| ToolExecutor._execute_with_retry: single retry loop | 4-layer recovery with independent thresholds | Phase 4 | Each failure type handled at appropriate layer |
| No tool failure tracking | FailureRegistry: permanent "never repeat" list | Phase 4 | Prevents LLM from wasting steps on known-bad operations |
| TokenGuard alone | GuardPipeline: TokenGuard + CostGuard + RateLimitGuard | Phase 4 | Multi-dimensional protection before each LLM call |
| No tool-level isolation | CircuitBreaker: per-tool failure isolation | Phase 4 | One failing tool doesn't derail the whole agent |

**Deprecated/outdated:**
- `_execute_with_retry` signature: Will be replaced by `_execute_with_recovery`. Old method becomes internal to Layer 3.
- `LoopDetector.check()` return: Currently `(bool, str)`. Upgrade returns `(bool, str, dict | None)` where dict contains classification info.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `Session` dataclass fields (`session_id`, `state`, `step_count`, `messages`, `tool_history`, `created_at`) are sufficient for crash recovery | Checkpoint | Missing fields would make recovery incomplete. User may need to confirm field whitelist. |
| A2 | Default sliding window N=10 is appropriate for circuit breaker | Circuit Breaker | Too small = false positives from statistical noise. Too large = slow to detect real failures. User may want to tune via config. |
| A3 | Layer 2 (in-context retry) should have max_attempts=2 | 4-Layer Recovery | Too few = no chance to self-correct. Too many = wasted LLM calls. User may want to adjust. |
| A4 | `time.monotonic()` is the correct clock for cooldown tracking | Circuit Breaker | `time.time()` is subject to system clock adjustments. `monotonic()` is immune but measures wall time, not CPU time. |
| A5 | FailureRegistry session-level list is reset per session | Failure Registry | For Phase 4, session-scoped is sufficient. Cross-session persistence deferred to Phase 6. |

## Open Questions

1. **How should circuit-open tools be excluded from LLM tool schema?**
   - What we know: `ToolRegistry.get_schemas()` returns all registered tools. FSM calls this in `_handle_reason`.
   - What's unclear: Should circuit breaker filter the schemas before passing to LLM, or should the tool remain visible but execution be blocked? Filtering is cleaner (LLM won't waste calls) but hides state. Blocking with visible tool is more transparent.
   - Recommendation: Filter from schema. Circuit-opened event published to bus so the dashboard can display state. LLM shouldn't waste tokens on unavailable tools.

2. **Should CostGuard use actual token counts or fixed model pricing?**
   - What we know: TokenCounter exists from Phase 3. No pricing model exists yet.
   - What's unclear: Cost per token varies by model. Without a pricing table, CostGuard can only estimate.
   - Recommendation: Start with `estimated_cost = token_count * model_cost_per_token` with a hardcoded lookup table for common models (`gpt-4o`, `gpt-4o-mini`). Add model config to `AgentConfig` in Phase 5 when cost tracking becomes a dashboard feature.

3. **What event schema fields for circuit state changes?**
   - What we know: D-06 requires `circuit_opened` / `circuit_closed` events on EventBus.
   - What's unclear: Should `circuit_opened` include the failure rate that triggered it? Should it include the window size?
   - Recommendation: Include `tool_name`, `previous_state`, `new_state`, `failure_rate` (percentage), `window_size`, `cooldown_seconds`. This gives consumers enough context to display and diagnose.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.12+ | All code | Yes | 3.12.3 | — |
| `json` (stdlib) | Checkpoint, FailureRegistry | Yes | — | — |
| `asyncio` (stdlib) | All async operations | Yes | — | — |
| `collections.deque` | Sliding window | Yes | — | — |
| `time` (stdlib) | Cooldown, rate limiting | Yes | — | — |

**Missing dependencies with no fallback:** None. All resilience components use stdlib only.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest + pytest-asyncio |
| Config file | `pyproject.toml` (`[tool.pytest.ini_options]`) |
| Quick run command | `python -m pytest tests/ -x -q --timeout=10` |
| Full suite command | `python -m pytest tests/ -v --timeout=10` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| RES-01 | CheckpointManager saves and recovers session state | unit | `pytest tests/test_checkpoint.py::TestCheckpoint -x -q` | No — Wave 0 |
| RES-01 | Checkpoint file is JSONL append-only, colocated with logs | unit | `pytest tests/test_checkpoint.py::TestCheckpoint::test_file_format -x -q` | No — Wave 0 |
| RES-02 | LoopDetector upgrade: classify loop patterns (same args, different args, same tool) | unit | `pytest tests/test_guards.py::TestLoopDetectorUpgrade -x -q` | No — extend existing |
| RES-02 | Metacognitive prompt injected on classified loop | unit | `pytest tests/test_guards.py::TestLoopDetectorUpgrade::test_meta_prompt -x -q` | No — extend existing |
| RES-03 | FailureRegistry records and blocks repeated operations | unit | `pytest tests/test_failure_registry.py::TestFailureRegistry -x -q` | No — Wave 0 |
| RES-03 | FailureRegistry JSONL persistence roundtrip | unit | `pytest tests/test_failure_registry.py::TestFailureRegistry::test_persistence -x -q` | No — Wave 0 |
| RES-04 | GuardPipeline runs TokenGuard → CostGuard → RateLimitGuard sequentially | unit | `pytest tests/test_guards.py::TestGuardPipeline -x -q` | No — extend existing |
| RES-04 | GuardPipeline short-circuits on first blocked guard | unit | `pytest tests/test_guards.py::TestGuardPipeline::test_short_circuit -x -q` | No — extend existing |
| RES-05 | 4-layer recovery: Layer 1 repairs JSON and retries | unit | `pytest tests/test_tools.py::TestRecoveryLayer -x -q` | No — extend existing |
| RES-05 | 4-layer recovery: Layer 4 escalates to human via EventBus | unit | `pytest tests/test_tools.py::TestRecoveryLayer::test_escalation -x -q` | No — extend existing |
| RES-06 | CircuitBreaker sliding window tracks failure rate correctly | unit | `pytest tests/test_circuit_breaker.py::TestCircuitBreaker -x -q` | No — Wave 0 |
| RES-06 | CircuitBreaker state transitions: closed→open→half-open→closed | unit | `pytest tests/test_circuit_breaker.py::TestCircuitBreaker::test_state_transitions -x -q` | No — Wave 0 |
| RES-06 | Circuit state changes published to EventBus | unit | `pytest tests/test_circuit_breaker.py::TestCircuitBreaker::test_events -x -q` | No — Wave 0 |
| Integration | All Phase 4 components wired into FSM | integration | `pytest tests/test_fsm.py::TestResilience -x -q` | No — extend existing |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_checkpoint.py tests/test_circuit_breaker.py tests/test_failure_registry.py -x -q`
- **Per wave merge:** `python -m pytest tests/ -x -q --timeout=10`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_checkpoint.py` — covers RES-01
- [ ] `tests/test_circuit_breaker.py` — covers RES-06
- [ ] `tests/test_failure_registry.py` — covers RES-03
- [ ] Extend `tests/test_guards.py` — covers LoopDetector upgrade (RES-02) + GuardPipeline + CostGuard + RateLimitGuard (RES-04)
- [ ] Extend `tests/test_tools.py` — covers 4-layer recovery (RES-05)
- [ ] Extend `tests/test_fsm.py` — covers integration of all new components

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V5 Input Validation | yes | Existing Pydantic validation in ToolExecutor. Layer 1 cosmetic repair is NOT a security bypass — it only fixes JSON formatting, not content. |
| V8 Data Protection | yes | Checkpoint files store message content. Must use same file permissions as JSONL logger (0o600 for files, 0o700 for directories). No secrets in checkpoint fields (`config` excluded). |

### Known Threat Patterns for Resilience Systems

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Crash recovery leaks session data | Information Disclosure | Checkpoint files stored in `logs/sessions/` with 0o600 permissions (matching JSONLLogger). |
| Circuit breaker as denial-of-service vector | Denial of Service | Circuit breaker limits failure impact but cannot be externally triggered. Sliding window only counts tool execution results, not external events. |
| In-context retry LLM cost amplification | Resource Exhaustion | Layer 2 has `max_attempts=2` ceiling. GuardPipeline includes CostGuard to prevent unbounded cost. |

## Sources

### Primary (HIGH confidence)
- [Existing codebase] — `src/loopai/` all modules verified by reading source files
- [Project documentation] — `.planning/CONTEXT.md`, `REQUIREMENTS.md`, `ROADMAP.md`, `PROJECT.md` all verified
- [Python stdlib] — `json`, `asyncio`, `collections.deque`, `time` documented behaviors from official Python 3.12 docs

### Secondary (MEDIUM confidence)
- [pybreaker README](https://github.com/danielfm/pybreaker) — circuit breaker states verified, sliding window NOT supported
- [circuitbreaker PyPI](https://pypi.org/project/circuitbreaker/) — async support verified, sliding window NOT supported

### Tertiary (LOW confidence)
- Assumptions about default threshold values (N=10, Layer 2 max=2) — unverified, marked as user discretion

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — No new external libraries needed. All stdlib verified.
- Architecture: HIGH — Patterns derived from existing codebase (Guard pattern, EventBus, FSM integration).
- Pitfalls: HIGH — Based on common distributed systems failure modes and existing codebase antipatterns.

**Research date:** 2026-05-29
**Valid until:** 2026-07-01 (stable — all dependencies are stdlib)
