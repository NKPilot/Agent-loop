# Project Research Summary

**Project:** loopAI — ReAct AI Agent Framework with Harness Engineering
**Domain:** AI Agent framework with developer tooling and observability
**Researched:** 2026-05-27
**Confidence:** HIGH

## Executive Summary

loopAI is a learning project focused on harness engineering for ReAct AI agents. The core thesis is that agent reliability is determined more by the quality of the harness infrastructure (context management, tool abstraction, error recovery, observability) than by model selection. Research across production frameworks (OpenAI Agents SDK, LangGraph, PydanticAI, harness engineering) converges on a layered architecture where each harness layer wraps and constrains the layer below, and all layers feed events upward to observability.

The recommended approach is to build the ReAct agent loop from scratch using the raw OpenAI SDK (not LangChain or PydanticAI). This is the correct choice for a learning project because it provides direct control over every aspect of the loop. The stack is Python 3.13 + FastAPI + Pydantic for the backend, and React 19 + TypeScript + Vite 8 + Tailwind CSS 4 for the real-time observability frontend. All versions have been cross-referenced against PyPI and npm for compatibility.

The key risks to mitigate from day one are: (1) infinite agent loops from missing harness-level loop detection, (2) context window overflow from unchecked tool output accumulation, (3) shell injection from unsafe subprocess execution with `shell=True`, and (4) undifferentiated error handling that treats all failures the same. All four have clear prevention strategies documented in the pitfalls research and must be addressed in Phase 1 of the build order, not deferred to "production hardening."

## Key Findings

### Recommended Stack

The stack is lean and deliberate. Core libraries are chosen to minimize abstraction over the agent loop while providing strong typing and real-time capabilities.

**Core technologies:**
- **Python 3.13**: Latest stable with improved asyncio scheduler, experimental io_uring backend. All libraries target 3.13.
- **OpenAI SDK 2.38.0**: Direct usage (not through wrappers) preserves full control over the agent loop. Async client is first-class.
- **FastAPI 0.136.3**: Native SSE support via `EventSourceResponse` for streaming agent state to the dashboard. Automatic Pydantic validation.
- **Pydantic 2.13.4**: Rust-backed core for 5-50x faster validation. Powers tool schemas, agent state models, and structured output.
- **React 19**: React Compiler auto-memoizes components. `use()` API for async data reading. Correct choice for the dashboard.
- **TypeScript 5.7+**: Type safety catches data shape mismatches between SSE events and UI components at compile time.
- **Vite 8.0.14**: Rolldown Rust-based bundler. Dramatically faster builds. De facto standard for new React projects.
- **Tailwind CSS 4.3.0**: CSS-first configuration, no config file needed. Oxide engine delivers 5x faster builds.

**Key architectural decision:** Build agent loop from scratch using raw OpenAI SDK. Do NOT use LangChain, LangGraph, or PydanticAI. The loop pattern is a while-loop over LLM chat completions with tool calling. This is approximately 150 lines of scaffolding for the core. The abstraction tax from frameworks (hidden prompts, opinionated state management) directly conflicts with the learning goal of understanding harness design.

**Supporting libraries:** httpx (async HTTP), psutil (system monitoring), rich (CLI display), shadcn/ui (dashboard components), TanStack Query (SSE state), Zustand (UI state), recharts (disk usage charts), lucide-react (icons).

**What NOT to use:** LangChain/LangGraph (contradicts learning goal), CrewAI (multi-agent out of scope), Django/Flask (no async SSE support), Redux (excessive boilerplate), SQLAlchemy (overkill for JSONL logging), Docker initial (adds complexity before core logic is solid), `shell=True` (command injection vector).

See detailed research at `.planning/research/STACK.md`.

### Expected Features

**Must have (table stakes -- Phase 1-2):**
- ReAct Agent Loop Core with state machine (REASON-ACT-OBSERVE-FINISH-ERROR)
- Tool Registration API via `@tool` decorator with JSON schema inference
- Tool Execution Pipeline (validate -> execute -> normalize -> return)
- Bash/Shell Tool via safe subprocess (no `shell=True`, timeout, output capture)
- Bash Danger Confirmation (pause before rm, dd, mkfs)
- Error Taxonomy with 4+ categories (Transient, ToolExecution, GuardViolation, Fatal)
- Basic Retry with exponential backoff + jitter for transient errors
- Streaming Agent Loop output via async generator/SSE
- Event Bus / Hook System with structured events (designed upfront, not retrofitted)
- Context Window Management (token tracking, compaction at 75% threshold)
- OpenAI-Compatible API only (configurable base URL, API key, model)

**Should have (differentiators -- Phase 3-5):**
- Real-Time Observability Web Dashboard (loopAI's flagship differentiator -- no open-source agent framework ships this out of the box)
- Structured Tool Abstraction Pipeline (discovery -> authorization -> execution -> result handling)
- Execution Boundaries (PathScope sandbox, command allow/deny lists)
- Command Allow/Deny Lists for BashTool
- Layered Self-Healing Recovery (cosmetic -> in-context -> full retry -> escalate)
- Guard Stage Pipeline (token budget, cost, rate limit, content guards)
- Session Replay with step-forward/backward controls
- Human-in-the-Loop Approval Gates (generic pause/resume)
- Typed State with reducers (beyond ad-hoc message list)
- Checkpointing (state serialization at key points)
- Token-Cost Tracking in Dashboard

**Defer (v2+):**
- Tool Speculative Execution (high risk, experimental)
- Causal Provenance / Ablation analysis (requires full session replay)
- Fuzz Testing for custom tools
- Multi-Agent via tool composition
- Long-Term Memory / Vector DB
- Additional provider adapters (Anthropic, Gemini, local)

**Anti-features (deliberately NOT building):**
- Full multi-agent orchestration (dilutes harness focus)
- OpenAI-compatibility proxy for 50+ providers (maintenance burden)
- Autonomous tool installation (security nightmare)
- Visual agent builder drag-and-drop (not valuable for developer audience)
- Automatic task decomposition (unpredictable sub-task structures)

See detailed research at `.planning/research/FEATURES.md`.

### Architecture Approach

The architecture follows a **layered harness** pattern with six layers: Agent Loop (core), Tool Abstraction Layer, Context Management, Error Recovery/Resilience, Observability, and (future) Memory. Each layer wraps the one below, adding constraints and capabilities without modifying the lower layer. All layers feed structured events upward through a central EventBus for observability.

**Major components:**
1. **Agent Loop** (agent/) -- State machine managing the ReAct cycle (REASON-ACT-OBSERVE-FINISH-ERROR). Controls iteration budget, delegates to Provider Adapter. Uses an explicit `AgentState` enum with `StepContext` dataclass rather than a raw while-loop.
2. **Tool Registry + Sandbox** (tools/) -- Central registry mapping tool names to `ToolDef` (callable + schema + metadata). Sandbox executor handles timeout, size limits, exception isolation. Permission middleware enforces tier-based approval (safe/moderate/dangerous with HITL gates).
3. **Context Manager** (context/) -- Token counting, compaction at 75% threshold, overflow file store. Append-only message store with prefix-stable system prompt for KV-cache reuse.
4. **Checkpoint + Resilience** (resilience/) -- State serialization, infinite loop detection, failure registry, guardrails, retry chain.
5. **Observability** (observability/) -- EventBus receives structured events from all layers, feeds JSONL logger and SSE/WebSocket stream. React frontend consumes SSE events for real-time timeline/tool call cards/approval gates.

**Key architectural patterns:**
- **Layered Harness (Control Plane Separation):** Each layer constrains the layer below without modification. Agent loop does not know about permissions; permission middleware does not know about context management.
- **State Machine Agent Loop:** Explicit state machine (not raw while-loop) giving precise control flow and trivial observability via state transition emission.
- **Append-Only Message Store + Prefix-Stable Prompt:** Nothing is mutated. Compaction produces new summary messages appended at the end. Enables KV-cache reuse (>80% hit rate) and clean audit trails.
- **Error Re-Injection:** Tool failures return structured error as tool result (not exception). LLM sees error in context and can self-correct.
- **Events flow outward only:** Components emit events but never consume from other layers. EventBus is a unidirectional dispatch point.

**Data flow:** User Input -> REASON (context manager -> provider adapter -> LLM response) -> ACT (permission check -> sandbox execute -> result injection) -> OBSERVE (budget check -> loop detection -> checkpoint) -> loop to REASON or FINISH.

See detailed research at `.planning/research/ARCHITECTURE.md`.

### Critical Pitfalls

1. **Infinite Agent Loop (Repeated Tool Calls):** The agent calls the same tool repeatedly without making progress. Prevention requires harness-level loop detection (track last N tool call hashes), metacognitive prompts ("you have tried this 3 times"), tool diversity limits, and a Verifier component independent of agent self-assessment. Must be built in Phase 1, not deferred.

2. **Context Window Overflow Without Graceful Degradation:** Tool outputs accumulate unchecked. LLM reasoning quality collapses silently as context grows. At approximately 32K tokens (for a 128K window), accuracy drops below 50%. Prevention requires a pre-LLM-call compaction pipeline: truncate per-tool outputs (2000 token max), remove stale history, summarize old results. Target 75% of context window as compaction threshold, not 100%.

3. **Shell Injection via Bash Tool:** Using `subprocess.run(command, shell=True)` with LLM-generated strings allows full system compromise via shell metacharacters. Prevention: NEVER use `shell=True`. Use `subprocess.run([cmd, arg1, arg2], shell=False)`, implement full command parsing (not first-token-only), block shell metacharacters, implement capability-based classification, unset sensitive env vars before subprocess.

4. **Undifferentiated Error Handling:** All tool failures treated the same (return error string to LLM). 8% of calls fail from transient errors (retriable), 30% from parameter errors (not retriable), 35% from tool selection errors. Without classification, the agent retries permanent errors indefinitely and misses transient retries. Prevention: implement error classification in the harness with distinct recovery strategies per category. Never pass raw tracebacks to the LLM.

5. **Missing Termination Conditions:** Agent runs until hard budget exhaustion. Users receive truncated responses or timeouts. Prevention: implement three-tier termination (goal met via independent Verifier, goal unachievable after N failures, budget exhaustion warning at 80%), and always return partial results with useful summary instead of silent truncation.

See detailed research at `.planning/research/PITFALLS.md`.

## Implications for Roadmap

Based on combined research across all four files, the recommended build order follows the architecture's dependency chain. Each phase produces a usable increment while minimizing rework.

### Phase 1: Core Agent Loop
**Rationale:** Everything depends on the loop. No agent, no tool calls, no context, no observability worth showing.
**Delivers:** Working ReAct state machine with OpenAI-compatible provider adapter, basic loop detection, JSONL logging from turn 1, step budget + termination conditions, message structure alternation validation.
**Addresses features:** ReAct Agent Loop Core (P1), Streaming Agent Loop (P1), OpenAI-Compatible API (P1), Basic Context Management (P1), Tool Registration API skeleton (P1).
**Avoids pitfalls:** Infinite Loop (basic detection), Missing Termination (step budget + Verifier), Tool Selection Ambiguity (enforce <7 tools), Message Structure Corruption (alternation validator), Undigestible Tool Outputs (structured contract from day one).
**Stack used:** Python 3.13, OpenAI SDK 2.38, Pydantic 2.13, FastAPI 0.136, rich (CLI output).
**Research flag:** Standard patterns. Well-documented ReAct loop, OpenAI SDK docs. No deeper research needed.

### Phase 2: Tool Abstraction Layer
**Rationale:** Tool registry, sandbox, and the first real tool (Bash) are needed before context management makes sense, and before the dashboard can show anything useful.
**Delivers:** Tool registry with metadata (name, schema, permission tier), sandbox executor with timeout and exception isolation, BashTool with safe subprocess (no `shell=True`), danger confirmation mechanism, error taxonomy (min 4 categories), basic retry with exponential backoff, structured output contracts (`{status, summary, data}` pattern), call registry for idempotency tracking.
**Addresses features:** Tool Registration API (P1), Tool Execution Pipeline (P1), Bash/Shell Tool (P1), Bash Danger Confirmation (P1), Error Taxonomy (P1), Basic Retry (P1).
**Avoids pitfalls:** Bash Injection (no `shell=True`, full command parsing, sandbox), Undifferentiated Errors (error classification), Non-Idempotent Tools (call registry).
**Stack used:** psutil 7.2 (disk diagnostics), subprocess + shlex (stdlib), Python 3.13 asyncio.
**Research flag:** Tool design (structured output contracts, PathScope patterns) may need targeted research during implementation. The harness-engineering toolbox (dr-gareth-roberts) is MEDIUM confidence.

### Phase 3: Context Management
**Rationale:** Compaction thresholds and overflow patterns depend on knowing what real tool outputs look like. Building context management before Phase 2 would design compaction in a vacuum with wrong thresholds.
**Delivers:** Token counting via tiktoken, compaction pipeline (truncate tool outputs, remove stale history, summarize old results), 75% threshold compaction, append-only message store hardening, overflow file store.
**Addresses features:** Context Window Management (P1), Token/Cost Tracking foundation.
**Avoids pitfalls:** Context Window Overflow (compaction pipeline at 75% threshold), Silent Context Loss (monitoring + preemptive detection).
**Stack used:** tiktoken (token counting), Python stdlib for file-based overflow.
**Research flag:** Compaction strategy selection (sliding window vs summarization) may need testing with real agent sessions. The Microsoft Agent Framework composable compaction strategies are worth referencing.

### Phase 4: Error Recovery and Resilience
**Rationale:** Checkpointing needs the well-defined context state from Phase 3 to serialize. Loop detection needs the message history that context management provides. Most important observability events (error states, recovery) require error handling to exist.
**Delivers:** Checkpoint manager (state serialization + crash recovery), loop detector hardening (classification-based intervention with metacognitive prompts), failure registry (persistent "do not repeat" list), guard stage pipeline (token budget, cost, rate limit guards), circuit breaker for failing tools, guardrails (input/output scanning).
**Addresses features:** Layered Self-Healing Recovery (P2), Guard Stage Pipeline (P2), Execution Boundaries (P2), Command Allow/Deny Lists (P2).
**Avoids pitfalls:** State Loss Across Recovery (failure registry), Undifferentiated Errors (full Recovery Ladder), Non-Idempotent Tools (hardened call registry).
**Stack used:** JSONL for checkpoint storage, asyncio for circuit breaker timers.
**Research flag:** Layered recovery strategies (cosmetic -> in-context -> full retry -> escalate) are documented but not widely production-validated. May need `/gsd-research-phase` during planning for recovery ladder implementation patterns.

### Phase 5: Observability and Web Dashboard
**Rationale:** The event bus needs events from all prior phases (state transitions, tool calls, context compaction, error recovery). Building it earlier would miss the most interesting events. Basic JSONL logging has been running since Phase 1, so there is already historical data.
**Delivers:** EventBus (asyncio.Queue with structured typed events), SSE streaming endpoint, React web frontend with agent timeline, tool call cards with status badges, state visualization, token/cost tracking in UI, session history browsing.
**Addresses features:** Event Bus / Hook System (P1), Real-Time Web Dashboard (P1), Token-Cost Tracking (P2).
**Avoids pitfalls:** Bolted-On Observability (event bus designed upfront, just built now). UX pitfalls: no thinking trace (show thought process alongside tool calls), no progress indication (step counter), final answer buries the lead (always provide summary).
**Stack used:** React 19, TypeScript 5.7+, Vite 8, Tailwind CSS 4, shadcn/ui, TanStack Query 5, Zustand 5, recharts, lucide-react, FastAPI SSE.
**Research flag:** COMPLEX INTEGRATION. SSE in FastAPI + React EventSource consumption has established patterns but live agent state streaming with approval gate responses is a custom integration. This phase likely needs `/gsd-research-phase` during planning, specifically for:
- SSE connection management and reconnection strategy
- Real-time state synchronization between backend and frontend
- Approval gate UI/API design
- Agent timeline component architecture

### Phase 6: Advanced Harness and Replay (v1.x)
**Rationale:** Session replay depends on checkpointing (Phase 4). Typed state is a refactoring of the message store (Phase 3). HITL depends on the approval mechanism and the dashboard (Phase 5). These features build on a stable foundation.
**Delivers:** Session replay in dashboard with step-forward/backward, human-in-the-loop generic pause/resume, typed state with reducers, checkpointing as first-class feature (was ad-hoc in Phase 4).
**Addresses features:** Session Replay (P2), Human-in-the-Loop (P2), Typed State (P2), Checkpointing (P2).
**Avoids pitfalls:** State Loss Across Recovery (fully addressed), Missing Termination (Verifier component hardened).
**Stack used:** Same as Phase 5 plus JSONL replay parser.
**Research flag:** Session replay architecture (deterministic replay from JSONL logs vs. snapshot-based replay) needs targeted research during planning. The harness-engineering `ReplayRunner` pattern is worth exploring.

### Phase Ordering Rationale

- **Phase 1 before everything**: The agent loop is the entry point. No loop, no agent, no tools, no observable events.
- **Phase 2 before Phase 3**: Compaction thresholds need real tool output patterns. Context management designed in a vacuum produces wrong thresholds.
- **Phase 3 before Phase 4**: Checkpointing needs a well-defined context state to serialize. Loop detection needs message history.
- **Phase 4 before Phase 5**: The most important things to observe are error states and recovery events. Building observability before error handling would miss the most interesting events.
- **Phase 5 before Phase 6**: Session replay and HITL depend on the dashboard infrastructure. Typed state is a refactoring of existing structures.

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 5 (Observability / Dashboard):** COMPLEX INTEGRATION. SSE connection management, real-time state sync, approval gate API, agent timeline component architecture. Multiple decisions with no single "right" pattern.
- **Phase 4 (Error Recovery):** Layered recovery strategies are documented but not widely production-validated. Recovery ladder implementation patterns need research.
- **Phase 6 (Advanced Features):** Session replay architecture (deterministic vs. snapshot) needs research. The harness-engineering `ReplayRunner` is the best reference but MEDIUM confidence.

Phases with standard patterns (likely skip research-phase):
- **Phase 1 (Core Loop):** Well-documented ReAct pattern with OpenAI SDK. Standard state machine implementation.
- **Phase 2 (Tool Harness):** Tool decorator pattern is universal. Safe subprocess execution is well-documented.
- **Phase 3 (Context Management):** Token counting and compaction are standard patterns across frameworks.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All versions verified against PyPI and npm. Openai, FastAPI, Pydantic, React, Vite, Tailwind all verified at exact versions. |
| Features | HIGH | Multiple primary sources (LangChain, OpenAI Agents SDK, PydanticAI, SmolAgents, harness-engineering). Feature prioritization cross-referenced with competitor analysis. Anti-features validated against project goals. |
| Architecture | HIGH | Confirmed across multiple production implementations (OpenAI Agents SDK 7-layer architecture, LangGraph state-graph model, Microsoft Agent Framework compaction, dataact minimal production harness). |
| Pitfalls | HIGH | Synthesized from production post-mortems (LlamaIndex, LangGraph RFCs, Azure DevOps), framework RFCs, and real-world incident reports. Clear prevention strategies for each. |

**Overall confidence:** HIGH

### Gaps to Address

- **Dashboard component integration:** SSE in FastAPI + React EventSource consumption needs practical validation during Phase 5. The specific patterns for real-time agent state streaming with bidirectional approval gates are not deeply tested in existing literature.
- **Layered recovery effectiveness:** The documented 4-layer recovery strategy (cosmetic -> in-context -> full retry -> escalate) comes from academic/secondary sources. Its real-world effectiveness needs validation through testing during Phase 4.
- **Compaction strategy tuning:** The 75% threshold and specific compaction strategies need testing with real agent sessions to validate. The Microsoft Agent Framework composable strategies are a good reference but need practical adaptation.
- **Disk cleanup scenario tool set:** The specific set of tools, commands, and safety boundaries needed for the disk space diagnosis and cleanup scenario needs refinement during implementation. The current research identifies general patterns but not the exact tool composition.
- **UI/UX patterns for agent trace visualization:** The dashboard timeline/graph/compact views described in the architecture are high-level concepts. Specific component design (how to show agent reasoning visually, how to handle long traces, how to show tool call relationships) needs design work during Phase 5.
- **Performance at scale:** The research focuses on correctness patterns, not performance. For a learning project this is acceptable, but any intention to scale beyond single-user will need profiling and optimization.

## Sources

### Primary (HIGH confidence)
- PyPI: openai 2.38.0, fastapi 0.136.3, pydantic 2.13.4, psutil 7.2.2, rich 15.0.0
- npm: vite 8.0.14, react 19.2.6, @tanstack/react-query 5.100.14, tailwindcss 4.3.0
- OpenAI Python SDK documentation -- async client, streaming, tool calling
- FastAPI SSE documentation -- EventSourceResponse support
- OpenAI Agents SDK v0.14+ -- Harness/Compute separation, 7-layer architecture
- LangGraph architecture -- State-graph model, checkpointing, streaming
- Python 3.13 release notes -- asyncio improvements verified
- Tailwind CSS v4.3 release -- scrollbar utilities, container queries
- shadcn/ui CLI v4 changelog -- Tailwind v4 support verified
- Pydantic AI documentation -- type-safe agents, event streaming, tool abstraction
- Atlan "How to Build an AI Agent Harness 2026" -- 10-step harness build process
- SmolAgents GitHub -- CodeAgent, tool decorator, multi-LLM support
- Microsoft Agent Framework (March 2026) -- composable compaction strategies
- arXiv 2509.25370: Agent Error Taxonomy -- 5-domain failure classification

### Secondary (MEDIUM confidence)
- harness-engineering Python toolkit (dr-gareth-roberts) -- Tool abstraction, PathScope, ReplayRunner, speculative execution
- MiniHarness Guide -- 4-stage tool pipeline, error-first design
- pyarnes Template -- Error taxonomy, lifecycle FSM, guardrails
- geny-executor -- 16-stage pipeline, dual abstraction, guard stages
- AgentField HarnessRunner -- 4-layer schema recovery, retry with backoff
- Agent-Fox issue #178 -- Shell metacharacter allowlist bypass
- Safer project (crufter/safer) -- Capability-based command classification
- AgentDiagnose Toolkit (EMNLP 2025) -- t-SNE action plots, navigation graphs
- App.build: Six Principles for Production AI Agents -- tool minimalism
- Various production post-mortems (LlamaIndex, Azure-dev, Inngest, Zencoder)

### Tertiary (LOW confidence)
- AgentField issue discussion -- 4-layer schema recovery (not yet released)
- Honeycomb Agent Timeline -- press release, not hands-on evaluation
- Specific UI/UX patterns for agent trace visualization -- academic papers, no production validation

---

*Research completed: 2026-05-27*
*Ready for roadmap: yes*
