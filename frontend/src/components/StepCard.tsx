import { memo, useRef, useState, useEffect, useCallback } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Event, ToolCallInfo, AgentCallStartEvent } from "@/lib/eventTypes";
import { fixMarkdownTable } from "@/utils/markdown";
import { useUIStore } from "@/stores/uiStore";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Progress } from "@/components/ui/progress";
import { AlertTriangle, Wrench, Eye, Brain, ChevronDown } from "lucide-react";
import AgentCallCard from "@/components/AgentCallCard";

// ── StepGroup type ───────────────────────────────────────────────────────

export interface StepGroup {
  stepNum: number;
  events: Event[];
  status: "pending" | "active" | "completed" | "error";
}

// ── Step grouping (exported for App.tsx) ─────────────────────────────────

export function groupEventsByStep(events: Event[]): StepGroup[] {
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

  groups.sort((a, b) => a.stepNum - b.stepNum);
  return groups;
}

// ── Helpers ──────────────────────────────────────────────────────────────

const STEP_STATUS_CIRCLE: Record<StepGroup["status"], string> = {
  pending: "bg-muted text-muted-foreground",
  active: "bg-primary text-primary-foreground",
  completed: "bg-muted text-foreground",
  error: "bg-destructive text-destructive-foreground",
};

function getAccumulatedText(events: Event[]): string {
  return events
    .filter((e): e is Event & { event_type: "llm_token"; content_delta: string } =>
      e.event_type === "llm_token"
    )
    .map((e) => e.content_delta)
    .join("");
}

function getToolCallInfosFromEvents(events: Event[], toolCalls: ToolCallInfo[]): ToolCallInfo[] {
  const ids = new Set(
    events
      .filter((e) => e.event_type === "tool_call_start")
      .map((e) => (e as Event & { tool_call_id: string }).tool_call_id)
  );
  return toolCalls.filter((tc) => ids.has(tc.tool_call_id));
}

// ── Streaming text hook ──────────────────────────────────────────────────

function useStreamingText(rawText: string, isStreaming: boolean) {
  const [displayText, setDisplayText] = useState("");
  const rafRef = useRef<number | null>(null);
  const lastLengthRef = useRef(0);

  useEffect(() => {
    if (!isStreaming) {
      setDisplayText(rawText);
      lastLengthRef.current = rawText.length;
      return;
    }

    const flush = () => {
      if (lastLengthRef.current < rawText.length) {
        setDisplayText(rawText);
        lastLengthRef.current = rawText.length;
      }
      rafRef.current = requestAnimationFrame(flush);
    };
    rafRef.current = requestAnimationFrame(flush);

    return () => {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
      }
    };
  }, [rawText, isStreaming]);

  return displayText;
}

// ── Sub-components ───────────────────────────────────────────────────────

function ToolCallCard({ tc }: { tc: ToolCallInfo }) {
  const selectToolCall = useUIStore((s) => s.selectToolCall);
  const [expanded, setExpanded] = useState(false);

  const handleClick = useCallback(() => {
    selectToolCall(tc.tool_call_id);
    setExpanded((prev) => !prev);
  }, [tc.tool_call_id, selectToolCall]);

  return (
    <div>
      <button
        className="flex items-center gap-2 w-full rounded-md border border-amber-400/40 bg-amber-50/50 dark:bg-amber-950/20 px-2.5 py-1.5 text-left text-xs hover:bg-amber-100/50 dark:hover:bg-amber-900/30 transition-colors cursor-pointer"
        onClick={handleClick}
      >
        <Wrench className="size-3 text-amber-600 shrink-0" />
        <span className="font-mono text-xs font-medium truncate flex-1">{tc.tool_name}</span>
        <Badge
          variant={tc.is_error ? "destructive" : "secondary"}
          className="text-[10px]"
        >
          {tc.status}
        </Badge>
        <ChevronDown
          className={`size-3 text-muted-foreground transition-transform ${
            expanded ? "rotate-180" : ""
          }`}
        />
      </button>

      {expanded && (
        <div className="ml-2 mt-1 p-2 rounded-md bg-muted/50 text-xs font-mono space-y-1.5">
          {tc.full_args && Object.keys(tc.full_args).length > 0 && (
            <div>
              <p className="text-muted-foreground mb-0.5 font-medium">Arguments:</p>
              <pre className="whitespace-pre-wrap text-[11px]">
                {JSON.stringify(tc.full_args, null, 2)}
              </pre>
            </div>
          )}
          {tc.result && (
            <div>
              <p className="text-muted-foreground mb-0.5 font-medium">Result:</p>
              <pre className="whitespace-pre-wrap text-[11px]">{tc.result}</pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── StepCard ─────────────────────────────────────────────────────────────

interface StepCardProps {
  step: StepGroup;
  toolCalls: ToolCallInfo[];
  isLastActive: boolean;
}

const StepCard = memo(function StepCard({ step, toolCalls, isLastActive }: StepCardProps) {
  const rawText = getAccumulatedText(step.events);
  const displayText = useStreamingText(rawText, step.status === "active");
  const isStreaming = step.status === "active" && rawText.length > 0;

  const inlineToolCalls = getToolCallInfosFromEvents(step.events, toolCalls);
  const hasToolCall = step.events.some((e) => e.event_type === "tool_call_start");
  const hasToolResult = inlineToolCalls.some((tc) => tc.result != null);
  const hasThinking = displayText.length > 0;

  // Guard events
  const budgetWarning = step.events.find(
    (e) => e.event_type === "budget_warning"
  ) as (Event & { event_type: "budget_warning"; used_pct: number; max_steps: number }) | undefined;
  const loopDetected = step.events.find((e) => e.event_type === "loop_detected");
  const errorEvent = step.events.find(
    (e) => e.event_type === "error"
  ) as (Event & { event_type: "error"; message: string; error_type: string }) | undefined;
  const tokenWarning = step.events.find(
    (e) => e.event_type === "token_warning"
  ) as (Event & { event_type: "token_warning"; used_pct: number }) | undefined;
  const contextCompacted = step.events.find((e) => e.event_type === "context_compacted");

  return (
    <div
      className={`rounded-lg border border-border bg-card overflow-hidden ${
        step.status === "error" ? "ring-1 ring-destructive/50" : ""
      }`}
    >
      {/* Step header */}
      <div className="flex items-center gap-2 px-4 py-2 bg-muted/30 border-b border-border">
        <div
          className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] font-bold ${STEP_STATUS_CIRCLE[step.status]}`}
        >
          {step.stepNum}
        </div>
        <span className="text-xs font-medium text-muted-foreground">
          Step {step.stepNum}
        </span>
        {step.status === "active" && (
          <span className="inline-block h-1.5 w-1.5 rounded-full bg-primary animate-pulse" />
        )}
        {step.status === "completed" && (
          <Badge variant="secondary" className="text-[10px]">done</Badge>
        )}
        {step.status === "error" && (
          <Badge variant="destructive" className="text-[10px]">error</Badge>
        )}
      </div>

      {/* Step body — three distinct phases */}
      <div className="px-4 py-3 space-y-3">
        {/* Phase 1: REASON — thinking text */}
        {hasThinking && (
          <div className="border-l-2 border-l-blue-400 pl-3">
            <div className="flex items-center gap-1.5 mb-1">
              <Brain className="size-3.5 text-blue-500" />
              <span className="text-[11px] font-medium text-blue-600 dark:text-blue-400">
                REASON
              </span>
              {isStreaming && (
                <span className="inline-block w-0.5 h-3 bg-blue-400 animate-pulse ml-1" />
              )}
            </div>
            <div className="text-sm leading-relaxed prose prose-sm dark:prose-invert max-w-none">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{fixMarkdownTable(displayText)}</ReactMarkdown>
            </div>
          </div>
        )}

        {/* Streaming indicator when no text yet */}
        {step.status === "active" && !hasThinking && isLastActive && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground italic">
            <Brain className="size-3.5 text-blue-400 animate-pulse" />
            Agent is thinking<span className="animate-pulse">...</span>
          </div>
        )}

        {/* Phase 2: ACT — tool calls */}
        {inlineToolCalls.length > 0 && (
          <div className="border-l-2 border-l-amber-400 pl-3">
            <div className="flex items-center gap-1.5 mb-1.5">
              <Wrench className="size-3.5 text-amber-500" />
              <span className="text-[11px] font-medium text-amber-600 dark:text-amber-400">
                ACT
              </span>
            </div>
            <div className="space-y-1.5">
              {inlineToolCalls.map((tc) => (
                <ToolCallCard key={tc.tool_call_id} tc={tc} />
              ))}
            </div>
          </div>
        )}

        {/* Phase 3: OBSERVE — tool results (shown inline when available) */}
        {hasToolResult && (
          <div className="border-l-2 border-l-green-400 pl-3">
            <div className="flex items-center gap-1.5 mb-1.5">
              <Eye className="size-3.5 text-green-500" />
              <span className="text-[11px] font-medium text-green-600 dark:text-green-400">
                OBSERVE
              </span>
            </div>
            <div className="space-y-1.5">
              {inlineToolCalls
                .filter((tc) => tc.result != null)
                .map((tc) => (
                  <div
                    key={`result-${tc.tool_call_id}`}
                    className="rounded-md border border-border bg-muted/30 px-2.5 py-1.5 text-xs"
                  >
                    <span className="font-mono font-medium text-muted-foreground">
                      {tc.tool_name}
                    </span>
                    <pre className="mt-1 whitespace-pre-wrap text-[11px] text-foreground/80">
                      {tc.result}
                    </pre>
                  </div>
                ))}
            </div>
          </div>
        )}

        {/* Guard events inline */}
        {budgetWarning && (
          <Alert variant="default" className="border-amber-400/50 bg-amber-50/50 dark:bg-amber-950/20">
            <AlertTriangle className="size-3.5 text-amber-600" />
            <AlertDescription className="text-xs">
              Budget Warning: {budgetWarning.used_pct}% used (step {step.stepNum}/{budgetWarning.max_steps})
            </AlertDescription>
            <Progress value={budgetWarning.used_pct} className="mt-1" />
          </Alert>
        )}

        {loopDetected && (
          <Alert variant="default" className="border-amber-400/50 bg-amber-50/50 dark:bg-amber-950/20">
            <AlertTriangle className="size-3.5 text-amber-600" />
            <AlertDescription className="text-xs">
              Loop Detected: The agent is repeating the same tool call pattern.
            </AlertDescription>
          </Alert>
        )}

        {errorEvent && (
          <Alert variant="destructive">
            <AlertTriangle className="size-3.5" />
            <AlertDescription className="text-xs">
              {errorEvent.error_type}: {errorEvent.message}
            </AlertDescription>
          </Alert>
        )}

        {tokenWarning && (
          <div className="flex items-center gap-2">
            <Badge variant="outline" className="border-amber-400/50 text-amber-600 text-xs">
              Token {Math.round(tokenWarning.used_pct)}%
            </Badge>
            <Progress value={tokenWarning.used_pct} className="flex-1" />
          </div>
        )}

        {contextCompacted && (
          <p className="text-xs text-muted-foreground italic">
            Context Compacting...
          </p>
        )}

        {/* Multi-agent nested calls */}
        {(() => {
          const childSessionIds = [
            ...new Set(
              step.events
                .filter((e): e is AgentCallStartEvent => e.event_type === "agent_call_start")
                .map((e) => e.child_session_id)
            ),
          ];
          if (childSessionIds.length === 0) return null;
          return (
            <div className="flex flex-col gap-2 mt-1">
              {childSessionIds.map((id) => (
                <AgentCallCard key={id} events={step.events} childSessionId={id} />
              ))}
            </div>
          );
        })()}
      </div>
    </div>
  );
});

export default StepCard;
