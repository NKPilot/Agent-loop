import { useRef, useEffect, useState, useMemo, useCallback } from "react";
import { ArrowDown } from "lucide-react";
import { useEventStore } from "@/stores/eventStore";
import { useUIStore } from "@/stores/uiStore";
import type { Event } from "@/lib/eventTypes";
import StepCard, { type StepGroup } from "@/components/StepCard";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";

// ── Step grouping logic ──────────────────────────────────────────────────

function groupEventsByStep(events: Event[]): StepGroup[] {
  const stepMap = new Map<number, Event[]>();
  let maxStepNum = 0;

  for (const event of events) {
    const stepNum =
      "step_num" in event ? (event as unknown as { step_num: number }).step_num : 0;
    if (stepNum > 0) {
      if (!stepMap.has(stepNum)) {
        stepMap.set(stepNum, []);
      }
      stepMap.get(stepNum)!.push(event);
      maxStepNum = Math.max(maxStepNum, stepNum);
    }
  }

  const groups: StepGroup[] = [];
  for (const [stepNum, stepEvents] of stepMap) {
    const hasStepEnd = stepEvents.some((e) => e.event_type === "step_end");
    const hasError = stepEvents.some((e) => e.event_type === "error");
    const isActive = stepNum === maxStepNum && !hasStepEnd;

    let status: StepGroup["status"];
    if (hasError) {
      status = "error";
    } else if (isActive) {
      status = "active";
    } else if (hasStepEnd) {
      status = "completed";
    } else {
      status = "pending";
    }

    groups.push({ stepNum, events: stepEvents, status });
  }

  // Sort by step number ascending
  groups.sort((a, b) => a.stepNum - b.stepNum);
  return groups;
}

// ── Loading skeleton ─────────────────────────────────────────────────────

function TimelineSkeleton() {
  return (
    <div className="space-y-3 p-4">
      {Array.from({ length: 3 }).map((_, i) => (
        <div key={i} className="flex gap-3">
          <Skeleton className="h-6 w-6 rounded-full shrink-0" />
          <div className="flex flex-1 flex-col gap-2">
            <Skeleton className="h-3 w-16" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-3/4" />
          </div>
        </div>
      ))}
    </div>
  );
}

// ── AgentTimeline ────────────────────────────────────────────────────────

function AgentTimeline() {
  const activeSessionId = useUIStore((s) => s.activeSessionId);
  const eventsBySession = useEventStore((s) => s.eventsBySession);
  const toolCallsBySession = useEventStore((s) => s.toolCallsBySession);
  const [isAtBottom, setIsAtBottom] = useState(true);
  const [isLoading, setIsLoading] = useState(false);

  const bottomRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);

  const events = activeSessionId ? eventsBySession[activeSessionId] ?? [] : [];
  const toolCalls = activeSessionId ? toolCallsBySession[activeSessionId] ?? [] : [];

  const steps = useMemo(() => groupEventsByStep(events), [events]);

  // Track loading state when session changes (historical fetch)
  useEffect(() => {
    if (activeSessionId && events.length === 0) {
      setIsLoading(true);
      // Give the historical fetch a chance to load events
      const timer = setTimeout(() => setIsLoading(false), 2000);
      return () => clearTimeout(timer);
    } else {
      setIsLoading(false);
    }
  }, [activeSessionId, events.length]);

  // Auto-scroll to bottom when new events arrive
  useEffect(() => {
    if (isAtBottom && bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [events.length, isAtBottom]);

  // Track scroll position
  const handleScroll = useCallback(() => {
    const container = scrollContainerRef.current;
    if (!container) return;

    // Check if user is within 50px of the bottom
    const scrollBottom =
      container.scrollHeight - container.scrollTop - container.clientHeight;
    setIsAtBottom(scrollBottom < 50);
  }, []);

  const scrollToBottom = useCallback(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    setIsAtBottom(true);
  }, []);

  const hasActiveStep = steps.some((s) => s.status === "active");

  // Empty state: no active session
  if (!activeSessionId) {
    return (
      <div className="flex flex-1 items-center justify-center p-6">
        <div className="text-center space-y-2">
          <p className="text-sm text-muted-foreground">
            Select a session to view its timeline.
          </p>
        </div>
      </div>
    );
  }

  // Loading state
  if (isLoading) {
    return <TimelineSkeleton />;
  }

  return (
    <div className="relative flex flex-1 flex-col overflow-hidden">
      <ScrollArea
        className="flex-1"
        ref={scrollContainerRef as React.Ref<HTMLDivElement>}
        onScroll={handleScroll}
      >
        <div className="divide-y divide-border">
          {steps.length === 0 && !hasActiveStep && (
            <div className="flex items-center justify-center p-6">
              <p className="text-sm text-muted-foreground">
                Waiting for agent events...
              </p>
            </div>
          )}

          {steps.map((step, idx) => (
            <StepCard
              key={step.stepNum}
              step={step}
              toolCalls={toolCalls}
              isLastActive={idx === steps.length - 1 && step.status === "active"}
            />
          ))}

          {/* Streaming indicator for active step without content yet */}
          {hasActiveStep && steps.length === 0 && (
            <div className="flex items-center justify-center p-6">
              <p className="text-sm text-muted-foreground italic">
                Agent is thinking...
                <span className="animate-pulse">...</span>
              </p>
            </div>
          )}
        </div>
        <div ref={bottomRef} />
      </ScrollArea>

      {/* "Scroll to bottom" floating button */}
      {!isAtBottom && (
        <Button
          variant="secondary"
          size="icon-sm"
          className="absolute bottom-4 right-4 z-10 shadow-md"
          onClick={scrollToBottom}
        >
          <ArrowDown />
        </Button>
      )}
    </div>
  );
}

export default AgentTimeline;
