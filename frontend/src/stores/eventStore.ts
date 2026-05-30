/**
 * Zustand v5 store for accumulated event data per session.
 *
 * Manages the streaming event log and tool call information indexed by
 * session_id. SSE events are appended in real-time; historical events
 * can be bulk-loaded from the REST API.
 */

import { create } from "zustand";
import type { Event, ToolCallInfo, RoundInfo } from "@/lib/eventTypes";

// ── State interface ───────────────────────────────────────────────────

export interface EventStoreState {
  eventsBySession: Record<string, Event[]>;
  toolCallsBySession: Record<string, ToolCallInfo[]>;
  roundsBySession: Record<string, RoundInfo[]>;

  appendEvent: (sessionId: string, event: Event) => void;
  getSessionEvents: (sessionId: string) => Event[];
  getSessionToolCalls: (sessionId: string) => ToolCallInfo[];
  getSessionRounds: (sessionId: string) => RoundInfo[];
  clearSession: (sessionId: string) => void;
  loadSessionEvents: (sessionId: string, events: Event[]) => void;
}

// ── Round tracking helper ─────────────────────────────────────────────

function updateRounds(
  rounds: RoundInfo[],
  event: Event
): RoundInfo[] {
  switch (event.event_type) {
    case "user_message": {
      // Start a new round
      const newRound: RoundInfo = {
        round_num: (event as Event & { round_num: number }).round_num,
        events: [event],
      };
      return [...rounds, newRound];
    }

    case "round_end": {
      // Finalize current round — append to last round
      if (rounds.length === 0) return rounds;
      const updated = [...rounds];
      const last = { ...updated[updated.length - 1] };
      last.events = [...last.events, event];
      updated[updated.length - 1] = last;
      return updated;
    }

    default: {
      // Append to current round (if any)
      if (rounds.length === 0) return rounds;
      const updated = [...rounds];
      const last = { ...updated[updated.length - 1] };
      last.events = [...last.events, event];
      updated[updated.length - 1] = last;
      return updated;
    }
  }
}

function rebuildRounds(events: Event[]): RoundInfo[] {
  const rounds: RoundInfo[] = [];
  let currentEvents: Event[] = [];

  for (const event of events) {
    if (event.event_type === "user_message") {
      // Flush previous partial round
      if (currentEvents.length > 0) {
        rounds.push({
          round_num: rounds.length + 1,
          events: currentEvents,
        });
      }
      // Start new round with this message
      currentEvents = [event];
    } else if (event.event_type === "round_end") {
      currentEvents.push(event);
      rounds.push({
        round_num: rounds.length + 1,
        events: currentEvents,
      });
      currentEvents = [];
    } else {
      currentEvents.push(event);
    }
  }

  // Flush remaining events (active round)
  if (currentEvents.length > 0) {
    rounds.push({
      round_num: rounds.length + 1,
      events: currentEvents,
    });
  }

  return rounds;
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
  roundsBySession: {},

  appendEvent: (sessionId: string, event: Event) =>
    set((state) => {
      const events = [...(state.eventsBySession[sessionId] ?? []), event];
      const toolCalls = updateToolCalls(
        state.toolCallsBySession[sessionId] ?? [],
        event
      );
      const rounds = updateRounds(
        state.roundsBySession[sessionId] ?? [],
        event
      );
      return {
        eventsBySession: { ...state.eventsBySession, [sessionId]: events },
        toolCallsBySession: {
          ...state.toolCallsBySession,
          [sessionId]: toolCalls,
        },
        roundsBySession: {
          ...state.roundsBySession,
          [sessionId]: rounds,
        },
      };
    }),

  getSessionEvents: (sessionId: string) =>
    get().eventsBySession[sessionId] ?? [],

  getSessionToolCalls: (sessionId: string) =>
    get().toolCallsBySession[sessionId] ?? [],

  getSessionRounds: (sessionId: string) =>
    get().roundsBySession[sessionId] ?? [],

  clearSession: (sessionId: string) =>
    set((state) => {
      const { [sessionId]: _, ...restEvents } = state.eventsBySession;
      const { [sessionId]: __, ...restToolCalls } = state.toolCallsBySession;
      const { [sessionId]: ___, ...restRounds } = state.roundsBySession;
      return {
        eventsBySession: restEvents,
        toolCallsBySession: restToolCalls,
        roundsBySession: restRounds,
      };
    }),

  loadSessionEvents: (sessionId: string, events: Event[]) =>
    set((state) => {
      // Rebuild tool calls from the full event list
      const toolCalls: ToolCallInfo[] = [];
      for (const event of events) {
        const updated = updateToolCalls(toolCalls, event);
        toolCalls.length = 0;
        toolCalls.push(...updated);
      }
      // Rebuild rounds from the full event list
      const rounds = rebuildRounds(events);
      return {
        eventsBySession: { ...state.eventsBySession, [sessionId]: events },
        toolCallsBySession: {
          ...state.toolCallsBySession,
          [sessionId]: toolCalls,
        },
        roundsBySession: {
          ...state.roundsBySession,
          [sessionId]: rounds,
        },
      };
    }),
}));
