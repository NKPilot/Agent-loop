---
phase: 05-observability
plan: 04
subsystem: frontend
tags: ['event-types', 'sse-hook', 'zustand', 'react-query', 'three-panel-layout', 'foundation']
requires:
  - 05-03
provides:
  - Three-panel layout shell (260px left / flex-1 center / 360px right)
  - 22 event TypeScript interfaces mirroring Python schemas.py
  - REST API client functions (fetchSessions, fetchSession, startSession, confirmCommand, deleteSession)
  - Token/cost calculation utilities (gpt-4o-mini default rates)
  - useSSE hook with exponential backoff reconnect (max 30s per D-04)
  - Zustand uiStore (activeSession, selectedToolCall, pendingConfirmation, sseStatus)
  - Zustand eventStore (event accumulation, tool call tracking per session)
  - useSessionEvents bridge hook (SSE -> Zustand + React Query invalidation)
  - QueryClientProvider integration (staleTime 30s, retry 2)
  - Vite proxy /api -> localhost:8000 with changeOrigin
affects:
  plans: ['05-05', '05-06', '05-07']
  subsystems: ['frontend']
tech-stack:
  added: []
  patterns:
    - useSSE React hook with EventSource API + exponential backoff (Pattern 2)
    - Zustand v5 create<T>()() syntax for client state (Pattern 4)
    - React Query setQueryData/invalidateQueries for SSE-driven cache updates (Pattern 3)
    - Single onmessage handler for SSE dispatch (22 event types routed by event_type discriminator)
key-files:
  created:
    - frontend/src/lib/eventTypes.ts (22 discriminated event interfaces + Event union type)
    - frontend/src/lib/api.ts (6 REST client functions with fetch + error handling)
    - frontend/src/lib/costCalculator.ts (calculateCost, formatCost, formatTokens)
    - frontend/src/hooks/useSSE.ts (SSE connection management with exponential backoff)
    - frontend/src/hooks/useSessionEvents.ts (SSE -> Zustand + React Query bridge)
    - frontend/src/stores/uiStore.ts (Zustand v5: activeSessionId, selectedToolCallId, pendingConfirmation, sseStatus)
    - frontend/src/stores/eventStore.ts (Zustand v5: eventsBySession, toolCallsBySession)
  modified:
    - frontend/src/App.tsx (three-panel layout + SSE status indicator driven by uiStore)
    - frontend/vite.config.ts (proxy /api -> localhost:8000)
    - frontend/src/main.tsx (QueryClientProvider with staleTime 30s, retry 2)
    - frontend/pnpm-workspace.yaml (fixed msw allowBuilds pre-existing blocker)
decisions:
  - "05-04: SSEStatus type placed in eventTypes.ts as shared type consumed by useSSE hook, uiStore, App.tsx, and useSessionEvents"
  - "05-04: Single SSE onmessage handler dispatches events by event_type discriminator (not 22 addEventListener calls)"
  - "05-04: QueryClientProvider placed in main.tsx (not App.tsx) for clean provider hierarchy"
metrics:
  plan_duration_seconds: 273
  plan_duration_human: 4min 33s
  completed_date: "2026-05-29T15:33:04Z"
  task_count: 2
  total_file_count: 11
  commit_count: 2
---

# Phase 05 Plan 04: Foundation Layer Summary

One-liner: Built three-panel layout shell, 22 TypeScript event type interfaces, SSE connection hook with exponential backoff, Zustand stores, and React Query foundation on top of the 05-03 Vite scaffold.

## Execution

### Task 1: Three-Panel Layout Shell + Event Types + Vite Proxy

Created the foundational data types and layout structure:

- **eventTypes.ts:** 22 discriminated event interfaces (`StepStartEvent`, `StepEndEvent`, etc.) with `event_type` literal discriminators, `Event` union type, `EVENT_TYPE_MAP` for human-readable labels, and helper types (`TokenUsage`, `ToolCallInfo`, `CostRates`, `SSEStatus`).
- **api.ts:** 6 fetch-based REST client functions (`fetchSessions`, `fetchSession`, `startSession`, `confirmCommand`, `deleteSession`, `exportSessionUrl`) with `handleResponse` error wrapper for non-2xx responses.
- **costCalculator.ts:** `calculateCost` with gpt-4o-mini default rates ($0.003/$0.015 per 1K), `formatCost` (3 decimal places), `formatTokens` (thousands separator).
- **App.tsx:** Three-panel layout per UI-SPEC Layout Contract: 260px left (Session List), flex-1 center (Agent Timeline), 360px right (Tool Detail). Header with "loopAI -- Observability Dashboard" title (28px Display) and SSE status indicator placeholder. All copywriting matches UI-SPEC contract.
- **vite.config.ts:** Proxy `/api` -> `http://localhost:8000` with `changeOrigin: true`. No buffering middleware (SSE compatible per Pitfall 2).

**Commit:** `fccafbe`

### Task 2: useSSE Hook + Zustand Stores + React Query + Event Bridge

Built the state management and real-time data pipeline:

- **useSSE.ts:** Custom React hook wrapping native `EventSource` API. Single `onmessage` handler parsing JSON and calling `onEvent(eventType, data)`. Exponential backoff reconnection: `delay = min(1000 * 2^retries, maxBackoff)` with default `maxBackoff=30000` (30s per D-04). Returns `{ status: SSEStatus, retryCount: number }`.
- **uiStore.ts:** Zustand v5 store managing `activeSessionId`, `selectedToolCallId`, `pendingConfirmation` (ConfirmationRequiredEvent), and `sseStatus`. Actions: `setActiveSession`, `selectToolCall`, `setPendingConfirmation`, `clearPendingConfirmation`, `setSSEStatus`.
- **eventStore.ts:** Zustand v5 store with `eventsBySession: Record<string, Event[]>` and `toolCallsBySession: Record<string, ToolCallInfo[]>`. `appendEvent` updates tool call tracking: `tool_call_start` creates `ToolCallInfo` (status=running), `tool_call_done` updates `full_args`, `tool_result` updates `result`/`duration_ms`/status. `loadSessionEvents` bulk-loads historical events from REST API.
- **useSessionEvents.ts:** Bridge hook connecting SSE -> Zustand + React Query. Uses `useSSE` with URL `/api/sessions/{id}/stream`. On `session_end`: invalidates React Query `['sessions']` cache. On `confirmation_required`: sets pending confirmation in uiStore. Syncs SSE status to uiStore via effect.
- **main.tsx:** Wrapped app in `<QueryClientProvider>` with `staleTime: 30_000` and `retry: 2`.
- **App.tsx:** Replaced static SSE indicator with `ConnectionStatus` component driven by `useUIStore.sseStatus` (green/amber/red dot with pulse animation and label text).

**Commit:** `b93654d`

### Acceptance Criteria Verification

| Criteria | Status | Evidence |
|----------|--------|----------|
| 22+ event_type definitions in eventTypes.ts | PASS | 23 occurrences |
| 9+ key event names found | PASS | 19 occurrences |
| API client exports all 6 functions | PASS | fetchSessions, fetchSession, startSession, confirmCommand, deleteSession, exportSessionUrl |
| Cost calculator exports correct functions | PASS | calculateCost, formatCost, formatTokens |
| Three-panel layout with correct widths | PASS | w-[260px], flex-1, w-[360px] in App.tsx |
| UI copy present (No Agent Sessions Yet, Select a tool call, loopAI) | PASS | 3 matches |
| Vite proxy with changeOrigin | PASS | 1 occurrence |
| useSSE hook with EventSource | PASS | new EventSource present |
| Exponential backoff logic | PASS | Math.pow, exponential, backoff, retry >= 2 |
| maxBackoff 30000 | PASS | Default in hook signature |
| Zustand v5 create<T>()() syntax | PASS | create<UIState>() in both stores |
| UI store fields | PASS | activeSessionId, pendingConfirmation, selectedToolCallId |
| Event store actions | PASS | appendEvent, loadSessionEvents |
| useSessionEvents bridge dependencies | PASS | useSSE, useQueryClient, useEventStore |
| QueryClientProvider in tree | PASS | main.tsx |
| `pnpm tsc --noEmit` exit 0 | PASS | Clean |
| `pnpm build` exit 0 | PASS | 205 modules, dist/ generated |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking Issue] pnpm build failed due to unapproved msw build scripts**

- **Found during:** Pre-execution baseline verification
- **Issue:** `pnpm-workspace.yaml` had `allowBuilds.msw: "set this to true or false"` (a placeholder string, not a boolean). pnpm 11.4.0 treats this as unapproved and refuses to install/run scripts.
- **Fix:** Changed to `allowBuilds.msw: true` in `pnpm-workspace.yaml`
- **Files modified:** `frontend/pnpm-workspace.yaml`
- **Commit:** `fccafbe`

**2. [Rule 1 - Bug] SSEStatus type imported from wrong module**

- **Found during:** Task 2 build verification
- **Issue:** `SSEStatus` was defined in `useSSE.ts` but imported from `@/lib/eventTypes` in `App.tsx`, `useSessionEvents.ts`, and `uiStore.ts`. `tsc -b` (build mode) caught the missing export, while `tsc --noEmit` (check mode) did not.
- **Fix:** Moved `SSEStatus` type definition to `eventTypes.ts` and updated `useSSE.ts` to import it from there.
- **Files modified:** `frontend/src/lib/eventTypes.ts`, `frontend/src/hooks/useSSE.ts`
- **Commit:** `b93654d`

## Threat Flags

None. The files created in this plan introduce:
- Static TypeScript type definitions (eventTypes.ts) -- no runtime data exposure
- Client-side fetch wrappers (api.ts) -- use `response.ok` checking (mitigates T-05-12 per threat model)
- In-memory Zustand stores (uiStore.ts, eventStore.ts) -- no persistence to localStorage (mitigates T-05-10)
- SSE hook using native EventSource -- no custom headers (accepts T-05-11 per threat model)

The threat model dispositions (T-05-10 mitigate, T-05-11 accept, T-05-12 mitigate, T-05-13 accept) are all correctly implemented.

## Auth Gates

None. No authentication required at this stage.

## Known Stubs

| File | Line | Reason |
|------|------|--------|
| `frontend/src/App.tsx` | Panel body content | Three-panel layout has placeholder/empty-state text only. Actual SessionList, AgentTimeline, and ToolDetail components will be built in plans 05-05, 05-06, 05-07. |
| `frontend/src/hooks/useSessionEvents.ts` | Inline store write for confirmation | Uses `useUIStore.getState().setPendingConfirmation(data)` in event callback. This is intentional for the bridge pattern but will be refined when the ConfirmationDialog component is built. |

These stubs are intentional. The plan's objective is building the data pipeline and layout shell -- the panel components consuming these stores and hooks are built in subsequent plans.

## Self-Check

- [x] `frontend/src/lib/eventTypes.ts` exists
- [x] `frontend/src/lib/api.ts` exists
- [x] `frontend/src/lib/costCalculator.ts` exists
- [x] `frontend/src/hooks/useSSE.ts` exists
- [x] `frontend/src/hooks/useSessionEvents.ts` exists
- [x] `frontend/src/stores/uiStore.ts` exists
- [x] `frontend/src/stores/eventStore.ts` exists
- [x] `frontend/src/App.tsx` updated with three-panel layout
- [x] `frontend/src/main.tsx` updated with QueryClientProvider
- [x] `frontend/vite.config.ts` updated with proxy
- [x] Commit `fccafbe` exists in git log
- [x] Commit `b93654d` exists in git log
- [x] `pnpm tsc --noEmit` passes
- [x] `pnpm build` passes (205 modules, dist/ generated)
