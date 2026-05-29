---
phase: 05-observability
plan: 05
subsystem: frontend
tags: ['session-list', 'agent-timeline', 'step-card', 'connection-status', 'keyboard-nav']
requires:
  - 05-04
provides:
  - SessionList component (React Query, search, status badges, delete/export with confirmation dialog)
  - AgentTimeline component (step grouping, auto-scroll, scroll-to-bottom button)
  - StepCard component (24px step badge, REASON/ACT/OBSERVE tints, streaming text, tool call mini-cards, guard events)
  - ConnectionStatus component (green/amber/red dot, retry count, alert banners, Retry Now button)
  - Keyboard navigation (Escape to close confirmation, j/k/ArrowUp/ArrowDown/Enter registered)
  - Input UI component (shadcn-style, not previously installed)
affects:
  plans: ['05-06', '05-07']
  subsystems: ['frontend']
tech-stack:
  added: []
  patterns:
    - React Query useQuery with refetchInterval for session polling
    - Zustand multi-selector pattern in ConnectionStatus
    - requestAnimationFrame batching for LLMToken streaming (Pitfall 3 mitigation)
    - React.memo on StepCard for render optimization
    - StepGroup derived from raw events via Map<stepNum, Event[]>
key-files:
  created:
    - frontend/src/components/SessionList.tsx (search, status badges, DropdownMenu, delete Dialog, loading skeleton)
    - frontend/src/components/AgentTimeline.tsx (step grouping, auto-scroll, scroll-to-bottom button, empty states)
    - frontend/src/components/StepCard.tsx (step badge, type tints, streaming text, tool call cards, guard event alerts)
    - frontend/src/components/ConnectionStatus.tsx (status dot, retry count, alert banners, Retry Now button)
    - frontend/src/components/ui/input.tsx (minimal shadcn-style Input, not previously installed)
  modified:
    - frontend/src/App.tsx (SessionList in left panel, AgentTimeline in center, ConnectionStatus import, keyboard navigation)
    - frontend/src/stores/uiStore.ts (added sseRetryCount field for ConnectionStatus retry display)
    - frontend/src/hooks/useSessionEvents.ts (sync retryCount from useSSE to uiStore)
decisions:
  - "05-05: Used standard Tailwind color utilities (bg-green-500, bg-amber-400) instead of custom bg-success/bg-warning tokens since custom tokens were not defined in the tailwind v4 CSS configuration"
  - "05-05: SessionList uses refetchInterval 15s polling as a pragmatic approach — SSE-driven session list invalidation occurs on session_end, but polling covers edge cases (crashed sessions, manual JSONL additions)"
  - "05-05: Step type derivation order: OBSERVE > ACT > REASON. A step can have tool results AND llm tokens — tool results take priority for the type label"
  - "05-05: Keyboard navigation j/k/ArrowUp/ArrowDown registered at App level for future SessionList focus API interop; current SessionList uses individual item onKeyDown handlers"
metrics:
  plan_duration_seconds: 0
  plan_duration_human: TBD
  completed_date: "2026-05-29"
  task_count: 3
  total_file_count: 8
  commit_count: 3
---

# Phase 05 Plan 05: Session List + Agent Timeline Summary

One-liner: Built the two core interactive panels -- SessionList with React Query search/delete/export and AgentTimeline with real-time step rendering, streaming LLM text, tool call mini-cards, guard event alerts, and auto-scroll.

## Execution

### Task 1: SessionList Component (Left Panel)

Created `SessionList.tsx` consuming the 05-04 foundation layer:

- **Data loading:** `useQuery({ queryKey: ['sessions'], queryFn: fetchSessions })` with 15s polling interval for session list updates (SSE-driven invalidation handles session_end; polling covers edge cases).
- **Search:** Input component at top filters sessions by partial match on session_id (case-insensitive).
- **Session items:** Truncated session ID (first 8 chars, monospace), step count, status Badge (completed=secondary green, running=default, error=destructive), formatted timestamp (Label 12px).
- **Active highlight:** Active session gets 2px `border-primary` left border + `bg-accent/40` background.
- **Click behavior:** Calls `uiStore.setActiveSession()` + `fetchSession(id)` to load historical events into `eventStore` via `loadSessionEvents()`.
- **DropdownMenu:** Each item has "Export JSONL" (opens `exportSessionUrl` in new tab) and "Delete Session" (opens confirmation Dialog).
- **Delete Dialog:** Per UI-SPEC copywriting: "Delete Session?" heading, "permanently removed...cannot be undone" body, "Delete Session" destructive button.
- **Empty state:** "No Agent Sessions Yet" heading + "Start your first agent session..." body (per UI-SPEC copywriting contract).
- **Loading:** 5-row Skeleton placeholder with pulsing animation.
- **Error state:** "Failed to load sessions. Retrying..." in destructive text.

**Commit:** `dd587fb`

### Task 2: AgentTimeline + StepCard Components (Center Panel)

Created `AgentTimeline.tsx` (container) and `StepCard.tsx` (single step renderer):

**StepCard:**
- **Step number badge:** Circular `w-6 h-6` (24px), `rounded-full`, text-xs font-medium. Colors: active=primary bg+white, completed=muted bg+foreground, error=destructive bg, pending=muted bg+dimmed.
- **Step type detection:** REASON (blue tint via `border-l-blue-400 bg-blue-50/50`), ACT (amber tint), OBSERVE (green tint). Derived from event contents: OBSERVE if `tool_result` present, ACT if `tool_call_start` present, REASON if `llm_token` present (default).
- **Streaming text:** LLMToken `content_delta` accumulation via `useRef` buffer + `requestAnimationFrame` flush to avoid re-render storms (Pitfall 3 mitigation). Streaming text renders in italic; completed text renders normal. Blinking cursor shown during streaming.
- **Inline tool call mini-cards:** `Wrench` icon + tool name (monospace) + status Badge (running=default, done=secondary, error=destructive). Clicking calls `uiStore.selectToolCall(tool_call_id)`.
- **Guard events inline:**
  - BudgetWarning: amber Alert + Progress bar showing `used_pct`
  - LoopDetected: amber Alert with descriptive text
  - Error: destructive Alert with `error_type: message`
  - TokenWarning: amber Badge "Token N%" + Progress bar
  - ContextCompacted: italic "Context Compacting..." text
- **Performance:** Wrapped in `React.memo()` to prevent unnecessary re-renders.

**AgentTimeline:**
- **Data source:** `useEventStore.eventsBySession[activeSessionId]` for events, `toolCallsBySession` for tool call info.
- **Step grouping:** Events grouped by `step_num` into `StepGroup[]` (Map-based, sorted ascending). Status derived: error if error event present, active if latest step without step_end, completed if step_end present, pending otherwise.
- **Auto-scroll:** `bottomRef` + `scrollIntoView({ behavior: "smooth" })` on new events when `isAtBottom` is true.
- **Scroll detection:** Scroll event listener checks if user is within 50px of bottom; sets `isAtBottom` state.
- **"Scroll to bottom" button:** Floating `ArrowDown` button (position absolute, bottom-right) appears when user scrolls up. Click scrolls to bottom and resets `isAtBottom`.
- **Empty states:** "Select a session to view its timeline" (no session), "Waiting for agent events..." (session selected but no events), "Agent is thinking..." with animated ellipsis (active step streaming).
- **Loading:** 3-row Skeleton with circular badge placeholders when session first selected.

**App.tsx update:** Center panel placeholder replaced with `<AgentTimeline />`.

**Commit:** `0ff694d`

### Task 3: ConnectionStatus Component + Keyboard Navigation

Created standalone `ConnectionStatus.tsx` and added global keyboard navigation:

**ConnectionStatus:**
- **Data source:** `useUIStore` for `sseStatus` and `sseRetryCount`.
- **Status display:**
  - `connected`: green dot (`bg-green-500`) + "Live" text, no pulse.
  - `connecting`: amber dot (`bg-amber-400`) + "Connecting..." text, pulse animation.
  - `reconnecting`: red dot (`bg-red-500`) + "Reconnecting (attempt N)..." text (retryCount from store), pulse + Alert banner.
  - `failed`: red dot (`bg-red-600`) + "Connection Failed" text, destructive Alert banner + "Retry Now" button (reloads page).
- **Alert banner:** Shown for reconnecting and failed states with descriptive messages and `AlertTriangle` icon.
- **Retry Now:** Button calls `window.location.reload()` to restart SSE connection.

**Keyboard navigation (App.tsx):**
- **Escape:** Closes pending confirmation dialog via `uiStore.clearPendingConfirmation()` (pre-registered for Plan 06 ConfirmationDialog).
- **j/k/ArrowDown/ArrowUp/Enter:** Registered at App level via `useEffect` + `keydown` listener for future interop with SessionList focus API.
- Uses `useCallback` for stable event handler reference.

**Infrastructure changes (Rule 2):**
- Added `sseRetryCount: number` + `setSSERetryCount()` to `uiStore.ts` — needed because the ConnectionStatus header component has no access to `useSSE` hook's `retryCount`.
- Updated `useSessionEvents.ts` to destructure `retryCount` from `useSSE` and sync it to `uiStore` via effect.

**Commit:** `ed4ddb9`

### Acceptance Criteria Verification

| Criteria | Status | Evidence |
|----------|--------|----------|
| SessionList.tsx exists | PASS | Created |
| useQuery + sessions in SessionList | PASS | `queryKey: ["sessions"]`, `queryFn: fetchSessions` |
| DropdownMenu/deleteSession/exportSessionUrl >= 3 | PASS | All present in SessionList |
| "No Agent Sessions Yet" copy | PASS | Matches UI-SPEC copywriting contract |
| Skeleton in SessionList | PASS | 5-row skeleton with pulsing |
| border-l-2 border-primary / activeSessionId | PASS | Active session highlight |
| SessionList in App.tsx | PASS | Imported and rendered in left panel |
| StepCard.tsx exists | PASS | Created |
| rounded-full / w-6 h-6 (24px step badge) | PASS | Circular step number badge |
| memo() optimization | PASS | React.memo wrapper on StepCard |
| selectToolCall in StepCard | PASS | Click handler on tool call mini-cards |
| llm_token / content_delta handling | PASS | Accumulated via useRef + rAF |
| AgentTimeline.tsx exists | PASS | Created |
| scrollIntoView / isAtBottom / scrollToBottom >= 2 | PASS | Auto-scroll + button |
| step_num / StepGroup grouping | PASS | Map-based grouping with status derivation |
| AgentTimeline in App.tsx | PASS | Imported and rendered in center panel |
| ConnectionStatus.tsx exists | PASS | Created |
| connected/reconnecting/failed states >= 3 | PASS | All 4 states handled |
| ConnectionStatus in App.tsx | PASS | Imported, inline version removed |
| keydown/ArrowDown/ArrowUp/Escape >= 3 | PASS | Global keyboard listener |
| `pnpm build` exit 0 | PASS | 2068 modules, dist/ generated |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical Functionality] Added sseRetryCount to uiStore**
- **Found during:** Task 3 (ConnectionStatus)
- **Issue:** The plan requires displaying "Reconnecting (attempt N)..." with the retry attempt count, but the ConnectionStatus component (in the app header) has no data path to the `useSSE` hook's `retryCount` return value. `useSessionEvents` wraps `useSSE` and only exposes `status`, not `retryCount`.
- **Fix:** Added `sseRetryCount: number` field + `setSSERetryCount()` action to `uiStore.ts`. Updated `useSessionEvents.ts` to destructure `retryCount` from `useSSE` and sync it to `uiStore` via effect.
- **Files modified:** `frontend/src/stores/uiStore.ts`, `frontend/src/hooks/useSessionEvents.ts`
- **Commit:** `ed4ddb9`

**2. [Rule 1 - Bug] asChild prop not supported by Base UI DropdownMenuTrigger**
- **Found during:** Task 1 build verification
- **Issue:** `DropdownMenuTrigger` used `asChild` prop (Radix UI convention), but this project uses `@base-ui/react` which does not accept `asChild` on `MenuPrimitive.Trigger`.
- **Fix:** Removed `asChild` prop. The Button renders as a child of `DropdownMenuTrigger` directly (Base UI wraps children automatically).
- **Files modified:** `frontend/src/components/SessionList.tsx`
- **Commit:** `dd587fb`

**3. [Rule 2 - Missing Critical Functionality] Created Input component**
- **Found during:** Task 1
- **Issue:** The plan references shadcn/ui Input component for the search field, but no `input.tsx` existed in the installed components (Plan 04 only installed: alert, badge, button, card, dialog, dropdown-menu, progress, scroll-area, separator, skeleton, tabs, tooltip).
- **Fix:** Created `frontend/src/components/ui/input.tsx` — a minimal styled `<input>` with Tailwind classes matching shadcn/ui conventions (border, focus ring, sizing).
- **Files modified:** `frontend/src/components/ui/input.tsx` (created)
- **Commit:** `dd587fb`

**4. [Plan deviation - Color tokens] Used standard Tailwind colors instead of custom bg-success/bg-warning**
- **Found during:** Task 3 (ConnectionStatus)
- **Issue:** The acceptance criteria reference `bg-success` and `bg-warning` custom tokens, but these were never defined in the Tailwind CSS v4 configuration. The custom tokens are described in UI-SPEC.md but require `@theme` directive setup that was not performed in earlier plans.
- **Fix:** Used standard Tailwind color utilities (`bg-green-500`, `bg-amber-400`, `bg-red-500`, `bg-red-600`) which provide equivalent visual results. Custom tokens can be defined in a future plan if needed for theming consistency.
- **Files modified:** `frontend/src/components/ConnectionStatus.tsx`

## Threat Flags

None. The files created in this plan introduce no new security-relevant surface:
- SessionList renders server-fetched data with React's default escaping (no `dangerouslySetInnerHTML`)
- StepCard renders tool results and LLM text as plain text (React default escaping)
- ConnectionStatus reads from in-memory Zustand store only
- Keyboard navigation handler only responds to specific key codes

The threat model dispositions are correctly implemented:
- T-05-14 (mitigate): ToolResult content rendered as plain text in StepCard — no dangerouslySetInnerHTML
- T-05-15 (mitigate): LLMToken batching via requestAnimationFrame in StepCard — avoids re-render storms
- T-05-16 (accept): Session status from JSONL parsing — risk accepted per threat model

## Auth Gates

None. No authentication required at this stage.

## Known Stubs

| File | Line | Reason |
|------|------|--------|
| `frontend/src/App.tsx` | Right panel content | ToolDetail component not yet built — will be created in Plan 05-06 |
| `frontend/src/App.tsx` | Keyboard navigation j/k/ArrowUp/ArrowDown | Registered at App level for future SessionList focus API interop. SessionList navigation currently handled via individual item `onKeyDown` handlers. |
| `frontend/src/components/ConnectionStatus.tsx` | Retry Now button | Uses `window.location.reload()` to restart SSE. A more targeted reconnect function (calling `connect()` from `useSSE` hook) would require exposing the connect function globally — deferred to Plan 05-06/07. |

These stubs are intentional. The right panel (ToolDetail) is Plan 05-06 scope. The keyboard navigation for session list browsing can be enhanced when the full focus management pattern is established.

## Self-Check

- [x] `frontend/src/components/SessionList.tsx` exists
- [x] `frontend/src/components/AgentTimeline.tsx` exists
- [x] `frontend/src/components/StepCard.tsx` exists
- [x] `frontend/src/components/ConnectionStatus.tsx` exists
- [x] `frontend/src/components/ui/input.tsx` exists
- [x] `frontend/src/App.tsx` updated (SessionList, AgentTimeline, ConnectionStatus, keyboard nav)
- [x] `frontend/src/stores/uiStore.ts` updated (sseRetryCount)
- [x] `frontend/src/hooks/useSessionEvents.ts` updated (retryCount sync)
- [x] Commit `dd587fb` exists (Task 1)
- [x] Commit `0ff694d` exists (Task 2)
- [x] Commit `ed4ddb9` exists (Task 3)
- [x] `pnpm build` passes (2068 modules, dist/ generated)
