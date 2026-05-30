/**
 * AgentCallCard — 可展开的多 Agent 调用嵌套卡片组件。
 *
 * 显示主 Agent 调用子 Agent 的嵌套关系：
 * - 默认状态：紫色主题卡片 + agent 名称 + 状态标记
 * - 展开后：REST 获取子会话详情渲染嵌套时间线
 * - 摘要栏：tool_calls 数量、token 消耗、执行步骤数、成功/失败状态
 */
import { useState, useCallback } from "react";
import { ChevronDown, ChevronRight, Bot, Loader2, CheckCircle, XCircle, Wrench, DollarSign, StepForward } from "lucide-react";
import type { Event, AgentCallStartEvent, AgentCallEndEvent } from "@/lib/eventTypes";
import { fetchSession, type SessionDetail } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

// ── Props ─────────────────────────────────────────────────────────────

interface AgentCallCardProps {
  /** 当前步骤的所有事件 */
  events: Event[];
  /** 子 Agent 的 session ID */
  childSessionId: string;
}

// ── Type-safe event finders ───────────────────────────────────────────

function findStartEvent(
  events: Event[],
  childSessionId: string
): AgentCallStartEvent | undefined {
  return events.find(
    (e): e is AgentCallStartEvent =>
      e.event_type === "agent_call_start" && e.child_session_id === childSessionId
  );
}

function findEndEvent(
  events: Event[],
  childSessionId: string
): AgentCallEndEvent | undefined {
  return events.find(
    (e): e is AgentCallEndEvent =>
      e.event_type === "agent_call_end" && e.child_session_id === childSessionId
  );
}

// ── Loading Skeleton ──────────────────────────────────────────────────

function ChildSessionSkeleton() {
  return (
    <div className="space-y-2 animate-pulse mt-2">
      <div className="h-3 w-3/4 rounded bg-muted" />
      <div className="h-3 w-1/2 rounded bg-muted" />
      <div className="h-3 w-2/3 rounded bg-muted" />
    </div>
  );
}

// ── AgentCallCard ─────────────────────────────────────────────────────

function AgentCallCard({ events, childSessionId }: AgentCallCardProps) {
  const [expanded, setExpanded] = useState(false);
  const [childSession, setChildSession] = useState<SessionDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [fetchError, setFetchError] = useState<string | null>(null);

  const startEvent = findStartEvent(events, childSessionId);
  const endEvent = findEndEvent(events, childSessionId);

  const agentName = startEvent?.agent_name ?? endEvent?.agent_name ?? "Unknown Agent";
  const isRunning = !endEvent;
  const isSuccess = endEvent?.success ?? false;

  const summary = endEvent?.summary ?? "";
  const toolCallsCount = endEvent?.tool_calls_count ?? 0;
  const tokenUsage = endEvent?.token_usage ?? null;
  const steps = endEvent?.steps ?? 0;

  const handleToggle = useCallback(() => {
    const nextExpanded = !expanded;
    setExpanded(nextExpanded);

    if (nextExpanded && !childSession && !loading && !fetchError) {
      setLoading(true);
      setFetchError(null);

      fetchSession(childSessionId)
        .then((session) => {
          setChildSession(session);
          setLoading(false);
        })
        .catch((err: Error) => {
          setFetchError(err.message);
          setLoading(false);
        });
    }
  }, [expanded, childSession, loading, fetchError, childSessionId]);

  return (
    <div
      className={cn(
        "rounded-lg border border-purple-200/60 bg-purple-50/40 dark:border-purple-800/30 dark:bg-purple-950/15 overflow-hidden transition-colors",
        isRunning && "border-purple-400/50 ring-1 ring-purple-400/20",
        !isRunning && isSuccess && "border-purple-300/50",
        !isRunning && !isSuccess && "border-red-300/50 dark:border-red-800/30"
      )}
    >
      {/* ── Card Header (always visible) ─────────────────────────────── */}
      <button
        type="button"
        onClick={handleToggle}
        className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-purple-100/40 dark:hover:bg-purple-900/20 transition-colors cursor-pointer"
      >
        {/* Expand/collapse icon */}
        {expanded ? (
          <ChevronDown className="size-3.5 shrink-0 text-purple-600 dark:text-purple-400" />
        ) : (
          <ChevronRight className="size-3.5 shrink-0 text-purple-600 dark:text-purple-400" />
        )}

        {/* Agent icon */}
        <Bot className="size-4 shrink-0 text-purple-600 dark:text-purple-400" />

        {/* Agent name */}
        <span className="flex-1 truncate text-xs font-semibold text-purple-800 dark:text-purple-200">
          Agent: {agentName}
        </span>

        {/* Status badge */}
        {isRunning ? (
          <Badge
            variant="default"
            className="bg-purple-500/15 text-purple-700 dark:text-purple-300 border-purple-300/40 text-[10px] px-1.5 py-0"
          >
            <Loader2 className="size-2.5 animate-spin mr-1 inline" />
            Running
          </Badge>
        ) : isSuccess ? (
          <Badge
            variant="secondary"
            className="bg-green-100/60 text-green-700 dark:bg-green-900/20 dark:text-green-300 border-green-300/40 text-[10px] px-1.5 py-0"
          >
            <CheckCircle className="size-2.5 mr-1 inline" />
            Done
          </Badge>
        ) : (
          <Badge
            variant="destructive"
            className="text-[10px] px-1.5 py-0"
          >
            <XCircle className="size-2.5 mr-1 inline" />
            Failed
          </Badge>
        )}
      </button>

      {/* ── Expanded content ────────────────────────────────────────── */}
      {expanded && (
        <div className="border-t border-purple-200/40 dark:border-purple-800/20 px-3 py-2 space-y-2">
          {/* Loading state */}
          {loading && <ChildSessionSkeleton />}

          {/* Fetch error */}
          {fetchError && (
            <p className="text-xs text-red-500">
              Failed to load child session: {fetchError}
            </p>
          )}

          {/* Summary text */}
          {!loading && summary && (
            <p className="text-xs text-muted-foreground leading-relaxed line-clamp-3">
              {summary}
            </p>
          )}

          {/* Metrics row */}
          {!loading && !fetchError && (toolCallsCount > 0 || tokenUsage || steps > 0) && (
            <div className="flex flex-wrap items-center gap-2 mt-1">
              {toolCallsCount > 0 && (
                <span className="inline-flex items-center gap-1 text-[10px] text-muted-foreground">
                  <Wrench className="size-3" />
                  {toolCallsCount} tool calls
                </span>
              )}
              {steps > 0 && (
                <span className="inline-flex items-center gap-1 text-[10px] text-muted-foreground">
                  <StepForward className="size-3" />
                  {steps} steps
                </span>
              )}
              {tokenUsage && tokenUsage.total_tokens > 0 && (
                <span className="inline-flex items-center gap-1 text-[10px] text-muted-foreground">
                  <DollarSign className="size-3" />
                  {tokenUsage.total_tokens} tokens
                </span>
              )}
            </div>
          )}

          {/* Child session timeline link */}
          {!loading && childSession && (
            <div className="mt-1 pt-1 border-t border-purple-200/30 dark:border-purple-800/15">
              <p className="text-[10px] text-muted-foreground">
                Session: <code className="text-purple-600 dark:text-purple-400 text-[9px]">{childSession.id}</code>
                <span className="ml-2">
                  ({childSession.step_count} steps, {childSession.status})
                </span>
              </p>
            </div>
          )}

          {/* Empty end state: agent call ended but no summary available */}
          {!loading && !fetchError && endEvent && !summary && !childSession && (
            <p className="text-xs text-muted-foreground italic">
              Child session completed. No summary available.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

export default AgentCallCard;
