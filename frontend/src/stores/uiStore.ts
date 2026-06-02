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
import type {
  ConfirmationRequiredEvent,
  ToolCreationRequestedEvent,
  ToolCreationTestResultEvent,
  SSEStatus,
} from "@/lib/eventTypes";

// ── State interface ───────────────────────────────────────────────────

export interface UIState {
  activeSessionId: string | null;
  selectedToolCallId: string | null;
  pendingConfirmation: ConfirmationRequiredEvent | null;
  pendingToolCreation: ToolCreationRequestedEvent | null;
  toolCreationTestResult: ToolCreationTestResultEvent | null;
  toolCreationApproveLoading: boolean;
  toolCreationRejectLoading: boolean;
  toolCreationError: string | null;
  sseStatus: SSEStatus;
  sseRetryCount: number;
  messageInput: string;
  pendingSessionStart: boolean;
  toolPanelOpen: boolean;

  setActiveSession: (id: string | null) => void;
  selectToolCall: (id: string | null) => void;
  setPendingConfirmation: (event: ConfirmationRequiredEvent | null) => void;
  clearPendingConfirmation: () => void;
  setPendingToolCreation: (event: ToolCreationRequestedEvent | null) => void;
  setToolCreationTestResult: (result: ToolCreationTestResultEvent | null) => void;
  setToolCreationApproveLoading: (v: boolean) => void;
  setToolCreationRejectLoading: (v: boolean) => void;
  setToolCreationError: (msg: string | null) => void;
  clearPendingToolCreation: () => void;
  setSSEStatus: (status: SSEStatus) => void;
  setSSERetryCount: (count: number) => void;
  setMessageInput: (text: string) => void;
  setPendingSessionStart: (v: boolean) => void;
  setToolPanelOpen: (open: boolean) => void;

// ── Store ─────────────────────────────────────────────────────────────

export const useUIStore = create<UIState>()((set) => ({
  activeSessionId: null,
  selectedToolCallId: null,
  pendingConfirmation: null,
  pendingToolCreation: null,
  toolCreationTestResult: null,
  toolCreationApproveLoading: false,
  toolCreationRejectLoading: false,
  toolCreationError: null,
  sseStatus: "connecting",
  sseRetryCount: 0,
  messageInput: "",
  pendingSessionStart: false,
  toolPanelOpen: false,

  setActiveSession: (id: string | null) =>
    set({ activeSessionId: id, selectedToolCallId: null }),

  selectToolCall: (id: string | null) =>
    set({ selectedToolCallId: id }),

  setPendingConfirmation: (event: ConfirmationRequiredEvent | null) =>
    set({ pendingConfirmation: event }),

  clearPendingConfirmation: () =>
    set({ pendingConfirmation: null }),

  setPendingToolCreation: (event: ToolCreationRequestedEvent | null) =>
    set({ pendingToolCreation: event, toolCreationTestResult: null, toolCreationError: null }),

  setToolCreationTestResult: (result: ToolCreationTestResultEvent | null) =>
    set({ toolCreationTestResult: result }),

  setToolCreationApproveLoading: (v: boolean) =>
    set({ toolCreationApproveLoading: v }),

  setToolCreationRejectLoading: (v: boolean) =>
    set({ toolCreationRejectLoading: v }),

  setToolCreationError: (msg: string | null) =>
    set({ toolCreationError: msg }),

  clearPendingToolCreation: () =>
    set({
      pendingToolCreation: null,
      toolCreationTestResult: null,
      toolCreationApproveLoading: false,
      toolCreationRejectLoading: false,
      toolCreationError: null,
    }),

  setSSEStatus: (status: SSEStatus) =>
    set({ sseStatus: status }),

  setSSERetryCount: (count: number) =>
    set({ sseRetryCount: count }),

  setMessageInput: (text: string) =>
    set({ messageInput: text }),

  setPendingSessionStart: (v: boolean) =>
    set({ pendingSessionStart: v }),

  setToolPanelOpen: (open: boolean) =>
    set({ toolPanelOpen: open }),
}));
