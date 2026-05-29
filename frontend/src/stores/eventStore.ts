/**
 * Zustand v5 store for accumulated event data per session.
 *
 * Manages the streaming event log and tool call information indexed by
 * session_id. SSE events are appended in real-time; historical events
 * can be bulk-loaded from the REST API.
 */

import { create } from "zustand";
import type { Event, ToolCallInfo } from "@/lib/eventTypes";

// ── State interface ───────────────────────────────────────────────────

export interface EventStoreState {
  eventsBySession: Record<string, Event[]>;
  toolCallsBySession: Record<string, ToolCallInfo[]>;

  appendEvent: (sessionId: string, event: Event) => void;
  getSessionEvents: (sessionId: string) => Event[];
  getSessionToolCalls: (sessionId: string) => ToolCallInfo[];
  clearSession: (sessionId: string) => void;
  loadSessionEvents: (sessionId: string, events: Event[]) => void;
}

// ── Helpers ───────────────────────────────────────────────────────────

function updateToolCalls(
  toolCalls: ToolCallInfo[],
  event: Event
): ToolCallInfo[] {
  switch (event.event_type) {
    case "tool_call_start": {
      const existing = toolCalls.find(
        (tc) => tc.tool_call_id === event.tool_call_id
      );
      if (!existing) {
        return [
          ...toolCalls,
          {
            tool_name: event.tool_name,
            tool_call_id: event.tool_call_id,
            step_num: event.step_num,
            status: "running",
          },
        ];
      }
      return toolCalls;
    }

    case "tool_call_done": {
      return toolCalls.map((tc) =>
        tc.tool_call_id === event.tool_call_id
          ? { ...tc, full_args: event.full_args, status: "done" as const }
          : tc
      );
    }

    case "tool_result": {
      return toolCalls.map((tc) =>
        tc.tool_call_id === event.tool_call_id
          ? {
              ...tc,
              result: event.result,
              is_error: event.is_error,
              duration_ms: event.duration_ms,
              status: (event.is_error ? "error" : "done") as ToolCallInfo["status"],
            }
          : tc
      );
    }

    default:
      return toolCalls;
  }
}

// ── Store ─────────────────────────────────────────────────────────────

export const useEventStore = create<EventStoreState>()((set, get) => ({
  eventsBySession: {},
  toolCallsBySession: {},

  appendEvent: (sessionId: string, event: Event) =>
    set((state) => {
      const events = [...(state.eventsBySession[sessionId] ?? []), event];
      const toolCalls = updateToolCalls(
        state.toolCallsBySession[sessionId] ?? [],
        event
      );
      return {
        eventsBySession: { ...state.eventsBySession, [sessionId]: events },
        toolCallsBySession: {
          ...state.toolCallsBySession,
          [sessionId]: toolCalls,
        },
      };
    }),

  getSessionEvents: (sessionId: string) =>
    get().eventsBySession[sessionId] ?? [],

  getSessionToolCalls: (sessionId: string) =>
    get().toolCallsBySession[sessionId] ?? [],

  clearSession: (sessionId: string) =>
    set((state) => {
      const { [sessionId]: _, ...restEvents } = state.eventsBySession;
      const { [sessionId]: __, ...restToolCalls } = state.toolCallsBySession;
      return {
        eventsBySession: restEvents,
        toolCallsBySession: restToolCalls,
      };
    }),

  loadSessionEvents: (sessionId: string, events: Event[]) =>
    set((state) => {
      // Rebuild tool calls from the full event list
      const toolCalls: ToolCallInfo[] = [];
      for (const event of events) {
        const updated = updateToolCalls(toolCalls, event);
        // Replace in-place for efficiency
        toolCalls.length = 0;
        toolCalls.push(...updated);
      }
      return {
        eventsBySession: { ...state.eventsBySession, [sessionId]: events },
        toolCallsBySession: {
          ...state.toolCallsBySession,
          [sessionId]: toolCalls,
        },
      };
    }),
}));
