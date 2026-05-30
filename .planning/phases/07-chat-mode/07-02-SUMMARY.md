---
phase: 07-chat-mode
plan: 02
subsystem: frontend-chat-ui
tags:
  - chat-ui
  - message-bubbles
  - event-grouping
  - round-tracking
dependency-graph:
  requires:
    - "07-01: 后端多轮 FINISH_WAIT + REST API"
  provides:
    - "Chat UI with SSE-driven message rendering"
  affects:
    - "App.tsx: complete rewrite from dashboard to chat"
    - "SessionList.tsx: onSelect prop for history sidebar"
tech-stack:
  added: []
  patterns:
    - "Round grouping useMemo in App.tsx: user_message/round_end as round boundaries"
    - "Inline expandable tool call cards (no right panel)"
    - "Accumulated text from llm_token events across step boundaries"
key-files:
  created: []
  modified:
    - "frontend/src/lib/api.ts — sendMessage, stopSession"
    - "frontend/src/lib/eventTypes.ts — RoundInfo interface"
    - "frontend/src/stores/uiStore.ts — messageInput, pendingSessionStart"
    - "frontend/src/stores/eventStore.ts — roundsBySession with update/rebuild"
    - "frontend/src/App.tsx — full rewrite to Chat layout"
    - "frontend/src/components/SessionList.tsx — onSelect prop"
decisions:
  - "Message bubbles: user right-aligned (primary color), agent left-aligned (card border)"
  - "Tool calls expandable inline (no separate right panel for ToolDetail)"
  - "Round boundary: user_message starts new round, round_end closes it"
  - "Start screen shown when no active session (first message prompt)"
metrics:
  duration: null
  completed_date: "2026-05-30"
---

# Phase 7 Plan 2: Frontend Chat UI — Summary

Refactored the loopAI frontend from a 3-panel observability dashboard to a pure conversational chat interface. Users now interact via "send message -> read reply" instead of "fill form -> view panels". The chat layout consists of a title bar with history button, a message stream with round-grouped bubbles, and a bottom input bar.

## Tasks

### Task 1: API 函数 + Store 扩展 + Event 类型更新

| Type | Commit | Hash |
|------|--------|------|
| `feat` | add sendMessage/stopSession API, RoundInfo type, store round tracking | `0d47898` |

Changes:
- `api.ts`: Added `sendMessage` (POST /api/sessions/{id}/messages) and `stopSession` (POST /api/sessions/{id}/stop) functions
- `eventTypes.ts`: Added `RoundInfo` interface and export (labels already present from 07-01)
- `uiStore.ts`: Added `messageInput`, `pendingSessionStart` state and `setMessageInput`/`setPendingSessionStart` setters
- `eventStore.ts`: Added `roundsBySession` state, `updateRounds` helper (user_message = new round, round_end = close round), `getSessionRounds` method, `clearSession`/`loadSessionEvents` updated to include rounds

### Task 2: 重构 App.tsx 为 Chat 布局 + 消息气泡组件 + 输入框组件

| Type | Commit | Hash |
|------|--------|------|
| `feat` | refactor App.tsx to Chat layout with message bubbles and input bar | `8e6add6` |

Changes:
- Completely rewrote `App.tsx` from 3-panel layout to chat interface:
  - **Header**: Title "loopAI" + History button + ConnectionStatus + New Chat button
  - **Start screen**: Centered prompt for first message when no session active
  - **Message stream**: Round-grouped display with user messages (right-aligned, primary bg) and agent responses (left-aligned, card border + Markdown rendering + expandable tool calls + token info)
  - **Input bar**: Textarea (Enter to send, Shift+Enter newline) + Send button
  - **History sidebar**: Overlay panel with SessionList when history button clicked
  - **Keyboard**: Escape closes confirmation dialog
  - `SessionList.tsx`: Added optional `onSelect` prop for history sidebar integration

## Deviations from Plan

### Rule 3 - Auto-fix: Path context issue with git worktree

**Found during:** Task 1 commit
**Issue:** Initial `Edit`/`Write` operations used absolute path `/home/atis/HE/loopAI/frontend/...` (main repo) instead of `/home/atis/HE/loopAI/.claude/worktrees/agent-aa0134adcc6e5b4c8/frontend/...` (worktree). This caused the first commit (`eae99ea`) to land on the `main` branch instead of the worktree branch.
**Fix:** Copied modified files from main repo to worktree, re-committed on the worktree branch (`0d47898`). The main branch commit is local-only and will be resolved during orchestrator merge.
**Files affected:** `api.ts`, `eventTypes.ts`, `uiStore.ts`, `eventStore.ts`
**Commit:** `0d47898`

## Verification

| Check | Result |
|-------|--------|
| sendMessage in api.ts | PASS (1 match) |
| stopSession in api.ts | PASS (1 match) |
| handleSendMessage in App.tsx | PASS (3 matches) |
| ReactMarkdown in App.tsx | PASS (3 matches) |
| rounds.map in App.tsx | PASS (1 match) |
| rounded-2xl in App.tsx | PASS (3 matches) |
| TypeScript noEmit | PASS (0 errors) |

## Key Links

- App.tsx uses `useSessionEvents(activeSessionId)` for SSE connection
- App.tsx imports `sendMessage` from `api.ts` for chat input submission
- Round grouping in App.tsx uses `eventsBySession` and `toolCallsBySession` from eventStore
- History sidebar passes `onSelect` to SessionList which sets active session and loads events
- ConfirmationDialog overlays chat without modification (uses `pendingConfirmation` from uiStore)

## Known Stubs

None. All data flows are wired: SSE events → eventStore → App.tsx round rendering → message bubbles.

## Threat Surface Check

No new threat surface introduced beyond what is covered by the threat model (T-07-05 Markdown rendering via ReactMarkdown, T-07-06 SSE reconnection, T-07-07 rate-limiting by awaiting backend response).
