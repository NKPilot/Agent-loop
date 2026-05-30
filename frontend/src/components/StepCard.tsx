import { memo, useRef, useState, useEffect, useCallback } from "react";
import ReactMarkdown from "react-markdown";
import type { Event, ToolCallInfo } from "@/lib/eventTypes";
import { useUIStore } from "@/stores/uiStore";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Progress } from "@/components/ui/progress";
import { AlertTriangle, Wrench, Eye, Brain } from "lucide-react";

// ── StepGroup type ───────────────────────────────────────────────────────

export interface StepGroup {
  stepNum: number;
  events: Event[];
  status: "pending" | "active" | "completed" | "error";
}

// ── Helpers ──────────────────────────────────────────────────────────────

type StepType = "REASON" | "ACT" | "OBSERVE";

function deriveStepType(events: Event[]): StepType {
  const hasToolResult = events.some((e) => e.event_type === "tool_result");
  const hasToolCall = events.some((e) => e.event_type === "tool_call_start");
  const hasLLMToken = events.some((e) => e.event_type === "llm_token");

  if (hasToolResult) return "OBSERVE";
  if (hasToolCall) return "ACT";
  if (hasLLMToken) return "REASON";
  return "REASON"; // default
}

const STEP_TYPE_CONFIG: Record<
  StepType,
  { icon: typeof Brain; tint: string; label: string }
> = {
  REASON: {
    icon: Brain,
    tint: "border-l-blue-400 bg-blue-50/50 dark:bg-blue-950/20",
    label: "REASON",
  },
  ACT: {
    icon: Wrench,
    tint: "border-l-amber-400 bg-amber-50/50 dark:bg-amber-950/20",
    label: "ACT",
  },
  OBSERVE: {
    icon: Eye,
    tint: "border-l-green-400 bg-green-50/50 dark:bg-green-950/20",
    label: "OBSERVE",
  },
};

const STEP_STATUS_CIRCLE: Record<
  StepGroup["status"],
  string
> = {
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
      // Completed — show full text immediately
      setDisplayText(rawText);
      lastLengthRef.current = rawText.length;
      return;
    }

    // Streaming — flush via requestAnimationFrame to batch updates
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

// ── StepCard ─────────────────────────────────────────────────────────────

interface StepCardProps {
  step: StepGroup;
  toolCalls: ToolCallInfo[];
  isLastActive: boolean;
}

const StepCard = memo(function StepCard({ step, toolCalls, isLastActive }: StepCardProps) {
  const selectToolCall = useUIStore((s) => s.selectToolCall);
  const stepType = deriveStepType(step.events);
  const typeConfig = STEP_TYPE_CONFIG[stepType];
  const Icon = typeConfig.icon;

  const rawText = getAccumulatedText(step.events);
  const displayText = useStreamingText(rawText, step.status === "active");
  const isStreaming = step.status === "active" && rawText.length > 0;

  const inlineToolCalls = getToolCallInfosFromEvents(step.events, toolCalls);

  // Guard events
  const budgetWarning = step.events.find(
    (e) => e.event_type === "budget_warning"
  ) as (Event & { event_type: "budget_warning"; used_pct: number; max_steps: number }) | undefined;
  const loopDetected = step.events.find(
    (e) => e.event_type === "loop_detected"
  );
  const errorEvent = step.events.find(
    (e) => e.event_type === "error"
  ) as (Event & { event_type: "error"; message: string; error_type: string }) | undefined;
  const tokenWarning = step.events.find(
    (e) => e.event_type === "token_warning"
  ) as (Event & { event_type: "token_warning"; used_pct: number }) | undefined;
  const contextCompacted = step.events.find(
    (e) => e.event_type === "context_compacted"
  );

  const handleToolCardClick = useCallback(
    (toolCallId: string) => {
      selectToolCall(toolCallId);
    },
    [selectToolCall]
  );

  return (
    <div
      className={`flex gap-3 border-l-2 px-4 py-3 ${typeConfig.tint} ${
        step.status === "error" ? "border-l-red-500" : ""
      }`}
    >
      {/* Step number badge */}
      <div
        className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-medium ${STEP_STATUS_CIRCLE[step.status]}`}
      >
        {step.stepNum}
      </div>

      {/* Content */}
      <div className="flex flex-1 flex-col gap-2 min-w-0">
        {/* Step header */}
        <div className="flex items-center gap-2">
          <Icon className="size-3.5 text-muted-foreground" />
          <span className="text-xs font-medium text-muted-foreground">
            {typeConfig.label}
          </span>
          {step.status === "active" && !isStreaming && (
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-primary animate-pulse" />
          )}
        </div>

        {/* Reasoning text */}
        {displayText && (
          <div className="text-sm leading-relaxed prose prose-sm dark:prose-invert max-w-none">
            <ReactMarkdown>{displayText}</ReactMarkdown>
            {isStreaming && (
              <span className="inline-block w-0.5 h-4 bg-foreground ml-0.5 align-middle animate-pulse" />
            )}
          </div>
        )}

        {/* Streaming indicator */}
        {step.status === "active" && !displayText && isLastActive && (
          <p className="text-sm text-muted-foreground italic">
            Agent is thinking...
            <span className="animate-pulse">...</span>
          </p>
        )}

        {/* Inline tool call mini-cards */}
        {inlineToolCalls.length > 0 && (
          <div className="flex flex-col gap-1.5 mt-1">
            {inlineToolCalls.map((tc) => (
              <button
                key={tc.tool_call_id}
                className="flex items-center gap-2 rounded-md border border-border bg-card px-2.5 py-1.5 text-left text-xs hover:bg-accent/50 transition-colors cursor-pointer"
                onClick={() => handleToolCardClick(tc.tool_call_id)}
              >
                <Wrench className="size-3 text-muted-foreground shrink-0" />
                <span className="font-mono text-xs font-medium truncate">
                  {tc.tool_name}
                </span>
                <Badge
                  variant={
                    tc.status === "done"
                      ? "secondary"
                      : tc.status === "error"
                      ? "destructive"
                      : "default"
                  }
                >
                  {tc.status}
                </Badge>
              </button>
            ))}
          </div>
        )}

        {/* Guard events inline */}
        {budgetWarning && (
          <Alert variant="default" className="border-amber-400/50 bg-amber-50/50 dark:bg-amber-950/20 mt-1">
            <AlertTriangle className="size-3.5 text-amber-600" />
            <AlertDescription className="text-xs">
              Budget Warning: {budgetWarning.used_pct}% used (step {step.stepNum}/{budgetWarning.max_steps})
            </AlertDescription>
            <Progress value={budgetWarning.used_pct} className="mt-1" />
          </Alert>
        )}

        {loopDetected && (
          <Alert variant="default" className="border-amber-400/50 bg-amber-50/50 dark:bg-amber-950/20 mt-1">
            <AlertTriangle className="size-3.5 text-amber-600" />
            <AlertDescription className="text-xs">
              Loop Detected: The agent is repeating the same tool call pattern.
            </AlertDescription>
          </Alert>
        )}

        {errorEvent && (
          <Alert variant="destructive" className="mt-1">
            <AlertTriangle className="size-3.5" />
            <AlertDescription className="text-xs">
              {errorEvent.error_type}: {errorEvent.message}
            </AlertDescription>
          </Alert>
        )}

        {tokenWarning && (
          <div className="flex items-center gap-2 mt-1">
            <Badge variant="outline" className="border-amber-400/50 text-amber-600 text-xs">
              Token {Math.round(tokenWarning.used_pct)}%
            </Badge>
            <Progress value={tokenWarning.used_pct} className="flex-1" />
          </div>
        )}

        {contextCompacted && (
          <p className="text-xs text-muted-foreground italic mt-1">
            Context Compacting...
          </p>
        )}
      </div>
    </div>
  );
});

export default StepCard;
