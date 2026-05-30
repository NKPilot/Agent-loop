/**
 * Zustand v5 store for client-side UI state.
 *
 * Manages UI-only state that does not belong in React Query's server-state
 * cache: active session, selected tool call, pending confirmation dialog,
 * and SSE connection status.
 *
 * Implements Pattern 4 from RESEARCH.md.
 */

import { create } from "zustand";
import type { ConfirmationRequiredEvent, SSEStatus } from "@/lib/eventTypes";

// ── State interface ───────────────────────────────────────────────────

export interface UIState {
  activeSessionId: string | null;
  selectedToolCallId: string | null;
  pendingConfirmation: ConfirmationRequiredEvent | null;
  sseStatus: SSEStatus;
  sseRetryCount: number;
  messageInput: string;
  pendingSessionStart: boolean;

  setActiveSession: (id: string | null) => void;
  selectToolCall: (id: string | null) => void;
  setPendingConfirmation: (event: ConfirmationRequiredEvent | null) => void;
  clearPendingConfirmation: () => void;
  setSSEStatus: (status: SSEStatus) => void;
  setSSERetryCount: (count: number) => void;
  setMessageInput: (text: string) => void;
  setPendingSessionStart: (v: boolean) => void;
}

// ── Store ─────────────────────────────────────────────────────────────

export const useUIStore = create<UIState>()((set) => ({
  activeSessionId: null,
  selectedToolCallId: null,
  pendingConfirmation: null,
  sseStatus: "connecting",
  sseRetryCount: 0,
  messageInput: "",
  pendingSessionStart: false,

  setActiveSession: (id: string | null) =>
    set({ activeSessionId: id, selectedToolCallId: null }),

  selectToolCall: (id: string | null) =>
    set({ selectedToolCallId: id }),

  setPendingConfirmation: (event: ConfirmationRequiredEvent | null) =>
    set({ pendingConfirmation: event }),

  clearPendingConfirmation: () =>
    set({ pendingConfirmation: null }),

  setSSEStatus: (status: SSEStatus) =>
    set({ sseStatus: status }),

  setSSERetryCount: (count: number) =>
    set({ sseRetryCount: count }),

  setMessageInput: (text: string) =>
    set({ messageInput: text }),

  setPendingSessionStart: (v: boolean) =>
    set({ pendingSessionStart: v }),
}));
