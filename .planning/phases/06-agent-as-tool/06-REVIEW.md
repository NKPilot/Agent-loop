---
phase: 06-agent-as-tool
reviewed: 2026-05-30T15:00:00Z
depth: standard
files_reviewed: 13
files_reviewed_list:
  - src/loopai/agents/__init__.py
  - src/loopai/agents/types.py
  - src/loopai/agents/decorator.py
  - src/loopai/agents/registry.py
  - src/loopai/agents/tool.py
  - src/loopai/agents/disk_agents.py
  - src/loopai/tools/registry.py
  - src/loopai/main.py
  - src/loopai/events/schemas.py
  - tests/test_agents.py
  - frontend/src/lib/eventTypes.ts
  - frontend/src/components/AgentCallCard.tsx
  - frontend/src/components/StepCard.tsx
findings:
  critical: 2
  warning: 3
  info: 4
  total: 9
status: issues_found
---

# Phase 06: Code Review Report — Agent-as-Tool

**Reviewed:** 2026-05-30T15:00:00Z
**Depth:** standard
**Files Reviewed:** 13 (8 Python backend, 3 TypeScript frontend, 2 test/support)
**Status:** issues_found

## Summary

Reviewed the Phase 06 Agent-as-Tool implementation across 13 files. The architecture is well-structured, reusing existing patterns (@tool decorator mechanics, ToolRegistry, EventBus). However, two **BLOCKER** issues make key functionality non-operational:

1. **Frontend visual disconnection**: `step_num=0` is hardcoded in AgentCallStart/AgentCallEnd events, preventing the frontend from rendering sub-agent call cards in the correct timeline step.
2. **Silent dangerous tool failure**: The sub-agent's PermissionGuard is wired to an isolated EventBus (`sub_bus`) with no confirmation consumer attached, causing all DANGEROUS tool calls (including disk_rm, the disk_cleaner's only tool) to silently time out.

Additional warnings cover token usage data loss, inconsistent registry contracts, and missing parameter validation for disk agents.

## Critical Issues

### CR-01: step_num hardcoded to 0 in AgentCallStart/AgentCallEnd prevents correct frontend rendering

**File:** `src/loopai/agents/tool.py:142,197`
**Issue:** Both AgentCallStart and AgentCallEnd events publish `step_num=0` unconditionally. The AgentTool has no visibility into the main agent's current step number. On the frontend, the Timeline component groups events by `step_num` — since these events always carry `step_num=0`, they are grouped into step 0 rather than the step that actually triggered the sub-agent call. The `StepCard` integration at `frontend/src/components/StepCard.tsx:210-224` filters `step.events` for `agent_call_start` events by scanning each step's event list, but the events never appear in the correct step. End result: the AgentCallCard (sub-agent detail card) never renders alongside the tool call that invoked it.

**Fix:** The ToolExecutor needs to propagate the current step number to tool functions, or the AgentTool.execute() signature needs to accept a step context. Option A (cleaner): modify `ToolExecutor.execute()` to accept an optional `step_num` parameter (default 0 for backward compatibility), pass it through `_execute_once()` to the tool function. Option B (simpler): inject step_num into AgentTool via a stateful attribute set by ToolExecutor before calling execute().

**Preferred fix (Option A — `executor.py`):**
```python
# In ToolExecutor.execute() signature:
async def execute(self, tool_name: str, args: dict,
                  session_id: str = "", tool_call_id: str = "",
                  step_num: int = 0) -> ToolResult:
    ...

# In ToolExecutor._execute_once(), pass step_num to func_ref:
# For async tools:
coro = func(**validated_args, _step_num=step_num)  # via a convention
# OR: store on the executor and let tools read it
```

**Then in `tool.py` `_run_sub_agent`:**
```python
# AgentCallStart publish needs real step_num.
# Store it on AgentTool instance before execute() if passed via shared state.
# Or accept step_num in execute().
```

---

### CR-02: Sub-agent PermissionGuard has no consumer on isolated EventBus — dangerous tools silently fail

**File:** `src/loopai/agents/tool.py:159-161`
**Issue:** The sub-agent creates a `PermissionGuard` wired to `sub_bus` (an isolated EventBus). When a DANGEROUS tool (like `disk_rm`) is called inside the sub-agent, `PermissionGuard.check()` publishes a `confirmation_required` event to `sub_bus` and waits for a response via `asyncio.Event.wait()`. However, **no consumer is connected to `sub_bus`** — there is no CLI renderer, SSE bridge, or Web dashboard subscribed to it. The confirmation request is never surfaced to the user, and no response is ever dispatched. After `confirmation_timeout` expires, PermissionGuard returns `(False, "timeout")`, the FSM records a timeout error in the message history, and the tool call silently fails.

This makes the `disk_cleaner` sub-agent **effectively non-functional** for its primary purpose — its only tool (`disk_rm`) is DANGEROUS, so every call to it from within the sub-agent will time out. The sub-agent's system prompt misleadingly states "系统会自动弹出确认框" (a confirmation dialog will appear automatically), but no dialog ever appears.

**Fix:** At minimum, wire the sub-agent's PermissionGuard to auto-approve or skip confirmation. Options:

Option A (sub-agent design): Create the sub-agent's PermissionGuard with a bypass for automated sub-agent contexts. An `auto_approve` flag:
```python
class PermissionGuard:
    def __init__(self, bus: EventBus, confirmation_timeout: float = 120.0,
                 auto_approve: bool = False) -> None:
        self._auto_approve = auto_approve
        ...

    async def check(self, ...):
        if self._auto_approve and permission_level == PermissionLevel.DANGEROUS:
            # In sub-agent context: auto-approve since no user is present
            return (True, "auto_approved")
        ...
```

Option B (event forwarding): Subscribe to `sub_bus` and forward `confirmation_required` events to `self._bus` (the main EventBus), and forward `confirmation_response` events back:
```python
# In AgentTool._run_sub_agent():
sub_bus = EventBus()

# Forward confirmation_required from sub_bus to main_bus
async def _forward_confirmation():
    async for event in sub_bus.subscribe("confirmation_required"):
        if self._bus:
            self._bus.publish(...)
    # Similarly forward confirmation_response back
```

---

## Warnings

### WR-01: Sub-agent token_usage permanently lost

**File:** `src/loopai/agents/tool.py:252-254`
**Issue:** The `_extract_summary` method explicitly sets `token_usage = None` with a comment stating "留空由上层或前端补充" (leave empty for upper layer or frontend to supplement). However, there is no mechanism by which the token usage is recovered. The ReActFSM's StepEnd events contain token_usage data published to `sub_bus`, but:
1. The `AgentCallEnd` event published to the main bus at line 212 passes `token_usage=result.token_usage` which is always `None`.
2. No code bridges token_usage from `sub_bus` StepEnd events to the `AgentCallEnd` event.
3. The frontend `AgentCallCard` (line 192-197) conditionally displays token usage but never receives it.

Even though the mock `LLMClient` in tests returns `token_usage`, the test `test_agent_tool_creates_independent_session` (test_agents.py:211-216) never asserts `result.token_usage`, so this gap is untested.

**Fix:** Aggregate token_usage in `_run_sub_agent` by subscribing to `sub_bus` StepEnd events:
```python
# In AgentTool._run_sub_agent(), before running FSM:
sub_bus = EventBus()
token_usage_accumulated = {}

# Subscribe to sub_bus step_end events to capture token_usage
async def _capture_token_usage():
    async for event in sub_bus.subscribe("step_end"):
        if event.get("token_usage"):
            token_usage_accumulated.update(event["token_usage"])

capture_task = asyncio.create_task(_capture_token_usage())

# ... run FSM ...
# ... after FSM completes:
capture_task.cancel()
result.token_usage = token_usage_accumulated or None
```

---

### WR-02: ToolRegistry.register() silently overwrites duplicate names while register_meta() raises ValueError — inconsistent contract

**File:** `src/loopai/tools/registry.py:43-72`
**Issue:** `register()` (line 55: `self._tools[meta.name] = meta`) silently overwrites if a tool with the same name already exists. `register_meta()` (lines 70-72) raises `ValueError` on duplicate. This inconsistency means:
- Code using `register()` can accidentally overwrite tools without warning.
- Code using `register_meta()` gets an error for the same condition.
- Callers who switch between the two methods get different behavior for the same logical operation.

The `register()` method should either check for duplicates (like `register_meta()`) or both should use the same policy. The pre-Phase 6 `register()` (silent overwrite) is the legacy behavior; `register_meta()` (raise error) is the stricter Phase 6 addition.

**Fix:** Add a duplicate check to `register()`:
```python
def register(self, tool_fn: Callable) -> None:
    meta: ToolMetadata = tool_fn.__tool_meta__
    if meta.name in self._tools:
        raise ValueError(f"Tool '{meta.name}' is already registered")
    self._tools[meta.name] = meta
```

---

### WR-03: _define_agent() does not set validation_model — disk agents lack Pydantic parameter validation

**File:** `src/loopai/agents/disk_agents.py:87-96`
**Issue:** The `_define_agent()` function builds `AgentMetadata` with `param_schema` but does not set `validation_model`. Compare this with `decorator.py:77-91` where the `@agent` decorator sets both `param_schema` and `validation_model`. This means:
- `@agent`-decorated agents have Pydantic parameter validation via their `__tool_meta__.validation_model`.
- Disk agents (`disk_analyzer`, `disk_cleaner`) created via `_define_agent()` have `validation_model=None`.
- If `ToolExecutor.execute()` receives invalid arguments for a disk agent call, it falls through to `validated_args = dict(args)` (raw passthrough, executor.py line 116) instead of catching the schema mismatch.
- This is a gap between the two agent creation paths. While the `@agent(tools=[...])` path is unusable for disk agents (documented D-06), the `_define_agent()` alternative should be a functional equivalent.

**Fix:** Add `_build_validation_model` call in `_define_agent()`:
```python
def _define_agent(name, description, system_prompt, tool_registry, max_steps, func, timeout=120.0):
    param_schema = _build_param_schema(func)
    validation_model = _build_validation_model(func)  # ADD THIS
    meta = AgentMetadata(
        ...
        param_schema=param_schema,
        validation_model=validation_model,  # ADD THIS
    )
    ...
```

Note: requires importing `_build_validation_model` in `disk_agents.py`.

---

## Info

### IN-01: AgentTool.__tool_meta__ always returns SAFE permission_level

**File:** `src/loopai/agents/tool.py:86`
**Issue:** The `AgentTool.__tool_meta__` property returns `permission_level=PermissionLevel.SAFE` unconditionally. While this is correct (the sub-agent owns its own authorization), it means the main agent's `PermissionGuard` always bypasses the sub-agent — no confirmation is ever requested before entering a sub-agent, even if the sub-agent's internal toolset includes DANGEROUS tools. The sub-agent's dangerous tool authorization is opaque to the main agent. This is by design (documented D-03) but worth noting: the main agent has no visibility into whether a sub-agent might perform dangerous operations.

---

### IN-02: _merge_args_kwargs silently drops extra positional arguments in @agent wrapper

**File:** `src/loopai/agents/decorator.py:100-105`
**Issue:** When merging positional and keyword arguments, the function iterates by parameter index. If `args` contains more positional arguments than `param_names` (i.e., extra positional args beyond the function's declared parameters), they are silently dropped. This is consistent with Python's normal behavior of raising `TypeError: takes X positional arguments but Y were given` but differs because the valiation via `validation_model(**merged)` would catch any mismatch in required parameters. However, extra positional args that match parameter names by position only to be replaced by explicit kwargs later could cause confusion.

**Fix:** This is a minor robustness issue. If intentional, the docstring should document this behavior.

---

### IN-03: get_default_registry exposes mutable module-level global state

**File:** `src/loopai/agents/__init__.py:17`, `src/loopai/agents/decorator.py:130-138`
**Issue:** `get_default_registry()` returns a reference to the module-level `_default_registry` singleton. Since `AgentRegistry` is mutable (any caller can call `register()` on it), this creates a shared global state. Two callers using `get_default_registry()` and registering agents with overlapping names would get `ValueError` (from `register()`), but more subtly, they would share the same registry — registering an agent in one module makes it visible to all modules sharing the default registry. This is likely intentional for the single-agent use case but could cause surprising interactions in test isolation or future multi-module setups.

**Fix:** For test isolation, each test should create a fresh `AgentRegistry()` instance rather than using the default registry. Tests in `test_agents.py` already do this correctly. No code change needed; documentation note only.

---

### IN-04: Module-level _build_sub_registries() call at import time couples tool names and working_dir

**File:** `src/loopai/agents/disk_agents.py:101-102`
**Issue:** `_read_registry, _clean_registry = _build_sub_registries()` is executed at module import time (not at function call time). This means:
1. If `register_disk_tools` has side effects beyond registry population, they occur at import time.
2. The working_dir is always `.sandbox` (the default); it cannot be configured for these module-level registries.
3. If a tool name lookup fails (e.g., "disk_df" not found in the full registry), the import itself crashes with `AttributeError` on `None`.

The same registries are shared across all uses of `disk_analyzer` and `disk_cleaner`. If `create_agent_components()` passes `config.tool_working_dir` that differs from `.sandbox`, the disk agents still use the `.sandbox`-bound tools (as documented in D-04: "Runtime config.tool_working_dir is not propagated to sub-agents in this plan").

---

_Reviewed: 2026-05-30T15:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
