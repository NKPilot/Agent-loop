<!-- GSD:project-start source:PROJECT.md -->
## Project

**loopAI**
<!-- GSD:project-end -->

<!-- GSD:stack-start source:research/STACK.md -->
## Technology Stack

## Recommended Stack
### Core Technologies
| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| **Python** | 3.13.x | Runtime | Latest stable with significant asyncio improvements: redesigned event loop scheduler (O(log n) task operations), experimental io_uring backend (60% fewer syscalls), free-threaded mode (PEP 703). All libraries target 3.13. |
| **openai** | 2.38.0 | LLM client | Official OpenAI SDK. Use directly (not through wrappers) to retain full control over the agent loop. The v2 SDK has mature streaming, tool calling, and response APIs. Async client (`openai.AsyncOpenAI`) is first-class. |
| **FastAPI** | 0.136.3 | Web framework | Standard for async Python APIs. Native SSE support (`EventSourceResponse`), WebSocket support, automatic Pydantic validation, OpenAPI docs. Required for real-time agent state streaming to the dashboard. |
| **Pydantic** | 2.13.4 | Data models | Industry standard for Python data validation. Powers FastAPI and Pydantic AI. Essential for tool schemas, agent state models, and structured output. The Rust-backed core (`pydantic-core`) provides 5-50x faster validation than v1. |
| **React** | 19.x | Frontend UI | React Compiler is stable, auto-memoizes components (eliminating manual `useMemo`/`useCallback`). `use()` API for async data reading. Required for building the observability dashboard with real-time event rendering. |
| **TypeScript** | 5.7+ | Frontend language | Type safety for the dashboard. Catches data shape mismatches between SSE events and UI components at compile time. |
| **Vite** | 8.0.14 | Frontend build tool | Rolldown (Rust-based bundler) replaces Rollup for dramatically faster builds. Universal plugin system. De facto standard for new React projects since 2024. |
| **Tailwind CSS** | 4.3.0 | Frontend styling | CSS-first configuration (no `tailwind.config.js` needed). Oxide engine delivers 5x faster builds. `@theme` directive for design tokens. Ideal for building custom dashboard UIs quickly without fighting opinionated component libraries. |
### Agent Loop — Approach Decision
### Supporting Libraries — Python Backend
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| **httpx** | 0.28.x | Async HTTP client | Required dependency of `openai` (used for API calls). Also useful for any direct HTTP calls from tools. |
| **psutil** | 7.2.2 | System monitoring | Disk space diagnosis (first business scenario). Provides `disk_usage()`, `disk_partitions()`, `disk_io_counters()` without shelling out to `df`/`du`. Cross-platform. |
| **rich** | 15.0.0 | CLI display | Agent thinking trace output in terminal/CLI mode. Render tables, markdown, syntax highlighting for tool calls and observations. Alternative to the web dashboard. |
| **asyncio** | (stdlib) | Async runtime | Python 3.13 includes improved task scheduling (binary heap priority queue), optimized cancellation, and experimental io_uring. |
| **subprocess** | (stdlib) | Bash execution | Use `subprocess.run(args_list, timeout=N, capture_output=True)` with `shell=False`. Never use `shell=True` with LLM-generated commands. |
| **shlex** | (stdlib) | Command safety | `shlex.quote()` and `shlex.split()` for safely handling user/LLM-provided command strings. |
| **json** | (stdlib) | Serialization | Agent state persistence to JSONL. Simpler than SQLite for a learning project. JSONL log = built-in audit trail. |
### Supporting Libraries — Frontend
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| **shadcn/ui** | CLI v4 | UI component library | Copy-paste components you own. Card, Dialog, Badge, Tooltip for the dashboard. No npm dependency — code lives in your repo. |
| **@tanstack/react-query** | 5.100.14 | Server state management | Agent session state, history caching. `queryClient.setQueryData()` for optimistic updates from SSE events. |
| **zustand** | 5.x | Client state management | Dashboard UI state (selected agent run, filter settings, theme toggle). Simpler than Redux, no boilerplate. |
| **recharts** | 2.x | Charts | Disk usage visualization (pie/bar for partition usage, line for I/O over time). React-friendly API. |
| **lucide-react** | (latest) | Icons | Clean, consistent icon set used by shadcn/ui. Disk, terminal, alert icons for the dashboard. |
### Development Tools
| Tool | Purpose | Notes |
|------|---------|-------|
| **uv** | Python package manager | 10-100x faster than pip. `uv pip install` or `uv sync` for dependency management. Rust-based, drop-in replacement for pip + venv. |
| **pytest** | Python testing | Async support via `pytest-asyncio`. Essential for testing agent loop, tool execution, sandbox. |
| **pytest-asyncio** | Async test support | Mark async tests with `@pytest.mark.asyncio`. Required for testing the agent loop. |
| **ruff** | Python linter/formatter | 100x faster than flake8 + isort + black. Single tool, zero config. |
| **mypy** | Python type checker | Strict mode catches data shape mismatches in tool schemas and agent state. |
| **node** (22.x+) | JS runtime | Required for Vite 8. Use latest LTS. |
| **pnpm** | JS package manager | Faster than npm, disk-efficient with content-addressable storage. |
## Installation
### Python Backend
# Using uv (recommended)
# Dev dependencies
### Frontend
# Using pnpm (recommended)
## Alternatives Considered
| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| **Build agent loop from scratch** | **Pydantic AI v1.103.0** | If fast iteration > learning depth. Pydantic AI provides type-safe tool abstraction, event streaming, dependency injection. v2 beta is available but v2 is not yet stable. |
| **Build agent loop from scratch** | **OpenAI Agents SDK v0.7+** | If accelerating toward multi-agent with handoffs. OpenAI-locked. Minimal abstraction, but adds handoff model and built-in tracing. |
| **Build agent loop from scratch** | **LangChain / LangGraph** | Never. Heavy abstraction, frequent breaking changes, hidden prompt injections. Directly opposed to the harness engineering learning goal. |
| **FastAPI** | **Django + Channels** | If you need Django ORM, admin panel, ecosystem. Overkill for this scope. Channels adds complexity over FastAPI's native SSE. |
| **React + Vite** | **Next.js** | If you need SSR, file-based routing, full-stack in one project. Unnecessary for a single-page dashboard. |
| **shadcn/ui** | **MUI (Material UI)** | If you need a comprehensive, opinionated design system with pre-built complex components (data grid, date pickers). MUI has a heavier bundle and you don't own the components. |
| **SSE** | **WebSocket** | If the dashboard needs bidirectional communication (e.g., sending commands to agent while it runs). For unidirectional observation, SSE is simpler. |
## What NOT to Use
| Avoid | Why | Use Instead |
|-------|-----|-------------|
| **LangChain** | Heavy abstraction that masks agent loop internals. Frequent breaking changes. Hidden prompt engineering. Directly contradicts the learning goal of understanding harness design. | Raw `openai` SDK |
| **LangGraph** | Graph-based orchestration is over-engineering for a single-agent system. Adds state machine complexity where a simple `while` loop suffices. | `while` loop + manual state |
| **CrewAI** | Multi-agent orchestration out of scope. Opinionated role-based design that is hard to customize. | Build from scratch when multi-agent is needed |
| **Django** | Synchronous ORM, heavy framework for a lightweight API. Channels adds complexity for real-time. | FastAPI |
| **Flask** | Synchronous only. No native async/await support without extensions. | FastAPI |
| **Redux** | Excessive boilerplate for dashboard state (selected run, filters, theme). | Zustand |
| **Styled Components** | Runtime CSS-in-JS adds bundle size and runtime overhead. Slower than utility CSS. | Tailwind CSS |
| **Celery** | Distributed task queue for a single-process agent. Premature infrastructure. | `asyncio.create_task()` |
| **SQLAlchemy** | ORM overkill for JSONL logging. Schema migrations for a learning project. | JSONL logging, simple file storage |
| **Docker** (initial) | Adds operational complexity before the core logic is solid. Learn first, containerize later. | Virtual environment |
| **`shell=True`** | Command injection via LLM-generated strings. LLM can generate `; rm -rf /`. | `subprocess.run([cmd, arg1, arg2], timeout=N)` with `shell=False` |
| **`eval()` / `exec()`** | Arbitrary code execution. LLM output should never be evaluated. | `json.loads()` for structured data, `shlex.split()` for commands |
## Stack Patterns by Variant
- Replace SSE with WebSocket
- FastAPI has native WebSocket support via `@app.websocket("/ws")`
- React side: use `useWebSocket` custom hook with exponential backoff reconnection
- Use the **Provider Adapter** pattern: define a protocol/base class `LLMClient` with `async def complete(messages, tools, stream)` 
- Implement per-provider: `OpenAIClient(LLMClient)`, `AnthropicClient(LLMClient)`, etc.
- This is part of the harness — the agent loop talks to `LLMClient`, not directly to `openai`
- Start with OpenAI only, add adapters as needed
- Wrap in Docker for reproducible deployment
- Add a database (SQLite for simplicity, PostgreSQL for scale)
- Use `uvicorn --workers N` behind nginx
- Add proper auth to the dashboard
- Serialize agent state (messages, tool results, step count) to JSONL
- JSONL format: one JSON object per line, each line is one step/event
- Built-in audit trail: you can replay any session step-by-step
## Version Compatibility
| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| openai 2.38.0 | Python 3.9+ | Async client is fully supported. No issues with 3.13. |
| fastapi 0.136.x | pydantic 2.x | Built on pydantic v2. No compatibility concerns. |
| pydantic 2.13.x | pydantic-ai 1.x | pydantic-ai 1.x pins pydantic v2. |
| rich 15.0.0 | Python 3.9+ | Drops Python 3.8 support. Python 3.13 is fine. |
| psutil 7.2.2 | All Python 3.x | v7 series is stable. |
| Vite 8.0.x | Node 20.19+ or 22.12+ | Requires modern Node.js. Use Node 22 LTS. |
| React 19.2.x | Vite 8.x | Vite 8 uses Rolldown, fully compatible. |
| Tailwind 4.3.x | Vite 8.x | Use `@tailwindcss/vite` plugin, no PostCSS config needed. |
| shadcn/ui CLI v4 | React 19.x + Tailwind 4.x | Updated for Tailwind v4. Interactive `init` setup. |
## Sources
- [PyPI: pydantic-ai 1.103.0](https://pypi.org/project/pydantic-ai/) — latest stable version verified 2026-05-27
- [PyPI: openai 2.38.0](https://pypi.org/project/openai/) — latest verified 2026-05-21
- [PyPI: fastapi 0.136.3](https://pypi.org/project/fastapi/) — latest verified 2026-05-23
- [PyPI: pydantic 2.13.4](https://pypi.org/project/pydantic/) — latest verified 2026-05-06
- [PyPI: psutil 7.2.2](https://pypi.org/project/psutil/) — latest verified 2026-01-28
- [PyPI: rich 15.0.0](https://pypi.org/project/rich/) — latest verified 2026-04-12
- [npm: vite 8.0.14](https://www.npmjs.com/package/vite) — verified via npm view
- [npm: react 19.2.6](https://www.npmjs.com/package/react) — verified via npm view
- [npm: @tanstack/react-query 5.100.14](https://www.npmjs.com/package/@tanstack/react-query) — verified via npm view
- [npm: tailwindcss 4.3.0](https://www.npmjs.com/package/tailwindcss) — verified via npm view
- [FastAPI SSE documentation](https://fastapi.tiangolo.com/advanced/custom-response/#streamingresponse) — verified EventSourceResponse support
- [Pydantic AI documentation](https://ai.pydantic.dev/) — agent framework event streaming, tool abstraction
- [OpenAI Python SDK documentation](https://github.com/openai/openai-python) — async client, streaming, tool calling
- [shadcn/ui CLI v4 changelog](https://ui.shadcn.com/docs/changelog/2026-03-cli-v4) — Tailwind v4 support, monorepo features
- [Tailwind CSS v4.3 release](https://tailwindcss.com/blog/tailwindcss-v4-3) — scrollbar utilities, container queries
- [Python 3.13 release notes](https://www.python.org/downloads/release/python-31313/) — async improvements verified
- [PEP 787 — Safer subprocess with t-strings](https://peps.python.org/pep-0787/) — deferred to Python 3.15, not yet available
- [AI Agent Framework Comparison 2026](https://dev.to/alexcloudstar/ai-agent-frameworks-in-2026-langgraph-vs-mastra-vs-vercel-ai-sdk-vs-openai-agents-sdk-vs-pydantic-539b) — framework tradeoffs analysis
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

Conventions not yet established. Will populate as patterns emerge during development.
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

Architecture not yet mapped. Follow existing patterns found in the codebase.
<!-- GSD:architecture-end -->

<!-- GSD:skills-start source:skills/ -->
## Project Skills

No project skills found. Add skills to any of: `.claude/skills/`, `.agents/skills/`, `.cursor/skills/`, `.github/skills/`, or `.codex/skills/` with a `SKILL.md` index file.
<!-- GSD:skills-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd-quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd-debug` for investigation and bug fixing
- `/gsd-execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->



<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd-profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
