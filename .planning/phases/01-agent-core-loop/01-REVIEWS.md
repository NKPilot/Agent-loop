---
phase: 1
reviewers: [claude]  # codex (401 Unauthorized), cursor (Authentication required) — neither configured
reviewed_at: 2026-05-27T20:15:00Z
plans_reviewed:
  - 01-01-PLAN.md (EventBus Infrastructure)
  - 01-02-PLAN.md (Guards & Configuration)
  - 01-03-PLAN.md (LLM Integration)
  - 01-04-PLAN.md (Event Consumers)
  - 01-05-PLAN.md (State Machine & Orchestration)
---

# Cross-AI Plan Review — Phase 1

## External CLI Status

| CLI | Status | Detail |
|-----|--------|--------|
| gemini | missing | Not installed |
| codex | failed | 401 Unauthorized — API key not configured |
| cursor | failed | Authentication required — `cursor agent login` not run |
| opencode | missing | Not installed |
| qwen | missing | Not installed |
| coderabbit | missing | Not installed |
| claude | skipped | Running inside Claude Code — skipped for independence |

Only 1 of 7 external CLIs was available (codex), and it lacked valid credentials. To enable true cross-AI review, configure at least one external CLI:

```bash
# Codex
codex login  # or set OPENAI_API_KEY

# Cursor
cursor agent login  # or set CURSOR_API_KEY

# Gemini
npm install -g @google/gemini-cli

# OpenCode
npm install -g opencode
```

---

## Claude Review

> Note: This review comes from the same Claude instance orchestrating the review workflow. For adversarial review, configure at least one external CLI.

### Overall Phase Assessment

**Summary**: The Phase 1 plan set is thorough and well-structured. Five plans are organized into three waves with clear dependency chains. Each plan has explicit TDD test sequences, threat models, and acceptance criteria. The architecture follows the locked decisions from CONTEXT.md faithfully. The overall risk is LOW — the plans are detailed enough that an executor can implement them without ambiguity, and the 70 total planned tests provide solid coverage of all 7 requirements.

**Strengths**:
- Wave-based parallelization is correctly structured: Wave 1 (01-01, 01-02) are independent and can run concurrently, Wave 2 (01-03, 01-04) depend only on 01-01, and Wave 3 (01-05) is the integration capstone
- TDD is mandated on the riskiest components (LoopDetector/MessageValidator, BudgetGuard, LLMClient, ReActFSM) — exactly where it adds the most value
- Threat models are included in every plan with STRIDE classification, which is unusual and valuable for a Phase 1 project
- The research-backed decision to use `client.beta.chat.completions.stream()` over `create(stream=True)` is well-justified and avoids the fragmented-argument pitfall
- Phase 1 no-op tool handling (synthetic "[SYSTEM] No tools available" result) is a pragmatic choice that exercises the full ReAct cycle without Phase 2 dependencies
- 70 total tests is appropriate for this scope — enough to catch regressions without being a burden

### Plan-by-Plan Analysis

#### 01-01: EventBus Infrastructure

**Strengths**:
- Event schemas with discriminated union is exactly right — it enables type-safe deserialization from JSONL logs later
- Bounded queues (maxsize=256) with QueueFull→warning+drop is mature backpressure handling for a v1
- Replay mechanism built from day one — avoids the pitfall of subscribers missing early events
- JSON-serializability validation at publish time catches bugs early

**Concerns**:
- MEDIUM: The plan says `publish(event_type: str, event_data: dict)` but the RESEARCH.md code example shows `publish(topic: str, event: dict)`. The distinction between "event_type as first arg" vs "topic" is ambiguous — the plan needs to clarify whether publish takes a topic string for routing or derives it from the event dict's event_type field
- MEDIUM: `test_wildcard_subscription` says "verify wildcard subscriber receives it AND topic subscriber does not get it" — this is contradictory. A wildcard subscriber should receive everything, AND a topic-specific subscriber should also receive topic-specific events. The test description may have a logic error
- LOW: The plan requires the `Event` discriminated union but doesn't specify how publish() handles the union — does publish() accept raw dicts or must callers construct pydantic model instances first? The task says `event_data: dict` but schemas define models
- LOW: `test_bounded_queue_backpressure` sets maxsize=2 manually but EventBus hardcodes 256 in subscribe() — no clear way to override for testing

**Suggestions**:
- Clarify `publish()` signature: either accept pydantic Event models (validates at boundary) or accept dicts and validate event_type key + JSON-serializability
- Fix the wildcard test logic: wildcard AND topic subscribers should BOTH receive the event
- Add a `subscribe(topic, maxsize=256)` parameter to allow test overrides without production impact

#### 01-02: Guards & Configuration

**Strengths**:
- Pure logic, zero dependencies — correct isolation for unit testing
- Three-tier escalation in LoopDetector (warn→block→force_exit) is proportionally gated
- SHA256 deterministic hashing with `json.dumps(sort_keys=True)` is the right approach for cross-session comparison
- MessageValidator strict mode (reject, don't fix) aligns with the research recommendation
- BudgetGuard never mutates input messages — critical for correctness
- add_cli_args() uses argparse.SUPPRESS as default — elegant way to distinguish "not provided" from "explicitly set"

**Concerns**:
- MEDIUM: LoopDetector._signature uses `hexdigest[:16]` (64 bits). At 15 steps max per session, collision risk is negligible. But the RESEARCH.md code shows `[:16]` on the hex string (16 hex chars = 64 bits) which is fine but worth noting as a design choice, not a bug
- LOW: BudgetGuard.check_unreachable() tracks "3 consecutive failures" but it's unclear what counts as a "failure" — tool execution error? guard block? LLM error? The plan should enumerate failure types
- LOW: MessageValidator.validate() is static but takes no config — if validation rules change per API provider (OpenAI vs Anthropic format differences), the static approach won't extend well
- LOW: The test case "multiple-tool-calls-all-matched" and "multiple-tool-calls-one-orphan-mentioned-in-error" are good but don't cover the case where tool_call_ids are interleaved (tool_1, tool_2, result_2, result_1 — is this valid?)

**Suggestions**:
- Document what "consecutive failure" means for check_unreachable() — maintain a counter that increments on tool errors + guard blocks, resets on successful tool execution
- Consider making MessageValidator instantiable with a provider-specific validator class later, but static is fine for Phase 1
- Add a test case for interleaved tool results to define the expected behavior

#### 01-03: LLM Integration

**Strengths**:
- Correctly uses `client.beta.chat.completions.stream()` with async context manager
- `tool_started_indices: set[int]` to avoid duplicate ToolCallStart events — handles the streaming edge case where argument deltas for the same tool call arrive across multiple events
- Falls back to `json.loads(event.arguments)` when `parsed_arguments` is None — robust against API variations
- Session.add_message() formats all 4 OpenAI roles — avoids ad-hoc dict construction scattered across the codebase
- Error event published before re-raise — preserves observability even on failure

**Concerns**:
- MEDIUM: All 7 LLMClient tests use AsyncMock. There are zero integration tests that hit a real API. The plan acknowledges this implicitly (the human verification checkpoint in Plan 05 is the first real-LLM test), but a single mocked integration point is the highest-risk area. If the beta stream API behavior differs from mocks, this will only be caught at the very end
- LOW: Session uses `dataclass` but RESEARCH.md shows `@dataclass`. The plan should specify `@dataclass` (which is mutable) — a frozen/pydantic alternative might be better for state integrity, but dataclass is simpler
- LOW: The plan says `add_message(role, content, tool_calls=None, tool_call_id=None, name=None)` but `name` is only valid for `role="tool"` in OpenAI format — the method should validate this
- LOW: `record_tool_call(tool_name, signature)` accepts a pre-computed signature but it's unclear who computes the signature (LoopDetector? FSM?) — this is a cross-plan integration point that needs alignment

**Suggestions**:
- Add one integration test that calls a real API (can be skipped in CI via env var check) before the human verification checkpoint
- Validate role-specific constraints in add_message() — e.g., `name` only valid for tool role
- Clarify whether Session.record_tool_call() computes the signature internally or receives it from the caller

#### 01-04: Event Consumers

**Strengths**:
- 0o600 file permissions on JSONL log — correct security stance for files containing agent activity
- Flush after every write + fsync on stop — the right tradeoff for crash resilience
- CLI Renderer uses `transient=True` on Rich Live — prevents scrollback pollution and handles terminal resize correctly
- Atomic full-rebuild updates (per RESEARCH.md Pitfall 5) — avoids interleaved step display
- Both consumers are independent asyncio tasks — clean separation of concerns

**Concerns**:
- MEDIUM: JSONLLogger writes `logs/sessions/YYYY-MM-DD_{session_id}.jsonl` with date from __init__, not from the event's timestamp. If a session spans midnight UTC, the filename is stale. Minor but worth noting
- LOW: CLI Renderer tests skip the Live context manager entirely — they only test `_handle_event()` state transitions. The actual rendering (Layout, Panel, Markdown construction) is untested. This is acknowledged but means the visual output is only verified manually
- LOW: `test_step_content_accumulation` tests accumulation but doesn't test the edge case where multiple LLMToken events arrive for the same content (duplicate deltas) — unlikely with the SDK but worth a defensive check
- LOW: 0o700 on logs/sessions/ directory is mentioned in the threat model (T-04-01) but the plan only specifies `mkdir(parents=True, exist_ok=True)` — should explicitly `os.chmod(log_dir, 0o700)`

**Suggestions**:
- Set directory permissions explicitly: `log_dir.mkdir(mode=0o700, parents=True, exist_ok=True)`
- Add a test that verifies the Rich renderable structure (at minimum, that build_renderable() returns a Layout with 3 children)
- Consider making JSONL date derive from the first event's timestamp rather than wall clock, or document the midnight-edge-case as accepted behavior

#### 01-05: State Machine & Orchestration

**Strengths**:
- Phase 1 no-op tool strategy (synthetic tool_result) is the right call — exercises the full FSM cycle without real tools
- SessionEnd always published before run() returns — critical for JSONL completeness
- Graceful shutdown sequence is correct: sentinel → drain (5s timeout) → logger.stop()
- Human verification checklist is concrete and testable (6 specific scenarios)
- Guard integration points are clearly specified (pre-REASON, pre-ACT, in OBSERVE)

**Concerns**:
- MEDIUM: The plan says `any exception -> ERROR (terminal for Phase 1)` but BudgetGuard.check() can return `action="final"` which should trigger FINISH, not ERROR. The distinction between "forced termination" (FINISH) and "unhandled exception" (ERROR) needs to be explicit in the FSM code
- MEDIUM: `asyncio.wait_for(timeout=5.0)` on consumer drain could lose the last events if the JSONL logger is slow (disk I/O). If fsync takes >5s, events are dropped. The timeout is a safety valve but 5s may be too short for slow disks
- LOW: The FSM `run()` return type is `Session` — but after ERROR, what fields are valid? The plan should specify which Session fields are meaningful in the ERROR terminal state
- LOW: `consecutive_failures` tracking is mentioned in the REFACTOR stage but not defined in the task — where is the counter stored? (Session? FSM instance?) The BudgetGuard.check_unreachable() needs this counter
- LOW: The plan says `main_cli()` uses `argparse` with prompt as positional OR `--prompt`. argparse positional + optional for the same value requires careful setup (nargs='?') to avoid ambiguity

**Suggestions**:
- Add explicit FINISH-vs-ERROR transition documentation: "final" action → one more REASON → FINISH with exit_reason="budget_exhausted"; exception during LLM/tool → ERROR with exit_reason=exception message
- Increase drain timeout to 10s or make it configurable
- Store consecutive_failures on the FSM instance (not Session — it's runtime state, not session data)
- Use `add_mutually_exclusive_group()` is not needed; just use `nargs='?'` on the positional prompt argument

---

## Consensus Summary

### Agreed Strengths (from plan analysis)

- Wave-based dependency structure with parallel Wave 1 execution is efficient
- TDD applied to high-risk components (guards, FSM) where it adds the most value
- Phase 1 no-op tool strategy correctly exercises the full ReAct cycle
- 70 planned tests provide solid coverage of all 7 CORE requirements
- Threat models in every plan demonstrate security-conscious design
- Using `client.beta.chat.completions.stream()` avoids the fragmented-tool-arguments pitfall

### Agreed Concerns (issues found in plan inspection)

1. **MEDIUM**: Plan 01-01 `publish()` signature ambiguity — does it take event_type string or derive from event dict? This affects all downstream plans
2. **MEDIUM**: Plan 01-05 FSM FINISH vs ERROR path ambiguity — "final" action should map to FINISH, not ERROR
3. **MEDIUM**: Plan 01-05 consumer drain timeout of 5s may lose last JSONL events on slow disks
4. **MEDIUM**: All LLMClient tests are mocked — first real API call happens at human verification checkpoint (Plan 01-05 Task 3)

### Divergent Views

- **Local model review tradeoff**: The plans assume cloud API (OpenAI). If the user wants to use local models (Ollama/LM Studio), the beta streaming API may not be available — but this is a v2 concern per ROADMAP.md

---

## Action Items

To incorporate this feedback, run:

```
/gsd-plan-phase 1 --reviews
```

This will regenerate affected plans with the review feedback incorporated. Priority items to address:

1. Clarify EventBus.publish() signature (affects plans 01-01, 01-03, 01-05)
2. Add explicit FSM FINISH-vs-ERROR documentation (plan 01-05)
3. Increase drain timeout or make configurable (plan 01-05)
4. Consider an optional integration test before the human checkpoint (plan 01-03)
