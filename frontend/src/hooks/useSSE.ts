/**
 * Custom React hook for SSE (Server-Sent Events) connection management.
 *
 * Implements Pattern 2 from RESEARCH.md: automatic reconnection with
 * exponential backoff (max 30s per D-04). Uses a single onmessage handler
 * for simplicity — event type dispatch is handled by the caller.
 *
 * Uses the native EventSource API (MDN standard) for broad browser support.
 */

import { useEffect, useRef, useState, useCallback } from "react";
import type { Event, SSEStatus } from "@/lib/eventTypes";

export interface SSEOptions {
  maxRetries?: number;
  maxBackoff?: number;
}

// ── Hook ──────────────────────────────────────────────────────────────

export function useSSE(
  url: string | null,
  onEvent: (eventType: string, data: Event) => void,
  options?: SSEOptions
): { status: SSEStatus; retryCount: number } {
  const { maxRetries = 10, maxBackoff = 30000 } = options ?? {};

  const [status, setStatus] = useState<SSEStatus>("connecting");
  const [retryCount, setRetryCount] = useState(0);

  const esRef = useRef<EventSource | null>(null);
  const retryCountRef = useRef(0);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const onEventRef = useRef(onEvent);

  // Keep onEvent callback ref current without re-triggering useEffect
  onEventRef.current = onEvent;

  const connect = useCallback(() => {
    if (!url) return;

    // Clean up any existing connection
    esRef.current?.close();
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }

    const es = new EventSource(url);
    esRef.current = es;
    setStatus("connecting");

    es.onopen = () => {
      setStatus("connected");
      retryCountRef.current = 0;
      setRetryCount(0);
    };

    es.onmessage = (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data) as Event;
        onEventRef.current(data.event_type, data);
      } catch {
        // Skip malformed events
      }
    };

    es.onerror = () => {
      es.close();
      esRef.current = null;

      const retries = retryCountRef.current;
      if (retries >= maxRetries) {
        setStatus("failed");
        return;
      }

      // Exponential backoff: delay = min(1000 * 2^retries, maxBackoff)
      const delay = Math.min(1000 * Math.pow(2, retries), maxBackoff);
      retryCountRef.current = retries + 1;
      setRetryCount(retries + 1);
      setStatus("reconnecting");

      timeoutRef.current = setTimeout(() => {
        connect();
      }, delay);
    };
  }, [url, maxRetries, maxBackoff]);

  useEffect(() => {
    connect();

    return () => {
      esRef.current?.close();
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
    };
  }, [connect]);

  return { status, retryCount };
}
