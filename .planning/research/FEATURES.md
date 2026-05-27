# Feature Research: ReAct AI Agent with Harness Engineering

**Domain:** ReAct agent framework (developer-oriented, harness-focused)
**Researched:** 2026-05-27
**Confidence:** HIGH (primary sources: LangChain docs, OpenAI Agents SDK, SmolAgents, PydanticAI, LangGraph changelog, harness-engineering toolbox)

## Feature Landscape

### Table Stakes (Users Expect These)

Features that the ecosystem treats as non-negotiable. A missing table-stakes feature makes a framework feel incomplete or unusable for real agent work.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| **ReAct Agent Loop** | Core identity -- LLM reasons, acts via tools, observes results, loops until answer. Without this it is not an agent framework. | MEDIUM | Every framework has one (LangChain `AgentExecutor`, SmolAgents `CodeAgent`, OpenAI `Runner.run_sync()`). loopAI must implement a correct ReAct cycle with tool-call parsing and result injection. |
| **Tool Registration via Decorator/Schema** | Users expect to turn any Python function into an agent tool with minimal boilerplate. | LOW | SmolAgents `@tool`, PydanticAI `@agent.tool`, OpenAI `@function_tool`, LangChain `@tool`. Standard pattern: docstring -> LLM description, type hints -> JSON schema. |
| **Tool Result Injection Into Context** | After tool call, the LLM must see the result in the conversation. Without this the loop breaks. | LOW | Standard ReAct pattern. The challenge (and differentiator) is how structured the result is and what metadata it carries. |
| **Multi-turn Conversation Memory** | Agents must work across multiple user turns without forgetting the conversation. | MEDIUM | LangGraph checkpointing, OpenAI Sessions, PydanticAI `result_type` persist. Baseline: accumulate message list with token-budget trimming. |
| **Configurable System Prompt** | Users need to set agent persona, constraints, rules via system prompt. | LOW | Universal across frameworks. Trivial to implement. |
| **LLM Temperature/Model/Max Tokens Config** | Users must control generation parameters. | LOW | Pass-through to API call. |
| **Tool Call Validation (Schema Check Before Execute)** | Prevent runtime errors from malformed tool arguments before they reach the function. | MEDIUM | Pydantic/Python type validation before invocation. LangChain, PydanticAI, OpenAI all do this. Without it, tool execution is unreliable. |
| **Streaming Agent Output** | Users want to see agent thinking in real-time, not wait for full completion. | MEDIUM | LangGraph `stream_mode`, OpenAI SDK `.stream_events()`, SmolAgents streaming. Non-negotiable for developer productivity. |
| **Tool Timeout** | Prevent runaway tool execution from blocking the agent. | LOW | LangGraph node `timeout=`/`run_timeout`, harness-engineering `safe_subprocess_run` with timeout. A tool that hangs forever kills the agent. |

### Differentiators (Competitive Advantage)

Features that set a framework apart. loopAI's thesis is that **harness engineering** -- the infrastructure around the agent loop -- is where the real value lives. These features align with the project's core value: making agents reliable, observable, and extensible.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **Tool Abstraction Layer (Harness Core)** | Not just "call a function" -- each tool passes through a pipeline: discovery -> authorization -> execution -> result handling. Enables policy enforcement, auditing, and error classification per tool. | HIGH | Cited from MiniHarness 4-stage pipeline (discovery -> authorization -> execution -> result handling) and harness-engineering toolbox. This is loopAI's architectural differentiator -- most frameworks skip this and call functions directly. |
| **Structured Error Taxonomy** | Classify errors by category (TransientError, LLMRecoverableError, ToolExecutionError, GuardViolationError, ContextOverflowError) so the agent can make informed recovery decisions instead of blind retry. | MEDIUM | Cited from pyarnes error taxonomy and geny-executor ErrorCategory. Enables layered recovery strategies. No mainstream framework does this well. |
| **Layered Self-Healing Recovery** | Multi-level recovery: (1) cosmetic repair -> (2) in-context retry with feedback -> (3) full retry with backoff -> (4) human escalation. | HIGH | Cited from AgentField 4-layer schema recovery and harness engineering "three pillars." AutoGen and LangChain have basic retry, but not layered recovery. |
| **Execution Boundaries (Scope Sandbox)** | Constrain what tools can do: filesystem path scope (`PathScope`), command allow/deny lists, safe subprocess execution with env scrubbing. Prevent tools from escaping their intended domain. | MEDIUM | Cited from rail-sdk PathPolicy and harness-engineering `PathScope`/`safe_subprocess_run`. Critical for safety in bash/shell tool scenarios. |
| **Real-Time Observability Web Dashboard** | Live visualization of: agent reasoning chain, tool call timeline, state changes, token usage, latency breakdown. Interactive rewind/step-through of agent decisions. | HIGH | Cited from Honeycomb Agent Timeline, AgentDiagnose t-SNE plots, Hermes Agent dashboard. No open-source agent framework ships this out of the box -- LangSmith is proprietary/SaaS. This is loopAI's flagship differentiator. |
| **Guard Stage Pipeline** | Pre/post hooks around the agent loop: token budget guard, cost guard, rate limit guard, content moderation guard, permission guard. Fail fast before expensive LLM calls. | MEDIUM | Cited from geny-executor guard stages and OpenAI guardrails. LangChain has middleware hooks but no structured guard pipeline. |
| **Deterministic Session Replay** | Re-run a past agent session with the exact same tool results to debug, test, or audit the agent's reasoning. | MEDIUM | Cited from harness-engineering `ReplayRunner`. Enables reproduction of agent behavior -- critical for debugging but absent from all mainstream frameworks. |
| **Human-in-the-Loop Approval Gates** | Pause agent execution before high-risk tool calls (rm, shutdown, delete) and require human confirmation. Resume with state preserved. | MEDIUM | Cited from OpenAI tool approval, LangGraph `interrupt_before`, harness-engineering permission hooks. Essential for the disk cleanup validation scenario. |
| **Causal Provenance / Ablation** | Measure which tool calls actually influenced the final outcome. "Leave-one-out" analysis to identify unnecessary or misleading tool calls. | HIGH | Cited from harness-engineering `harness.attribute` module with Jaccard/Embedding similarity. Cutting-edge feature for agent debugging. No mainstream framework has this. |
| **Tool Speculative Execution** | Pre-execute likely next tool calls in async tasks while the LLM generates the next turn. Idempotency-gated to avoid side effects if the prediction is wrong. | VERY HIGH | Cited from harness-engineering `harness.speculate`. Reduces end-to-end latency. Experimental -- appropriate only after core is solid. |
| **Fuzz Testing for Tools** | Hypothesis-driven fuzzing of tool call arguments to find edge cases and failure modes before runtime. | MEDIUM | Cited from harness-engineering `harness.fuzz`. Developer tooling for tool robustness. |
| **Structured State Machine State** | Instead of ad-hoc message list, use a typed state graph (StateGraph style) with reducers for each field. Enables clean state transitions and easy checkpointing. | HIGH | LangGraph pioneered this. For a greenfield framework, implementing a simpler version (not full graph but typed state with reducers) gives the same benefits without graph complexity. |

### Anti-Features (Things to Deliberately NOT Build)

Features that seem attractive but create problems for a harness-focused framework.

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| **Full Multi-Agent Orchestration** | "More agents = more powerful." Market trend is toward multi-agent systems (AutoGen, CrewAI). | Multi-agent adds enormous complexity: inter-agent communication, agent discovery, consensus, shared state races, debugging across agents. It dilutes focus from harness depth. Single-agent with good harness is more reliable and easier to instrument. | Implement single-agent + tool composition (agents can delegate to sub-agents via tool calls). Do NOT build native multi-agent orchestration in v1. |
| **OpenAI-Compatibility Proxy Layer** | "We should support every LLM provider from day one." Users want flexibility. | Building and maintaining an adapter layer for 50+ providers is a massive maintenance burden. Provider APIs diverge in subtle ways (tool-call format, streaming, structured output). Half-baked support is worse than no support. | Support OpenAI-compatible API only (as PROJECT.md states). Add adapters only when a specific use case demands it and can be tested. |
| **Autonomous Tool Installation** | "Agent should install missing packages automatically." Seems convenient. | Security nightmare -- arbitrary package installation gives the agent escape vectors. Also creates reproducibility problems (different versions on different runs). | Tools declare their dependencies explicitly. Use containerized/venv execution with pre-installed deps. Fail with clear error if dep is missing. |
| **Visual Agent Builder (Drag & Drop)** | "Non-developers should build agents visually." Attracts broader audience. | Tremendous upfront UI investment with little value for the target developer audience. DnD flows cannot express the nuanced error handling, guard policies, and execution boundaries that are loopAI's differentiators. | CLI-first + YAML/JSON configuration. Web dashboard focuses on observability, not agent construction. |
| **Automatic Task Decomposition** | "Agent should break down complex tasks automatically." Sounds intelligent. | Without explicit decomposition boundaries, the agent creates unpredictable sub-task structures that are hard to observe, audit, or resume. Often results in planning loops that waste tokens. | Use explicit tool boundaries (the harness tool abstraction IS the decomposition primitive). Let the developer define tool granularity. |
| **Long-Term Memory / Vector Database** | "Agent should remember everything forever." General AI trope. | Adds vector DB dependency, embedding pipeline, retrieval latency, and memory poisoning risks. For a harness-focused framework, this is scope creep that distracts from execution quality. | Focus on session-level context management first (token budgeting, summarization, trimming). Add persistent memory as a separate milestone after core harness is proven. |

## Feature Dependencies

```
Agent Loop (Core)
    └──requires──> LLM Client (OpenAI-compatible API integration)
    └──requires──> Tool Call Parsing (extract tool calls from LLM response)
    └──requires──> Tool Result Injection (feed results back into context)
                       └──enhances──> Streaming Output (stream each loop iteration)

Tool System (Harness)
    └──requires──> Tool Registration API (decorator/schema)
    └──requires──> Tool Execution Pipeline
                       ├──requires──> Input Validation (Pydantic schema check before execution)
                       ├──requires──> Execution (run the actual tool function)
                       ├──requires──> Output Normalization (wrap raw output into structured ToolResult)
                       └──enhances──> Tool Authorization / Guard Stage (pre-execution policy check)

Bash/Shell Tool
    └──requires──> Tool Execution Pipeline (reuse the harness pipeline)
    └──requires──> subprocess Execution (safe subprocess runner with timeout)
    └──requires──> Output Capture (stdout + stderr + exit code)
    └──enhances──> PathScope Sandbox (restrict which directories bash can access)
    └──enhances──> Command Allow/Deny List (restrict which commands can run)
    └──requires──> Danger Confirmation Mechanism (for rm, shutdown, dd etc.)

Error Recovery System
    └──requires──> Structured Error Taxonomy
    └──requires──> Agent Loop Integration (loop must handle recovery decisions)
    └──requires──> Retry Policy Engine (configurable backoff + max attempts)
    └──enhances──> Layered Recovery Strategy (cosmetic -> in-context -> full retry -> escalate)
    └──enhances──> Human Escalation Path (for unrecoverable errors)

Context / State Management
    └──requires──> Message Accumulator (accumulate conversation history)
    └──requires──> Token Budget Tracker (count tokens, trigger summarization before overflow)
    └──enhances──> Typed State (structured state with reducers, not just a message list)
    └──enhances──> Checkpointing (save state for resume and replay)

Observability Web Dashboard
    └──requires──> Event Bus / Hook System (instrument Agent Loop + Tool Pipeline + Error Recovery)
    └──requires──> Event Serialization (convert internal events to JSON for frontend)
    └──requires──> WebSocket / SSE Endpoint (push real-time events to frontend)
    └──enhances──> Session Replay (replay past sessions in dashboard)
    └──enhances──> Agent State Snapshot (full state dump for debugging)

Guard Stage Pipeline
    └──requires──> Tool Execution Pipeline (hooks before/after execution)
    └──requires──> Budget Tracking (token, cost, rate-limit counters)
    └──enhances──> Pre-Tool Guard (fail fast before expensive LLM retry)
    └──enhances──> Post-Tool Guard (redact sensitive output)

Human-in-the-Loop
    └──requires──> Execution Pause Mechanism (interrupt agent loop, wait for confirmation)
    └──requires──> State Persistence (preserve state across pause/resume)
    └──requires──> Approval/Rejection API (user-facing endpoint to respond)
    └──enhances──> Bash Danger Confirmation (confirm before rm, dd, etc.)
```

### Dependency Notes

- **Agent Loop is the root dependency.** Nothing works without the core ReAct cycle. The loop must be designed with hook points from the start -- retrofitting hooks is expensive.
- **Tool Pipeline requires Input Validation before Execution.** Tool execution without input validation is fragile. Pydantic schema validation is the first line of defense.
- **Error Recovery depends on Structured Error Taxonomy.** Without classifying errors, recovery is a blind gamble (always retry vs always fail). The taxonomy drives the strategy.
- **Observability Dashboard depends on Event Bus.** The dashboard is worthless without instrumentation points in the agent loop, tool pipeline, and error recovery. The event bus must be designed upfront.
- **Bash Danger Confirmation depends on Human-in-the-Loop.** The confirmation mechanism for dangerous commands repurposes the same pause/resume infrastructure.
- **Checkpointing enables Replay and Human-in-the-Loop.** Both features require saving and restoring agent state at arbitrary points.

## MVP Definition

### Launch With (v1)

What constitutes a working ReAct agent with harness engineering for the disk space diagnosis and cleanup validation scenario.

- [x] **ReAct Agent Loop Core** -- LLM reasons, calls tools, observes results, loops. Parses tool calls from OpenAI-compatible response format. Correctly injects tool results as new messages. Terminates when LLM produces final answer or hits max iterations.
- [x] **Tool Registration API** -- Simple `@tool` decorator that converts a Python function into an agent tool. Infers JSON schema from type hints. Reads docstring for LLM description. Registers tool in a central registry.
- [x] **Tool Execution Pipeline** -- Unified path for all tool calls: validate inputs -> execute -> normalize result -> return to loop. Returns structured `ToolResult(error, output, metadata)` rather than raw strings.
- [x] **Bash/Shell Tool** -- A `BashTool` that executes shell commands via `subprocess` with: configurable timeout, stdout/stderr capture, exit code reporting. Must be registered through the standard tool pipeline so it inherits guards and hooks.
- [x] **Bash Danger Confirmation** -- Before executing a dangerous command (rm, dd, mkfs, etc.), pause the agent, surface the exact command to the user, wait for confirmation, then resume or skip. Implemented via the Human-in-the-Loop mechanism.
- [x] **Error Taxonomy (Initial)** -- At minimum: `TransientError` (retriable: network, rate-limit), `ToolExecutionError` (tool logic failure), `GuardViolationError` (policy blocked), `FatalError` (non-recoverable). Each carries structured metadata for the recovery system.
- [x] **Basic Retry on Transient Errors** -- Automatic retry with configurable max attempts and exponential backoff + jitter for `TransientError`. Must not retry `FatalError` or `GuardViolationError`.
- [x] **Streaming Agent Loop** -- Stream each loop iteration (thought -> tool call -> result -> next thought) via async generator/SSE. Enables real-time observation of agent reasoning.
- [x] **Event Bus / Hook System** -- Instrument Agent Loop, Tool Pipeline, and Error Recovery with emit points. Events carry structured payloads (type, timestamp, data, metadata). Must be designed upfront (cannot retrofit cleanly).
- [x] **Real-Time Web Dashboard** -- Web UI that displays live agent execution: streaming thought chain, tool call timeline (input/output/duration/status), error events, token counters. Updates via WebSocket/SSE. Must support basic session history browsing.
- [x] **Context Window Management** -- Track token usage per session. Before approaching model context limit, trigger summarization of oldest messages or drop with a warning. Prevent silent truncation of tool results.
- [x] **OpenAI-Compatible API Only** -- Connect to any OpenAI-compatible endpoint (official OpenAI, Azure, local LLMs with OpenAI proxy like Ollama/vLLM/LM Studio). Configurable base URL, API key, model name.

### Add After Validation (v1.x)

Features to add once the core agent + dashboard is working and the disk cleanup scenario is verified end-to-end.

- [ ] **Execution Boundaries (PathScope)** -- Restrict BashTool to specific directories. Prevent `../../` escape. Block access to `/etc`, `/sys`, `/proc` unless explicitly configured.
- [ ] **Command Allow/Deny Lists** -- Configure which commands BashTool can run (allow: df, du, find, ls; deny: rm, dd without confirmation override). Replaces the hardcoded danger list.
- [ ] **Layered Self-Healing Recovery** -- Full recovery pipeline: (1) cosmetic repair of malformed tool input -> (2) in-context retry with error description -> (3) full retry with backoff -> (4) human escalation. Automatically classify into the right layer.
- [ ] **Guard Stage Pipeline** -- Pre/post hooks for: token budget (cap), cost budget (cap), rate-limit (queue/throttle), content safety (input/output scanning). Fail fast before expensive LLM call.
- [ ] **Session Replay** -- Save complete agent session (all events + state). Replay in dashboard with step-forward/backward controls. Critical for debugging agent behavior after the fact.
- [ ] **Human-in-the-Loop Approval Gates** -- Generic pause/resume mechanism. Any tool can declare itself `requires_approval=True`. Agent pauses before execution, waits for user response via dashboard or CLI. State is preserved across pause.
- [ ] **Typed State (Beyond Message List)** -- Structured agent state with typed fields (current task, files modified, tool call history). Use reducers for conflict resolution. Enables cleaner checkpointing and state inspection.
- [ ] **Checkpointing** -- Persist agent state at key points (after each loop iteration). Resume from last checkpoint on crash. Enables human-in-the-loop and session replay as side effects.
- [ ] **Token-Cost Tracking in Dashboard** -- Real-time display of per-tool and cumulative token usage, estimated cost, number of LLM calls per session. Helps developers optimize agent prompts and tool design.

### Future Consideration (v2+)

Features to defer until the harness engineering value is proven with real developer usage.

- [ ] **Tool Speculative Execution** -- Pre-execute likely next tools while LLM generates. Requires idempotency analysis and execution rollback. High risk, high reward.
- [ ] **Causal Provenance (Ablation)** -- Leave-one-out analysis of tool calls. Requires full session replay infrastructure and the ability to re-run without specific tools.
- [ ] **Fuzz Testing for Custom Tools** -- Developer tool that auto-generates test cases for registered tools using property-based testing (Hypothesis). Helps find edge cases.
- [ ] **Multi-Agent via Tool Composition** -- Agents as tools: one agent delegates sub-tasks to another agent via tool call. NOT full multi-agent orchestration -- just agent-as-tool pattern.
- [ ] **Long-Term Memory (Vector DB)** -- Persistent memory across sessions. High complexity, high scope risk. Only after session-level context management is solid.
- [ ] **Provider Adapters (Anthropic, Gemini, Local)** -- Support additional LLM providers. Each adapter requires tool-call format handling (each provider has different tool-calling schemas). Add on demand, not proactively.

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| ReAct Agent Loop Core | HIGH | MEDIUM | P1 |
| Tool Registration API | HIGH | LOW | P1 |
| Tool Execution Pipeline | HIGH | MEDIUM | P1 |
| Bash/Shell Tool | HIGH | LOW | P1 |
| Bash Danger Confirmation | HIGH | LOW | P1 |
| Error Taxonomy (Initial) | HIGH | LOW | P1 |
| Basic Retry on Transient Errors | MEDIUM | LOW | P1 |
| Streaming Agent Loop | HIGH | MEDIUM | P1 |
| Event Bus / Hook System | HIGH | MEDIUM | P1 |
| Real-Time Web Dashboard | HIGH | HIGH | P1 |
| Context Window Management | HIGH | MEDIUM | P1 |
| OpenAI-Compatible API Only | HIGH | LOW | P1 |
| Execution Boundaries (PathScope) | MEDIUM | MEDIUM | P2 |
| Command Allow/Deny Lists | MEDIUM | LOW | P2 |
| Layered Self-Healing Recovery | HIGH | HIGH | P2 |
| Guard Stage Pipeline | MEDIUM | MEDIUM | P2 |
| Session Replay | HIGH | HIGH | P2 |
| Human-in-the-Loop Approval Gates | HIGH | MEDIUM | P2 |
| Typed State (Beyond Message List) | MEDIUM | HIGH | P2 |
| Checkpointing | MEDIUM | HIGH | P2 |
| Token-Cost Tracking in Dashboard | LOW | MEDIUM | P2 |
| Tool Speculative Execution | LOW | VERY HIGH | P3 |
| Causal Provenance (Ablation) | MEDIUM | VERY HIGH | P3 |
| Fuzz Testing for Custom Tools | LOW | MEDIUM | P3 |
| Multi-Agent via Tool Composition | MEDIUM | HIGH | P3 |
| Long-Term Memory (Vector DB) | LOW | HIGH | P3 |
| Provider Adapters | LOW | MEDIUM | P3 |

**Priority key:**
- P1: Must have for launch -- without these, the validation scenario (disk space diagnosis) cannot be demonstrated
- P2: Should have, add after core loop is working -- these are the harness engineering differentiators
- P3: Nice to have, future consideration -- do not build until harness value is proven

## Competitor Feature Analysis

| Feature | LangChain / LangGraph | OpenAI Agents SDK | SmolAgents (HF) | PydanticAI | loopAI (Plan) |
|---------|----------------------|-------------------|-----------------|------------|---------------|
| **ReAct Loop** | Via AgentExecutor or LangGraph | Via Runner.run_sync() | Native CodeAgent/ToolCallingAgent | Via Agent.run() | Custom, minimal, with hook points |
| **Tool Decorator** | `@tool` with args schema | `@function_tool` | `@tool` decorator | `@agent.tool` | `@tool` decorator, harness-aware |
| **Tool Pipeline** | Direct function call | Direct function call + guardrails | Direct function call | Direct function call | 4-stage pipeline: discover -> auth -> execute -> handle |
| **Bash/Shell Tool** | Third-party only | ShellTool in sandbox | LocalPythonInterpreter | Not built-in | First-class BashTool with harness wrapping |
| **Error Taxonomy** | Basic error types | Retry on API errors | Minimal | Pydantic validation errors | Structured 4-category taxonomy |
| **Layered Recovery** | LangGraph node error_handler (v1.2+) | Tool guardrails (either allow or skip) | Minimal | Validation retry loop | 4-layer recovery: cosmetic -> in-context -> full retry -> escalate |
| **Execution Boundaries** | Not built-in | SandboxAgent (container) | E2B/Docker backends | Not built-in | PathScope + Command allow/deny |
| **Observability Dashboard** | LangSmith (proprietary SaaS) | Built-in tracing UI | No dashboard | Logfire (proprietary) | Open-source, self-hosted, real-time |
| **Human-in-the-Loop** | LangGraph interrupt_before | Tool approval gates | Not built-in | Not built-in | Generic pause/resume + danger confirmation |
| **State Management** | Typed StateGraph with reducers | Session-based message history | Minimal (in-memory) | RunContext DI | Typed state with checkpointing (v1.x) |
| **Checkpointing** | Full persistence system | Redis sessions | Not built-in | Not built-in | Key-point checkpointing (v1.x) |
| **Session Replay** | LangSmith only | Not built-in | Not built-in | Not built-in | Built-in replay in dashboard (v1.x) |
| **Guard Stage Pipeline** | Callback system (scattered) | Input/output guardrails | Not built-in | Not built-in | Structured pre/post guard stages (v1.x) |
| **Multi-Agent** | First-class (LangGraph) | First-class (handoffs) | Via ManagedAgent | Via agent-as-tool | Agent-as-tool only (v2+) |
| **Provider Support** | Many adapters | OpenAI + 100 via adapters | Best-in-class (100+) | 40+ providers | OpenAI-compatible only |

## Phase-to-Feature Mapping (Roadmap Implications)

| Phase Theme | Features Included | Rationale |
|-------------|-------------------|-----------|
| **Phase 1: Core Loop** | ReAct Agent Loop, Tool Registration, Tool Execution Pipeline, OpenAI-compatible LLM Client, Streaming Output, Basic Context Management | Establish the foundation. Without a running agent loop, nothing else matters. Must demo "agent calls df, reads output, decides next step" end-to-end. |
| **Phase 2: Tool Harness** | BashTool, Bash Danger Confirmation, Error Taxonomy, Basic Retry, Event Bus | Add the first real tool (bash) with safety and reliability. The event bus is the observability foundation -- must be built before the dashboard. |
| **Phase 3: Observability** | Real-Time Web Dashboard, Token/Budget Tracking in UI, Session History | Build the WebSocket-backed dashboard that visualizes what Phase 1+2 produce. This is loopAI's flagship differentiator. |
| **Phase 4: Resilience** | Layered Recovery, Guard Stage Pipeline, Execution Boundaries (PathScope), Command Allow/Deny Lists | Deepen the harness. Add self-healing and execution safety. Makes the agent production-ready for the disk cleanup scenario. |
| **Phase 5: State & Replay** | Typed State, Checkpointing, Session Replay, Human-in-the-Loop Approval Gates | Add state persistence and debugging superpowers. Enables time-travel debugging and safe human oversight of dangerous operations. |

## Sources

- [LangChain Agent Documentation](https://docs.langchain.com/) -- Agent loop, tool calling, callback system (HIGH confidence)
- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/) -- StateGraph architecture, checkpointing, streaming (HIGH confidence)
- [LangGraph v1.2.0 Changelog](https://www.langchain.com/blog/january-2026-langchain-newsletter) -- Node timeout, error_handler, Delta Channels (HIGH confidence)
- [OpenAI Agents SDK GitHub](https://github.com/openai/openai-agents-python) -- Guardrails, tool approval, tracing, sandbox agents (HIGH confidence)
- [SmolAgents GitHub](https://github.com/huggingface/smolagents) -- CodeAgent, tool decorator, multi-LLM support (HIGH confidence)
- [PydanticAI Documentation](https://github.com/pydantic/pydantic-ai) -- Type-safe agents, validation retry, RunContext DI (HIGH confidence)
- [harness-engineering Toolbox](https://github.com/dr-gareth-roberts/harness-engineering) -- Tool abstraction, PathScope, ReplayRunner, speculative execution, fuzzing (MEDIUM confidence -- newer project, less community validation)
- [MiniHarness Guide](https://yeasy.gitbook.io/harness_engineering_guide) -- 4-stage tool pipeline, error-first design (MEDIUM confidence -- guide, not production framework)
- [pyarnes Template](https://github.com/Cognitivemesh/pyarnes) -- Error taxonomy, lifecycle FSM, guardrails (MEDIUM confidence -- template project)
- [geny-executor](https://pypi.org/project/geny-executor/) -- 16-stage pipeline, dual abstraction, guard stages (MEDIUM confidence -- small project)
- [AgentField HarnessRunner](https://github.com/Agent-Field/agentfield/issues/201) -- 4-layer schema recovery, retry with backoff (LOW confidence -- issue discussion, not released)
- [AgentDiagnose Toolkit](https://aclanthology.org/2025.emnlp-demos.15.pdf) -- t-SNE action plots, navigation graphs for agent debugging (MEDIUM confidence -- academic paper)
- [Honeycomb Agent Timeline](https://www.thefastmode.com/technology-solutions/48504-honeycomb-unveils-agent-timeline-canvas-agent-skills-for-ai-observability) -- Multi-agent trace visualization (MEDIUM confidence -- press release, not hands-on)

---
*Feature research for: ReAct AI Agent with Harness Engineering (loopAI)*
*Researched: 2026-05-27*
