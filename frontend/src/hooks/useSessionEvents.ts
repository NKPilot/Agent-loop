/**
 * Bridge hook connecting SSE stream -> Zustand eventStore + React Query cache.
 *
 * When a session is active, this hook opens an SSE connection to
 * `/api/sessions/{id}/stream`, dispatches incoming events to the eventStore,
 * and triggers React Query cache invalidation on session completion.
 */

import { useCallback, useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useSSE } from "@/hooks/useSSE";
import { useEventStore } from "@/stores/eventStore";
import { useUIStore } from "@/stores/uiStore";
import type { Event, SSEStatus } from "@/lib/eventTypes";

// ── Hook ──────────────────────────────────────────────────────────────

export function useSessionEvents(sessionId: string | null): { status: SSEStatus } {
  const queryClient = useQueryClient();
  const appendEvent = useEventStore((s) => s.appendEvent);
  const setSSEStatus = useUIStore((s) => s.setSSEStatus);

  const onEvent = useCallback(
    (eventType: string, data: Event) => {
      if (!sessionId) return;

      // Dispatch event to the event store
      appendEvent(sessionId, data);

      // Handle session lifecycle events
      if (eventType === "session_end") {
        queryClient.invalidateQueries({ queryKey: ["sessions"] });
      }

      // Handle confirmation required — set pending confirmation in UI store
      if (eventType === "confirmation_required" && data.event_type === "confirmation_required") {
        useUIStore.getState().setPendingConfirmation(data);
      }
    },
    [sessionId, appendEvent, queryClient]
  );

  const url = sessionId ? `/api/sessions/${encodeURIComponent(sessionId)}/stream` : null;

  const { status } = useSSE(url, onEvent);

  // Sync SSE status to UI store via effect (avoids render-phase store writes)
  useEffect(() => {
    setSSEStatus(status);
  }, [status, setSSEStatus]);

  return { status };
}
