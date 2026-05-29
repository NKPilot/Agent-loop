# Phase 05: 可观测性与 Web 前端 - Research

**Researched:** 2026-05-29
**Domain:** Web 可观测性 (FastAPI SSE + React 19 前端)
**Confidence:** HIGH

## Summary

Phase 5 builds the loopAI observability web frontend on top of the existing EventBus infrastructure from Phase 1 and the JSONL logging from Phase 1. The backend adds a FastAPI application with SSE streaming endpoints that bridge the in-process EventBus to browser clients. The frontend is a greenfield React 19 + Vite 8 + Tailwind 4 application using shadcn/ui components, delivering a three-panel dashboard (session list, agent timeline, tool detail) with real-time updates, token/cost tracking, session history browsing, and interactive disk cleanup demo with danger confirmation dialogs.

The key technical challenge is the EventBus-to-SSE bridge: an asyncio.Queue consumer that subscribes to the existing EventBus via the same pattern used by the CLI renderer and JSONL logger, then yields events as `ServerSentEvent` objects through FastAPI's native `EventSourceResponse`. This is the final phase of v1, integrating all prior subsystems (tools, context management, resilience) into a visual observability interface.

**Primary recommendation:** Build the FastAPI app as a separate module (`src/loopai/api/`) that imports and reuses the existing `EventBus`, `Session`, and component wiring from `main.py`. Create the frontend under `frontend/` with Vite 8, using Vite's dev proxy to connect to the FastAPI backend during development, and FastAPI's `StaticFiles` mount for production serving.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| OBS-01 | 事件总线 — 所有 harness 层通过结构化事件向外报告状态 | Already implemented (Phase 1): `src/loopai/events/bus.py` with 22 event types in `schemas.py`. Research covers reuse strategy. |
| OBS-02 | SSE 实时流端点 — 将 agent 状态变更实时推送到前端 | FastAPI `fastapi.sse.EventSourceResponse` (native since 0.134.0). SSE bridge consumer subscribes to EventBus `"*"`, yields `ServerSentEvent` objects. |
| OBS-03 | React Web 前端 — Agent 时间线、思考步骤、工具调用卡片 | React 19 + Vite 8 + Tailwind 4 + shadcn/ui CLI v4. Three-panel layout per UI-SPEC.md. SSE consumption via custom `useSSE` hook. |
| OBS-04 | Token/成本追踪 — 在前端展示每次调用的 token 消耗 | `StepEnd.token_usage` event field, cumulative tracking in Zustand store. recharts AreaChart for cost visualization. |
| OBS-05 | 会话历史浏览 — 查看过往 agent 会话记录 | REST API `/api/sessions` reads from `logs/sessions/*.jsonl`. `/api/sessions/{id}` returns full event history. React Query for caching. |
| BIZ-02 | 可交互演示 — 通过网页完整演示磁盘清理流程 | "Start Agent" button triggers POST `/api/sessions/start`. Confirmation dialog for dangerous commands (D-06). Full disk-cleanup flow visible in timeline. |
</phase_requirements>

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** 三面板布局。左侧会话列表（历史+当前），中间 Agent 思考/行动时间线（实时 SSE 驱动），右侧工具调用详情卡片（参数、结果、耗时）。
- **D-02:** 技术栈：React 19 + TypeScript 5.7 + Vite 8 + Tailwind CSS 4.3 + shadcn/ui (CLI v4) + @tanstack/react-query 5 + Zustand 5 + recharts + lucide-react。
- **D-03:** 单端点 `/api/sessions/{id}/stream`，所有事件类型走同一个 SSE 连接，前端按 `event_type` 分发到对应渲染组件。
- **D-04:** SSE 连接管理：自动重连（指数退避，最大 30s），断线期间显示"重连中"状态。
- **D-05:** 全功能交付——实时监控 + 会话历史浏览 + Token/成本追踪 + 磁盘清理完整交互演示。覆盖 OBS-01 到 OBS-05 及 BIZ-02。
- **D-06:** 危险操作确认弹窗集成到前端，用户在 Dashboard 中点击批准/拒绝。
- **UI-SPEC.md:** 所有布局、颜色、排版、间距、交互、文案契约必须遵守 05-UI-SPEC.md。

### Claude's Discretion
- 具体 UI 组件选型和组合 (shadcn/ui 组件选择)
- recharts 图表类型选择 (PieChart, LineChart, BarChart, AreaChart per UI-SPEC)
- 色彩方案和视觉风格 (shadcn default theme + custom success/warning tokens)
- Vite 代理配置
- SSE hook 实现方式 (custom hook preferred over third-party for simplicity)
- FastAPI app 模块组织

### Deferred Ideas (OUT OF SCOPE)
- 会话回放（step-forward/backward）— Phase 6
- 多用户支持 — v2
- 暗色模式切换 — Phase 6
</user_constraints>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| EventBus integration | API / Backend | — | EventBus is in-process Python; SSE bridge must be a co-located consumer |
| SSE streaming endpoint | API / Backend | — | FastAPI `EventSourceResponse` is server-side; browser consumes via `EventSource` |
| Session list API | API / Backend | — | JSONL files on server filesystem; REST endpoints expose session metadata |
| Session detail API | API / Backend | — | Reads and parses JSONL files; returns structured JSON |
| Confirmation request/response | API / Backend | Browser / Client | Backend publishes `confirmation_required` via SSE; frontend POSTs response |
| Timeline rendering | Browser / Client | — | React components consume SSE events, render DOM |
| Token/cost computation | Browser / Client | API / Backend | Cumulative tracking computed client-side from SSE events; cost rates configurable |
| Session list UI | Browser / Client | — | React Query fetches `/api/sessions`, renders list |
| Tool detail display | Browser / Client | — | React component renders tool call data from selected event in Zustand store |
| Static asset serving (prod) | API / Backend | CDN / Static | FastAPI `StaticFiles` mount serves Vite build output |
| Dev hot-reload proxy | Frontend Server (Vite) | — | Vite dev server proxies `/api` to FastAPI backend |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| **FastAPI** | 0.136.3 | Backend web framework | Per CLAUDE.md. Native SSE support (`fastapi.sse.EventSourceResponse`) since 0.134.0. Async-native, Pydantic v2 integration. |
| **uvicorn** | 0.38+ | ASGI server | Standard for FastAPI. Async event loop compatible with Python 3.13. |
| **React** | 19.2.6 | Frontend UI framework | Per D-02. React Compiler auto-memoizes. `use()` API for async data reading. [VERIFIED: npm registry] |
| **TypeScript** | 5.7+ | Frontend type safety | Per D-02. Catches SSE event shape mismatches at compile time. |
| **Vite** | 8.0.14 | Frontend build tool | Per D-02. Rolldown (Rust) for fast builds. Universal plugin system. [VERIFIED: npm registry] |
| **Tailwind CSS** | 4.3.0 | Frontend styling | Per D-02. CSS-first configuration (no `tailwind.config.js`). Oxide engine. [VERIFIED: npm registry] |
| **shadcn/ui** | CLI v4 | UI component library | Per D-02. Copy-paste components (not npm dependency). Radix UI primitives. Tailwind v4 support. [VERIFIED: Context7 /shadcn-ui/ui] |
| **@tanstack/react-query** | 5.100.14 | Server state management | Per D-02. Session list/data caching. `setQueryData()` for optimistic SSE updates. [VERIFIED: npm registry] |
| **zustand** | 5.0.14 | Client state management | Per D-02. Active session ID, selected tool call, UI filters. v5 API: `create()` with no curried wrapper. [VERIFIED: npm registry] |
| **recharts** | 3.8.1 | Charts | Per D-02. Token usage pie/area/line charts. React-native API. [VERIFIED: npm registry] |
| **lucide-react** | latest | Icons | Per D-02. Clean icon set used by shadcn/ui. `AlertTriangle`, `Terminal`, `CircleDot` for dashboard. |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| **fastapi.sse** | (built-in) | SSE event streaming | `EventSourceResponse` + `ServerSentEvent` for typed SSE events |
| **fastapi.middleware.cors** | (built-in) | CORS for dev | Allow Vite dev server origin (`http://localhost:5173`) |
| **fastapi.staticfiles** | (built-in) | Static file serving | Serve Vite production build from `frontend/dist/` |
| **asyncio** | (stdlib) | Async runtime | SSE bridge consumer uses `asyncio.Queue` from EventBus |
| **json** | (stdlib) | JSONL parsing | Parse session history from `logs/sessions/*.jsonl` |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| **fastapi.sse.EventSourceResponse** | sse-starlette | sse-starlette was the standard before FastAPI 0.134.0 added native SSE. Now redundant. Native is simpler, zero extra dependency. |
| **Custom useSSE hook** | react-use-sse-event npm package | Third-party hook adds dependency for simple EventSource wrapper. Custom hook is ~80 lines, no dependency, full control over reconnection logic. |
| **Zustand 5** | Redux, Jotai, Valtio | Zustand is locked by D-02 and is the right choice: zero boilerplate, no provider needed, TypeScript-first. |
| **recharts** | visx, nivo, chart.js | recharts is locked by D-02 and is ideal: React-native declarative API, good for the 4 chart types needed. |
| **Single FastAPI app** | Separate backend/frontend servers | Single process simpler for v1. FastAPI serves both API and static files. Vite proxy only needed in dev. |

**Installation:**
```bash
# Backend (new dependencies)
uv pip install fastapi uvicorn

# Frontend (greenfield)
cd frontend
pnpm create vite . --template react-ts
pnpm add @tanstack/react-query@5 zustand recharts lucide-react
npx shadcn@latest init -t vite
npx shadcn@latest add card dialog badge tooltip scroll-area separator button skeleton tabs progress alert dropdown-menu
```

**Version verification:**
- FastAPI 0.136.3 per CLAUDE.md recommendation [CITED: CLAUDE.md]
- React 19.2.6: `npm view react version` = 19.2.6 [VERIFIED: npm registry]
- Vite 8.0.14: `npm view vite version` = 8.0.14 [VERIFIED: npm registry]
- Tailwind CSS 4.3.0: `npm view tailwindcss version` = 4.3.0 [VERIFIED: npm registry]
- @tanstack/react-query 5.100.14: `npm view @tanstack/react-query version` = 5.100.14 [VERIFIED: npm registry]
- zustand 5.0.14: `npm view zustand version` = 5.0.14 [VERIFIED: npm registry]
- recharts 3.8.1: `npm view recharts version` = 3.8.1 [VERIFIED: npm registry]
- FastAPI NOT installed in current venv; will be added as new dependency

## Architecture Patterns

### System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        loopAI Process                           │
│                                                                 │
│  ┌──────────┐    ┌──────────────┐    ┌───────────────────────┐ │
│  │ ReActFSM │───▶│  EventBus    │───▶│ CLI Renderer (CLI)     │ │
│  │ (existing)│    │  (existing)  │    │ JSONL Logger (existing)│ │
│  │          │    │              │    │ SSE Bridge (NEW)       │ │
│  └──────────┘    └──────┬───────┘    └───────────┬───────────┘ │
│                         │                        │              │
│                         │ subscribe("*")         │ yield SSE    │
│                         │ asyncio.Queue          │ events       │
│                         │                        ▼              │
│  ┌──────────────────────┴──────────────────────────────────┐   │
│  │                   FastAPI App (NEW)                       │   │
│  │                                                          │   │
│  │  GET  /api/sessions              → list JSONL files      │   │
│  │  GET  /api/sessions/{id}         → read JSONL file       │   │
│  │  GET  /api/sessions/{id}/stream  → SSE EventSourceResponse│   │
│  │  POST /api/sessions/start        → spawn agent session   │   │
│  │  POST /api/sessions/{id}/confirm → respond to guard      │   │
│  │  DEL  /api/sessions/{id}         → delete session files   │   │
│  │  GET  /api/sessions/{id}/export  → download JSONL        │   │
│  │                                                          │   │
│  │  StaticFiles mount: / → frontend/dist/index.html         │   │
│  └──────────────────────┬───────────────────────────────────┘   │
└─────────────────────────┼───────────────────────────────────────┘
                          │ HTTP (port 8000)
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│  Dev Mode:                │  Production Mode:                   │
│  ┌──────────────────┐     │  ┌──────────────────────────────┐   │
│  │ Vite Dev Server   │     │  │ Browser                      │   │
│  │ (port 5173)       │     │  │ EventSource("/api/.../stream")│   │
│  │ proxy /api→:8000  │     │  │ fetch("/api/sessions")       │   │
│  │ HMR for React     │     │  │ Static assets from FastAPI   │   │
│  └──────────────────┘     │  └──────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### Recommended Project Structure
```
src/loopai/
├── api/                    # NEW: FastAPI application module
│   ├── __init__.py
│   ├── app.py              # FastAPI app factory, CORS, mounts
│   ├── sse_bridge.py       # EventBus → SSE consumer (AsyncGenerator)
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── sessions.py     # Session list/detail/delete/export endpoints
│   │   ├── stream.py       # SSE stream endpoint
│   │   └── control.py      # Start agent, confirmation response endpoints
│   └── schemas.py          # Pydantic response models for API
├── events/                 # EXISTING: unchanged
├── consumers/              # EXISTING: unchanged
├── session/                # EXISTING: unchanged
└── main.py                 # EXISTING: CLI entry point (unchanged)

frontend/                   # NEW: greenfield Vite + React project
├── index.html
├── package.json
├── tsconfig.json
├── vite.config.ts          # Proxy /api → localhost:8000
├── src/
│   ├── main.tsx            # React entry point
│   ├── App.tsx             # Root layout (three-panel)
│   ├── components/
│   │   ├── ui/             # shadcn/ui components (generated)
│   │   ├── SessionList.tsx       # Left panel
│   │   ├── AgentTimeline.tsx     # Center panel
│   │   ├── ToolDetail.tsx        # Right panel
│   │   ├── ConfirmationDialog.tsx # Danger command modal
│   │   ├── ConnectionStatus.tsx  # SSE connection indicator
│   │   ├── TokenUsageCard.tsx    # Token/cost summary
│   │   └── StepCard.tsx          # Timeline step rendering
│   ├── hooks/
│   │   ├── useSSE.ts             # SSE connection with reconnection
│   │   └── useSessionEvents.ts   # Event dispatch to stores
│   ├── stores/
│   │   ├── uiStore.ts            # Zustand: active session, selected tool, filters
│   │   └── eventStore.ts         # Zustand: accumulated events per session
│   ├── lib/
│   │   ├── eventTypes.ts         # TypeScript types matching Python schemas
│   │   ├── costCalculator.ts     # Token → cost estimation
│   │   └── api.ts                # fetch wrappers for REST endpoints
│   └── styles/
│       └── index.css             # Tailwind imports + custom tokens
└── components.json               # shadcn/ui configuration
```

### Pattern 1: SSE Bridge (EventBus → FastAPI ServerSentEvent)
**What:** An async generator that subscribes to the EventBus and yields typed `ServerSentEvent` objects. This is the critical architectural bridge between the existing event system and the web frontend.

**When to use:** Every agent session that needs real-time browser observability.

**Example:**
```python
# Source: FastAPI docs via Context7 /fastapi/fastapi + existing EventBus pattern
from typing import AsyncIterable
import asyncio
from fastapi import FastAPI
from fastapi.sse import EventSourceResponse, ServerSentEvent
from loopai.events.bus import EventBus

app = FastAPI()

async def event_stream(session_id: str, bus: EventBus) -> AsyncIterable[ServerSentEvent]:
    """Bridge EventBus to SSE: subscribe, yield, handle disconnect."""
    queue = await bus.subscribe("*")
    try:
        # Replay existing events for late-connecting clients
        for event in bus.replay():
            if event.get("session_id") == session_id:
                yield ServerSentEvent(
                    data=event,
                    event=event["event_type"],
                    id=str(len(event)),  # sequence for Last-Event-ID
                )

        # Stream new events
        while True:
            event = await queue.get()
            if event is None:  # shutdown sentinel
                break
            if event.get("session_id") == session_id:
                yield ServerSentEvent(
                    data=event,
                    event=event["event_type"],
                    id=str(len(event)),
                    retry=3000,  # suggest 3s reconnection delay
                )
    finally:
        await bus.unsubscribe("*", queue)

@app.get("/api/sessions/{session_id}/stream", response_class=EventSourceResponse)
async def stream_session(session_id: str):
    # bus is obtained from app.state or dependency injection
    return EventSourceResponse(event_stream(session_id, bus))
```

### Pattern 2: React SSE Hook with Exponential Backoff
**What:** A custom React hook wrapping the native `EventSource` API with automatic reconnection and event type dispatch.

**When to use:** The single SSE connection for real-time agent timeline updates.

**Example:**
```typescript
// Source: MDN EventSource API + research best practices
import { useEffect, useRef, useState, useCallback } from 'react';

interface SSEOptions {
  onEvent: (eventType: string, data: unknown) => void;
  maxRetries?: number;
  maxBackoff?: number;
}

export function useSSE(url: string | null, options: SSEOptions) {
  const { onEvent, maxRetries = 10, maxBackoff = 30000 } = options;
  const [status, setStatus] = useState<'connected' | 'connecting' | 'reconnecting' | 'failed'>('connecting');
  const esRef = useRef<EventSource | null>(null);
  const retryCountRef = useRef(0);
  const timeoutRef = useRef<ReturnType<typeof setTimeout>>();

  const connect = useCallback(() => {
    if (!url) return;
    
    const es = new EventSource(url);
    esRef.current = es;
    setStatus('connecting');

    es.onopen = () => {
      setStatus('connected');
      retryCountRef.current = 0;
    };

    // Handle typed events (event: field in SSE)
    es.addEventListener('step_start', (e) => onEvent('step_start', JSON.parse(e.data)));
    es.addEventListener('llm_token', (e) => onEvent('llm_token', JSON.parse(e.data)));
    es.addEventListener('tool_call_start', (e) => onEvent('tool_call_start', JSON.parse(e.data)));
    es.addEventListener('tool_result', (e) => onEvent('tool_result', JSON.parse(e.data)));
    es.addEventListener('step_end', (e) => onEvent('step_end', JSON.parse(e.data)));
    es.addEventListener('session_end', (e) => onEvent('session_end', JSON.parse(e.data)));
    es.addEventListener('confirmation_required', (e) => onEvent('confirmation_required', JSON.parse(e.data)));
    // ... register all 22 event types
    es.addEventListener('error', (e) => onEvent('error', JSON.parse(e.data)));

    es.onerror = () => {
      es.close();
      const retries = retryCountRef.current;
      if (retries >= maxRetries) {
        setStatus('failed');
        return;
      }
      const delay = Math.min(1000 * Math.pow(2, retries), maxBackoff);
      retryCountRef.current = retries + 1;
      setStatus('reconnecting');
      timeoutRef.current = setTimeout(connect, delay);
    };
  }, [url, onEvent, maxRetries, maxBackoff]);

  useEffect(() => {
    connect();
    return () => {
      esRef.current?.close();
      clearTimeout(timeoutRef.current);
    };
  }, [connect]);

  return { status };
}
```

### Pattern 3: React Query + SSE Optimistic Updates
**What:** SSE events feed into React Query's cache via `queryClient.setQueryData()`, keeping the session timeline and session list in sync without refetching.

**When to use:** When building the timeline from streaming events and updating the session list when sessions complete.

```typescript
// Source: TanStack Query v5 docs via Context7 /websites/tanstack_query_v5
import { useQueryClient } from '@tanstack/react-query';

function useSSEEventHandler(sessionId: string) {
  const queryClient = useQueryClient();

  return useCallback((eventType: string, data: any) => {
    switch (eventType) {
      case 'step_start':
        queryClient.setQueryData(['session', sessionId, 'steps'], (old: any[]) =>
          [...(old || []), { stepNum: data.step_num, events: [], status: 'active' }]
        );
        break;
      case 'llm_token':
        queryClient.setQueryData(['session', sessionId, 'steps'], (old: any[]) => {
          if (!old) return old;
          const updated = [...old];
          const lastStep = { ...updated[updated.length - 1] };
          lastStep.thinking = (lastStep.thinking || '') + data.content_delta;
          updated[updated.length - 1] = lastStep;
          return updated;
        });
        break;
      case 'tool_result':
        // Update tool call in the step with result + duration
        queryClient.setQueryData(['session', sessionId, 'toolCalls'], (old: any[]) =>
          (old || []).map(tc =>
            tc.tool_call_id === data.tool_call_id
              ? { ...tc, result: data.result, duration_ms: data.duration_ms, is_error: data.is_error }
              : tc
          )
        );
        break;
      case 'session_end':
        // Invalidate session list to show updated status
        queryClient.invalidateQueries({ queryKey: ['sessions'] });
        break;
      case 'confirmation_required':
        // Trigger Zustand store to open the dialog
        useUIStore.getState().setPendingConfirmation(data);
        break;
    }
  }, [sessionId, queryClient]);
}
```

### Pattern 4: Zustand Store for Client UI State
**What:** Simple Zustand store for UI-only state that doesn't belong in React Query's server-state cache.

```typescript
// Source: Zustand v5 docs via Context7 /pmndrs/zustand
import { create } from 'zustand';

interface UIState {
  activeSessionId: string | null;
  selectedToolCallId: string | null;
  pendingConfirmation: ConfirmationEvent | null;
  setActiveSession: (id: string) => void;
  selectToolCall: (id: string | null) => void;
  setPendingConfirmation: (event: ConfirmationEvent | null) => void;
}

export const useUIStore = create<UIState>((set) => ({
  activeSessionId: null,
  selectedToolCallId: null,
  pendingConfirmation: null,
  setActiveSession: (id) => set({ activeSessionId: id, selectedToolCallId: null }),
  selectToolCall: (id) => set({ selectedToolCallId: id }),
  setPendingConfirmation: (event) => set({ pendingConfirmation: event }),
}));
```

### Pattern 5: FastAPI App Factory with SSE-Ready Lifecycle
**What:** FastAPI app created via factory function that wires EventBus into `app.state`, manages agent session lifecycle, and serves both API and static files.

```python
# Source: FastAPI docs + existing main.py patterns
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from loopai.events.bus import EventBus
from loopai.api.routes import sessions, stream, control

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: create EventBus. Shutdown: drain subscribers."""
    app.state.bus = EventBus()
    app.state.active_sessions: dict[str, "Session"] = {}
    yield
    await app.state.bus.shutdown()

def create_app() -> FastAPI:
    app = FastAPI(title="loopAI API", lifespan=lifespan)

    # CORS for Vite dev server
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://localhost:8000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # API routes
    app.include_router(sessions.router, prefix="/api")
    app.include_router(stream.router, prefix="/api")
    app.include_router(control.router, prefix="/api")

    # SPA fallback: serve frontend static files, catch-all to index.html
    import os
    frontend_dist = "frontend/dist"
    if os.path.isdir(frontend_dist):
        app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")

    return app
```

### Anti-Patterns to Avoid
- **SSE over WebSocket for unidirectional data:** SSE is simpler (native HTTP, auto-reconnect, no upgrade handshake). WebSocket adds bidirectional complexity not needed here.
- **Multiple SSE connections per session:** D-03 mandates single endpoint. Multiple connections would duplicate events and waste server resources.
- **Direct DOM manipulation in React:** Use React state and effects. shadcn/ui components handle accessibility.
- **Storing streaming event data in React Query only:** Use Zustand for the "current streaming state" pattern — React Query for persisted/completed data, Zustand for in-flight accumulation.
- **Blocking the EventBus queue:** The SSE bridge consumer MUST drain its queue promptly. Never do synchronous I/O in the SSE event loop.
- **Not handling SSE client disconnect:** Always use `try/finally` to unsubscribe from EventBus. Disconnected clients that don't clean up will leak queue slots (max 256 subscribers).
- **Re-rendering on every LLMToken:** Use React 19's automatic memoization + throttle rendering. The CLI renderer already throttles to 80ms; the frontend should do similar (requestAnimationFrame batching or 60fps cap).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| SSE protocol formatting | Custom `data: ...\n\n` string builder | FastAPI `ServerSentEvent` + `EventSourceResponse` | Handles encoding, event IDs, retry fields, connection close detection. Built into FastAPI since 0.134.0. |
| Frontend SSE client with reconnection | Custom `fetch()` with `ReadableStream` | Native `EventSource` API | Built-in auto-reconnect (with `retry` field), simpler API, all browsers support it. One caveat: no custom headers — for auth use query params or cookies. |
| Session JSONL parsing | Custom line-by-line JSON parser | Python `json.loads()` per line | JSONL is trivial (one JSON object per line). Existing `JSONLLogger` already writes valid JSONL. |
| Token counting for cost display | Custom tokenizer in browser | Server-side `tiktoken` (cl100k_base) + `StepEnd.token_usage` | Token counts come from the Python backend — the frontend only displays them. Cost estimation is simple math client-side: `prompt * rate_prompt + completion * rate_completion`. |
| CSS-in-JS or custom component library | Building styled components from scratch | Tailwind CSS 4 + shadcn/ui | Utility classes cover 95% of styling. shadcn/ui provides accessible, customizable primitives. No npm dependency for components. |
| Frontend state synchronization | Custom event bus or Redux | @tanstack/react-query + Zustand | React Query handles server state (fetching, caching, invalidation). Zustand handles client-only UI state. Clear separation of concerns. |
| Chart rendering from scratch | Canvas/SVG manual drawing | recharts | Declarative React components. PieChart, LineChart, BarChart, AreaChart cover all visualization needs per UI-SPEC. |
| CORS headers | Manual response header injection | `fastapi.middleware.cors.CORSMiddleware` | Handles preflight (OPTIONS), origin validation, credentials. One middleware addition. |

**Key insight:** The two "custom" pieces that ARE appropriate to build are: (1) the SSE bridge consumer — ~60 lines, specific to the EventBus API, and (2) the `useSSE` React hook — ~80 lines, specific to the 22 event types. Everything else uses standard libraries.

## Runtime State Inventory

> Phase 5 is a greenfield addition (new API + new frontend). No rename/refactor/migration. This section is included for completeness but no runtime state to migrate.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | JSONL session logs in `logs/sessions/` — will be read by new API endpoints | None — API reads existing files, no migration |
| Live service config | None — no external services reference loopAI | None |
| OS-registered state | None — no systemd/launchd/pm2 registrations | None |
| Secrets/env vars | OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL — already in `.env` | Reuse existing env vars for API server |
| Build artifacts | None — no frontend build exists yet | Greenfield setup |

**Nothing found in any category that requires migration.**

## Common Pitfalls

### Pitfall 1: EventBus Queue Backpressure from SSE Client
**What goes wrong:** A slow SSE client (browser tab throttled, network congestion) causes the EventBus subscriber queue to fill up. When the queue hits maxsize=256, events are dropped with a warning. The frontend sees gaps in the timeline.

**Why it happens:** The SSE bridge reads from an `asyncio.Queue(maxsize=256)`. If the HTTP response write is slower than the event publication rate (common during `llm_token` bursts), the queue fills up.

**How to avoid:** 
1. The SSE bridge consumer should drain the queue as fast as possible — never `await` on I/O inside the queue read loop.
2. FastAPI's `EventSourceResponse` handles backpressure natively via ASGI flow control.
3. Drop non-critical events under backpressure: prioritize `llm_token` (most frequent) for coalescing.
4. Consider batching `llm_token` events: collect deltas for 50ms, then send as a single event.

**Warning signs:** `RuntimeWarning: EventBus: dropping event 'llm_token' for slow consumer` in server logs. Timeline gaps in the frontend.

### Pitfall 2: Vite Proxy Not Forwarding SSE Properly
**What goes wrong:** In development, the Vite dev server proxy strips or buffers the SSE response, causing the `EventSource` connection to timeout or never receive events.

**Why it happens:** Some HTTP proxies buffer responses. Vite's proxy (based on `http-proxy`) may buffer chunked transfer encoding responses by default.

**How to avoid:** Configure Vite proxy with explicit SSE-friendly options. Test with `curl -N` to verify streaming works:
```typescript
// vite.config.ts
export default defineConfig({
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        // Do NOT add any buffering middleware
      }
    }
  }
});
```
Vite 8's proxy (http-proxy 1.18+) handles SSE correctly by default. If issues arise, verify `proxyReq` and `proxyRes` event handlers aren't buffering.

**Warning signs:** `EventSource` fires `onerror` immediately. `curl -N http://localhost:5173/api/sessions/x/stream` shows buffered output instead of streaming chunks.

### Pitfall 3: React Re-render Storms from LLMToken Events
**What goes wrong:** `llm_token` events fire at 10-50 tokens/second during LLM streaming. If every token triggers a full state update, React re-renders the entire timeline on each token, causing UI jank.

**Why it happens:** Naive `setState` or `setQueryData` on every `llm_token` event without batching.

**How to avoid:**
1. Accumulate token deltas in a ref (`useRef`), flush to state at ~60fps via `requestAnimationFrame`.
2. Use React 19's automatic memoization — the React Compiler handles this, but verify.
3. The component that displays streaming text should use `useDeferredValue` for the text content to avoid blocking user interactions.
4. Structure the event handler so only the streaming text component re-renders, not the entire timeline.

**Warning signs:** Scrolling becomes laggy, confirmation dialogs are slow to open, CPU usage spikes during LLM streaming.

### Pitfall 4: Missing SPA Fallback Route
**What goes wrong:** In production, refreshing the browser on a client-side route (e.g., `/session/abc123`) returns a 404 because FastAPI doesn't have that route.

**Why it happens:** React Router (or URL-based state) creates client-side URLs. The server must serve `index.html` for all non-API paths.

**How to avoid:** Mount `StaticFiles` with `html=True` on the root path AFTER all API routes. This makes FastAPI serve `index.html` for any path that doesn't match an API route:
```python
# API routes must be registered BEFORE the static mount
app.include_router(sessions.router, prefix="/api")
# ...
app.mount("/", StaticFiles(directory="frontend/dist", html=True), name="frontend")
```

**Warning signs:** 404 on page refresh. Works on first load from `/` but breaks on deep links.

### Pitfall 5: Confirmation Timeout Mismatch
**What goes wrong:** The PermissionGuard has a configurable timeout (`confirmation_timeout`, default 120s). If the frontend doesn't respect this, the agent could hang indefinitely or the confirmation response could arrive after the timeout.

**Why it happens:** The SSE connection delivers the `confirmation_required` event, but there's no mechanism to communicate the timeout deadline to the frontend.

**How to avoid:**
1. Include the timeout deadline in the `confirmation_required` event (or add a `timeout_seconds` field).
2. Show a countdown timer in the ConfirmationDialog.
3. If the timeout expires before user action, auto-dismiss the dialog and show "Confirmation timed out" in the timeline.
4. The `PermissionGuard` should publish a `confirmation_timeout` event so the frontend can react.

**Warning signs:** Dialog stays open after agent has already proceeded. Stale confirmation state.

### Pitfall 6: shadcn/ui CLI v4 Init on Existing Project
**What goes wrong:** Running `npx shadcn@latest init` on an already-initialized Vite project can overwrite `tailwind.config` (irrelevant in Tailwind v4), `index.css`, or `components.json`.

**How to avoid per UI-SPEC:** UI-SPEC explicitly states `shadcn_initialized: false` and defers init to plan execution. The plan should: (1) create fresh Vite project via `pnpm create vite`, (2) run `npx shadcn@latest init -t vite`, (3) add components via `npx shadcn@latest add <component>`. This is the standard approach for greenfield shadcn/ui projects.

## Code Examples

Verified patterns from official sources:

### FastAPI SSE Endpoint with Event Typing
```python
# Source: Context7 /fastapi/fastapi — tutorial/server-sent-events.md
from typing import AsyncIterable
from fastapi import FastAPI
from fastapi.sse import EventSourceResponse, ServerSentEvent

@app.get("/stream-sse-events", response_class=EventSourceResponse)
async def stream_sse_events() -> AsyncIterable[ServerSentEvent]:
    yield ServerSentEvent(data={"message": "Starting stream"}, event="start")
    for i in range(5):
        yield ServerSentEvent(
            data={"count": i},
            event="update",
            id=str(i),
            retry=5000,
        )
        await asyncio.sleep(0.5)
    yield ServerSentEvent(data={"message": "Stream finished"}, event="end")
```

### FastAPI Static Files with SPA Fallback
```python
# Source: Context7 /fastapi/fastapi — tutorial/static-files.md
from fastapi.staticfiles import StaticFiles

app = FastAPI()
# Mount with html=True for SPA fallback (serves index.html for 404s)
app.mount("/", StaticFiles(directory="frontend/dist", html=True), name="frontend")
```

### Vite Proxy Configuration
```typescript
// Source: Context7 /vitejs/vite — config/server-options.md
export default defineConfig({
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      }
    }
  }
});
```

### Zustand v5 Store (Simple)
```typescript
// Source: Context7 /pmndrs/zustand — v5 API (no curried wrapper)
import { create } from 'zustand';

interface BearState {
  bears: number;
  addABear: () => void;
}

export const useBearStore = create<BearState>()((set) => ({
  bears: 0,
  addABear: () => set((state) => ({ bears: state.bears + 1 })),
}));
```

### React Query setQueryData with SSE
```typescript
// Source: Context7 /websites/tanstack_query_v5 — updates-from-mutation-responses
const queryClient = useQueryClient();

// Append to a list in cache (immutable update)
queryClient.setQueryData(['session', id, 'steps'], (old: Step[] | undefined) =>
  old ? [...old, newStep] : [newStep]
);
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `sse-starlette` third-party package | FastAPI native `fastapi.sse.EventSourceResponse` | FastAPI 0.134.0 (2025) | Zero extra dependency. Built-in typing and validation. |
| Zustand v4 `create()` with curried type | Zustand v5 `create<T>()((set) => ...)` | Zustand 5.0 (2025) | Newer API, no curried generic wrapper. Both APIs work; v5 is current. |
| Tailwind CSS v3 with `tailwind.config.js` | Tailwind CSS v4 CSS-first config via `@theme` | Tailwind 4.0 (2025) | No JS config file. `@theme` directive in CSS. `@import "tailwindcss"` replaces `@tailwind` directives. |
| React.memo + useMemo/useCallback everywhere | React 19 Compiler auto-memoization | React 19 (2024) | Automatic memoization. Manual hooks still work but are unnecessary in most cases. |
| Vite with Rollup (JS) | Vite 8 with Rolldown (Rust) | Vite 7+ (2025) | 3-5x faster production builds. API compatible with Rollup plugins. |

**Deprecated/outdated:**
- `sse-starlette`: Native SSE in FastAPI 0.134.0+ makes it redundant. Do not install.
- `@tailwindcss/vite` plugin (pre-4.4): Tailwind 4.3 uses the plugin but the API is stable. No concerns.
- Redux, Jotai, Valtio for this project: Zustand is locked by D-02 and is the right choice.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | FastAPI 0.136.3 is the correct version to install (per CLAUDE.md). The SSE module (`fastapi.sse`) is available in all versions >= 0.134.0. | Standard Stack | LOW — CLAUDE.md is authoritative for this project. Even if 0.136.3 is unavailable, any version >= 0.134.0 works. |
| A2 | shadcn/ui CLI v4 `init -t vite` works with Vite 8.0.14 and Tailwind 4.3.0 without version conflicts. | Standard Stack | LOW — shadcn/ui CLI v4 was specifically updated for Tailwind v4. The `-t vite` template is the primary supported path. [CITED: shadcn/ui docs — installation/vite.mdx] |
| A3 | The Vite dev server proxy passes SSE (chunked transfer-encoding) without buffering. | Architecture | MEDIUM — Some proxy configurations buffer chunked responses. Verify with `curl -N` during implementation. Workaround: configure `http-proxy` to not buffer, or bypass proxy for SSE in dev (connect directly to `:8000`). |
| A4 | The existing `EventBus._history` list provides sufficient replay for late-connecting SSE clients. | Architecture | MEDIUM — The history list grows unboundedly (no eviction). For long sessions (>1000 events), this could cause memory pressure. Mitigation: limit replay to last N events, or clear history on session end. |
| A5 | The `StepEnd.token_usage` field reliably contains `prompt_tokens` and `completion_tokens` keys matching OpenAI's format. | Code Examples, OBS-04 | LOW — This field comes from the existing OpenAI API response via `LLMClient`. The format is standard. |
| A6 | pnpm is available on the target system for frontend package management. | Environment | LOW — `which pnpm` returned a valid path. CLAUDE.md recommends pnpm. |
| A7 | The OpenAI API token usage format uses `prompt_tokens` and `completion_tokens` keys (not `input_tokens`/`output_tokens`). | Token Tracking | LOW — OpenAI's API uses `prompt_tokens` and `completion_tokens`. The existing codebase already processes these fields. |

## Open Questions (RESOLVED)

1. **Session isolation in EventBus**
   - What we know: EventBus is a singleton per process. All sessions share the same bus. The SSE bridge filters by `session_id`.
   - What's unclear: How to handle concurrent sessions — each needs its own SSE stream but they share the same EventBus.
   - RESOLVED: The SSE bridge filters events by `session_id` (already in every event). Concurrent sessions just get separate SSE endpoints, each filtering independently. No architectural change needed. However, `bus.replay()` returns ALL events — the replay filter must apply `session_id` to avoid leaking cross-session data.

2. **How to wire FastAPI lifespan with existing `run_session()`**
   - What we know: `run_session()` in `main.py` creates all components (EventBus, Session, guards, FSM) and orchestrates the lifecycle. The FastAPI app needs to do the same but expose endpoints.
   - What's unclear: Whether to refactor `run_session()` into reusable factory functions, or duplicate the wiring.
   - RESOLVED: Extract component creation into factory functions (`create_event_bus()`, `create_session()`, `create_fsm()`). `run_session()` becomes a thin wrapper. The FastAPI control endpoint uses the same factories. This minimizes duplication and ensures CLI and Web paths stay in sync.

3. **Confirmation flow across SSE boundary**
   - What we know: CLI `CLIAgentRenderer` handles confirmation by pausing Live display, reading `console.input()`, and calling `PermissionGuard.respond()`. The web frontend needs equivalent via SSE + HTTP POST.
   - What's unclear: Whether the `PermissionGuard.respond(confirmation_id, approved)` call is thread-safe / async-safe when called from an HTTP handler.
   - RESOLVED: Read the `PermissionGuard` implementation to verify. Based on existing code, `PermissionGuard` uses `asyncio.Event` internally — fully async-safe. The HTTP POST handler can directly call `permission_guard.respond()`.

4. **Session history data format for the frontend**
   - What we know: JSONL files contain raw events with `seq`, `ts`, `session_id` wrapper. The frontend needs a structured session summary.
   - What's unclear: Exact response format for `/api/sessions` and `/api/sessions/{id}`.
   - RESOLVED: `/api/sessions` returns a lightweight list (id, created_at, step_count, status, exit_reason). `/api/sessions/{id}` returns the full event array. The frontend reconstructs the timeline client-side from the event array — same as it does for live SSE events.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.13 | FastAPI backend | Y | 3.13.13 | — |
| Node.js | Vite, npm/pnpm | Y | 24.15.0 | — |
| npm | Frontend packages | Y | 11.12.1 | — |
| pnpm | Frontend package manager (per CLAUDE.md) | Y | available | npm if pnpm unavailable |
| FastAPI | Backend SSE + REST API | N | — | **Must install:** `uv pip install fastapi` |
| uvicorn | ASGI server | N | — | **Must install:** `uv pip install uvicorn` |
| Existing EventBus | SSE bridge consumer | Y | already in src/loopai/events/bus.py | — |
| Existing JSONL logs | Session history API | Y | already in src/loopai/consumers/jsonl_logger.py | — |
| Existing Pydantic | API schema validation | Y | 2.13.4 | — |
| Existing openai SDK | Agent runs from web | Y | 2.38.0 | — |
| OpenAI API key | Agent LLM calls | Y | via OPENAI_API_KEY env var | — |

**Missing dependencies with no fallback:**
- **FastAPI**: Critical for SSE endpoints and REST API. Install via `uv pip install fastapi`.
- **uvicorn**: Critical for running the ASGI server. Install via `uv pip install uvicorn`.

**Missing dependencies with fallback:**
- None. All other required dependencies are already installed or are frontend packages managed by pnpm.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.3 + pytest-asyncio 1.4.0 (backend) / vitest (frontend, built into Vite) |
| Config file | pyproject.toml (backend pytest config) / vitest.config.ts (frontend, Wave 0) |
| Quick run command | `pytest tests/api/ -x -q` (backend) / `pnpm --dir frontend test --run` (frontend) |
| Full suite command | `pytest tests/ -x -q` (backend) / `pnpm --dir frontend test` (frontend) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| OBS-02 | SSE endpoint streams events for session | integration | `pytest tests/api/test_sse.py::test_stream_events -x` | No — Wave 0 |
| OBS-02 | SSE endpoint filters by session_id | integration | `pytest tests/api/test_sse.py::test_stream_session_filter -x` | No — Wave 0 |
| OBS-02 | SSE endpoint handles client disconnect | integration | `pytest tests/api/test_sse.py::test_stream_disconnect -x` | No — Wave 0 |
| OBS-05 | GET /api/sessions returns session list | integration | `pytest tests/api/test_sessions.py::test_list_sessions -x` | No — Wave 0 |
| OBS-05 | GET /api/sessions/{id} returns session events | integration | `pytest tests/api/test_sessions.py::test_get_session -x` | No — Wave 0 |
| OBS-05 | DELETE /api/sessions/{id} removes session | integration | `pytest tests/api/test_sessions.py::test_delete_session -x` | No — Wave 0 |
| BIZ-02 | POST /api/sessions/start spawns agent | integration | `pytest tests/api/test_control.py::test_start_session -x` | No — Wave 0 |
| BIZ-02 | POST /api/sessions/{id}/confirm responds to guard | integration | `pytest tests/api/test_control.py::test_confirm_command -x` | No — Wave 0 |
| OBS-03 | Frontend renders three-panel layout | smoke | `pnpm --dir frontend test --run` | No — Wave 0 |
| OBS-04 | Token usage displays in frontend | unit | `pnpm --dir frontend test --run` | No — Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/api/ -x -q` (backend API tests, < 30s)
- **Per wave merge:** `pytest tests/ -x -q` (full backend suite) + `pnpm --dir frontend test` (frontend)
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/api/` directory — does not exist yet, needs creation
- [ ] `tests/api/test_sse.py` — SSE endpoint tests
- [ ] `tests/api/test_sessions.py` — Session CRUD endpoint tests
- [ ] `tests/api/test_control.py` — Agent control endpoint tests
- [ ] `tests/api/conftest.py` — Shared fixtures (EventBus, test session, FastAPI TestClient)
- [ ] `frontend/vitest.config.ts` — Vitest configuration
- [ ] `frontend/src/__tests__/` — Frontend component tests
- [ ] Backend: Install `httpx` (already installed 0.28.1) for `TestClient` — or use `fastapi.testclient.TestClient`

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | No auth for v1 (single-user local tool). Deferred to v2. |
| V3 Session Management | No | SSE is connection-level, not session-level auth. |
| V4 Access Control | No | Single-user local deployment. No multi-tenancy. |
| V5 Input Validation | Yes | FastAPI + Pydantic auto-validates all request bodies and path parameters. SSE event data validated by existing Pydantic schemas. Confirmation POST validates `confirmation_id` exists before calling `PermissionGuard.respond()`. |
| V6 Cryptography | No | No crypto operations in this phase. OPENAI_API_KEY stored in env (existing). |
| V7 Error Handling | Yes | API errors return structured JSON (never stack traces). SSE `error` events already contain structured Error objects from EventBus. |

### Known Threat Patterns for FastAPI + React SPA

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| XSS via tool result content | Information Disclosure | Tool results are user-controlled (file contents, command output). Render as text, never as HTML. Use React's default escaping. Monospace display only. |
| CSRF on confirmation endpoint | Tampering | Same-origin CORS policy (`allow_origins=["http://localhost:..."])`. For local deployment, CSRF risk is minimal. If deployed to network, add CSRF token. |
| Path traversal in session ID | Tampering | FastAPI path parameter validation. Session ID is a UUID — validate format. JSONL file path constructed with `Path(log_dir) / f"{date_str}_{session_id}.jsonl"`. Use `Path` to prevent traversal. |
| Information leak via SSE replay | Information Disclosure | Cross-session data leak: SSE bridge MUST filter replay by `session_id`. Without filtering, `bus.replay()` returns all events from all sessions. |
| DoS via session creation flood | Denial of Service | No rate limiting on `/api/sessions/start`. For local tool, acceptable. If exposed to network, add `RateLimitGuard` (already exists in Phase 4). |
| Large JSONL file read | Denial of Service | `/api/sessions/{id}` reads entire JSONL into memory. For very large sessions, add pagination or streaming response. Acceptable for v1 (sessions typically < 50 steps, ~200KB). |

## Sources

### Primary (HIGH confidence)
- [Context7 /fastapi/fastapi] — SSE streaming, ServerSentEvent, EventSourceResponse, StaticFiles, CORS middleware
- [Context7 /shadcn-ui/ui] — CLI v4 init for Vite, component list
- [Context7 /pmndrs/zustand] — v5 create() API, persist middleware, slices pattern
- [Context7 /websites/tanstack_query_v5] — setQueryData, mutation updates, query invalidation
- [Context7 /vitejs/vite] — server.proxy configuration, dev server options
- [npm registry] — Verified versions: react 19.2.6, vite 8.0.14, tailwindcss 4.3.0, @tanstack/react-query 5.100.14, zustand 5.0.14, recharts 3.8.1
- [Existing codebase] — EventBus (bus.py), event schemas (schemas.py, 22 types), CLI renderer (cli_renderer.py), JSONL logger (jsonl_logger.py), Session (context.py), main.py (run_session orchestration)
- [05-UI-SPEC.md] — Complete UI design contract (layout, colors, typography, spacing, interactions, copywriting)
- [05-CONTEXT.md] — Locked decisions D-01 through D-06, Claude's discretion areas
- [CLAUDE.md] — Technology stack recommendations, version pinning, What NOT to Use

### Secondary (MEDIUM confidence)
- [MDN EventSource API] — Reconnection behavior, event types, `retry` field — training knowledge, standard API
- [WebSearch: react-use-sse-event] — npm package for SSE hooks; opted for custom hook approach (simpler, no dependency)

### Tertiary (LOW confidence)
- None — all claims verified or explicitly flagged as assumptions.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — All versions verified against npm registry. FastAPI version from CLAUDE.md (project authority). shadcn/ui CLI v4 confirmed via Context7.
- Architecture: HIGH — SSE bridge pattern verified via Context7 FastAPI docs. EventBus consumer pattern already proven in existing CLI/JSONL consumers. React patterns verified via Context7 for React Query and Zustand.
- Pitfalls: MEDIUM-HIGH — Pitfalls derived from existing codebase patterns (EventBus backpressure is a known issue from Phase 1), Context7 docs (SPA fallback, CORS), and standard React/SSE patterns (re-render storms, proxy buffering). Two pitfalls are ASSUMED (proxy buffering, confirmation timeout) and flagged for verification.

**Research date:** 2026-05-29
**Valid until:** 2026-06-29 (30 days — stable stack, no fast-moving dependencies)

**Environment:** Linux (WSL2), Node.js 24.15.0, Python 3.13.13, npm 11.12.1, pnpm available, FastAPI NOT installed (needs `uv pip install fastapi uvicorn`)
