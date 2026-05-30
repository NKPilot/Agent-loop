/**
 * ToolDetail — 右侧面板组件，展示选中工具调用的详细信息。
 *
 * 功能：参数 JSON 语法高亮显示、结果内容（含溢出文件引用）、
 * 状态标记、耗时和元数据。空状态提示用户选择工具调用。
 */

import { useMemo } from "react";
import { useUIStore } from "@/stores/uiStore";
import { useEventStore } from "@/stores/eventStore";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { calculateCost, formatCost, formatTokens } from "@/lib/costCalculator";
import type { ToolCallInfo, StepEndEvent } from "@/lib/eventTypes";

// ── JSON syntax highlighting ─────────────────────────────────────────────
// 通过 React 元素实现语法着色，不使用 dangerouslySetInnerHTML
// 满足威胁模型 T-05-17 要求

function JsonHighlight({ data }: { data: Record<string, unknown> }) {
  const json = JSON.stringify(data, null, 2);

  const tokens: { text: string; className?: string }[] = [];
  let i = 0;

  while (i < json.length) {
    // Whitespace
    if (json[i] === " " || json[i] === "\n") {
      const start = i;
      while (i < json.length && (json[i] === " " || json[i] === "\n")) i++;
      tokens.push({ text: json.slice(start, i) });
      continue;
    }

    // String (key or value)
    if (json[i] === '"') {
      const start = i;
      i++;
      while (i < json.length) {
        if (json[i] === "\\") i += 2;
        else if (json[i] === '"') { i++; break; }
        else i++;
      }
      const str = json.slice(start, i);

      // Check if followed by ':' (it's a key)
      const afterMatch = json.slice(i).match(/^:\s*/);
      if (afterMatch) {
        tokens.push({ text: str, className: "text-foreground font-medium" });
        tokens.push({ text: afterMatch[0] });
        i += afterMatch[0].length;
      } else {
        tokens.push({ text: str, className: "text-green-600 dark:text-green-400" });
      }
      continue;
    }

    // Number (including negative)
    if (/\d/.test(json[i]) || (json[i] === "-" && i + 1 < json.length && /\d/.test(json[i + 1]))) {
      const start = i;
      if (json[i] === "-") i++;
      while (i < json.length && /[\d.eE+]/i.test(json[i])) i++;
      tokens.push({ text: json.slice(start, i), className: "text-blue-600 dark:text-blue-400" });
      continue;
    }

    // Boolean / null
    if (json.startsWith("true", i)) {
      tokens.push({ text: "true", className: "text-amber-600 dark:text-amber-400" });
      i += 4;
      continue;
    }
    if (json.startsWith("false", i)) {
      tokens.push({ text: "false", className: "text-amber-600 dark:text-amber-400" });
      i += 5;
      continue;
    }
    if (json.startsWith("null", i)) {
      tokens.push({ text: "null", className: "text-muted-foreground" });
      i += 4;
      continue;
    }

    // Structural / punctuation
    tokens.push({ text: json[i] });
    i++;
  }

  return (
    <pre className="font-mono text-xs leading-relaxed whitespace-pre-wrap">
      {tokens.map((t, idx) => (
        <span key={idx} className={t.className}>{t.text}</span>
      ))}
    </pre>
  );
}

// ── Status badge config ──────────────────────────────────────────────────

interface StatusBadgeConfig {
  variant: "default" | "secondary" | "destructive" | "outline";
  label: string;
  className: string;
}

const STATUS_BADGE: Record<string, StatusBadgeConfig> = {
  done: {
    variant: "outline",
    label: "Done",
    className: "border-green-200 text-green-700 bg-green-50 dark:border-green-800 dark:text-green-400 dark:bg-green-950/30",
  },
  error: {
    variant: "destructive",
    label: "Error",
    className: "",
  },
  running: {
    variant: "default",
    label: "Running",
    className: "",
  },
  pending: {
    variant: "secondary",
    label: "Pending",
    className: "",
  },
};

// ── Overflow file pattern ────────────────────────────────────────────────

const OVERFLOW_FILE_RE = /\[工具输出已保存至:\s*(.+?)\s*\]/;

// ── Result rendering ─────────────────────────────────────────────────────

function formatResult(raw: string | undefined) {
  if (!raw) {
    return <p className="text-xs text-muted-foreground italic">No result data</p>;
  }

  const overflowMatch = raw.match(OVERFLOW_FILE_RE);
  if (overflowMatch) {
    const filePath = overflowMatch[1];
    const beforeRef = raw.slice(0, overflowMatch.index ?? 0);

    return (
      <div>
        {beforeRef && (
          <pre className="font-mono text-xs leading-relaxed whitespace-pre-wrap mb-1">
            {beforeRef}
          </pre>
        )}
        <div className="flex items-center gap-1 text-xs text-muted-foreground">
          <span>[工具输出已保存至:</span>
          <span className="font-mono text-blue-600 dark:text-blue-400 truncate max-w-[200px]">
            {filePath}
          </span>
          <span>]</span>
        </div>
      </div>
    );
  }

  return (
    <pre className="font-mono text-xs leading-relaxed whitespace-pre-wrap">
      {raw}
    </pre>
  );
}

// ── ToolDetail ───────────────────────────────────────────────────────────

function ToolDetail() {
  const selectedToolCallId = useUIStore((s) => s.selectedToolCallId);
  const activeSessionId = useUIStore((s) => s.activeSessionId);
  const toolCallsBySession = useEventStore((s) => s.toolCallsBySession);
  const eventsBySession = useEventStore((s) => s.eventsBySession);

  // Find matching tool call
  const toolCall = useMemo<ToolCallInfo | null>(() => {
    if (!activeSessionId || !selectedToolCallId) return null;
    const calls = toolCallsBySession[activeSessionId] ?? [];
    return calls.find((tc) => tc.tool_call_id === selectedToolCallId) ?? null;
  }, [activeSessionId, selectedToolCallId, toolCallsBySession]);

  // Get token usage from StepEnd event for this step
  const stepEndTokenUsage = useMemo(() => {
    if (!activeSessionId || !toolCall) return null;
    const events = eventsBySession[activeSessionId] ?? [];
    const stepEnd = events.find(
      (e): e is StepEndEvent =>
        e.event_type === "step_end" && e.step_num === toolCall.step_num
    );
    return stepEnd?.token_usage ?? null;
  }, [activeSessionId, toolCall, eventsBySession]);

  const estimatedCost = useMemo(() => {
    if (!stepEndTokenUsage) return null;
    return calculateCost(
      stepEndTokenUsage.prompt_tokens,
      stepEndTokenUsage.completion_tokens
    );
  }, [stepEndTokenUsage]);

  // ── Empty state ──────────────────────────────────────────────────────────

  if (!toolCall) {
    return (
      <div className="flex flex-1 items-center justify-center p-6 transition-opacity duration-150 ease">
        <div className="text-center space-y-2">
          <p className="text-sm font-medium text-foreground">Select a tool call</p>
          <p className="text-xs text-muted-foreground max-w-[260px]">
            Click any tool call in the timeline to view its arguments, result,
            and performance metrics.
          </p>
        </div>
      </div>
    );
  }

  // ── Populated state ──────────────────────────────────────────────────────

  const statusConfig = STATUS_BADGE[toolCall.status] ?? STATUS_BADGE.pending;

  return (
    <ScrollArea className="flex-1">
      <div className="p-4 space-y-4 transition-opacity duration-150 ease">
        {/* Header — tool name + status badge + duration */}
        <Card>
          <CardHeader className="pb-0">
            <div className="flex items-center justify-between gap-2">
              <CardTitle className="text-lg font-semibold truncate">
                {toolCall.tool_name}
              </CardTitle>
              <Badge
                variant={statusConfig.variant}
                className={statusConfig.className}
              >
                {statusConfig.label}
              </Badge>
            </div>
            {toolCall.duration_ms !== undefined && (
              <p className="text-xs text-muted-foreground mt-1">
                {toolCall.duration_ms}ms
              </p>
            )}
          </CardHeader>
        </Card>

        {/* Arguments — JSON syntax-highlighted */}
        {toolCall.full_args && Object.keys(toolCall.full_args).length > 0 && (
          <Card>
            <CardHeader className="pb-1">
              <CardTitle className="text-sm font-medium">Arguments</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="rounded-md bg-muted/50 p-3 overflow-x-auto">
                <JsonHighlight data={toolCall.full_args} />
              </div>
            </CardContent>
          </Card>
        )}

        {/* Result */}
        <Card>
          <CardHeader className="pb-1">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm font-medium">Result</CardTitle>
              {toolCall.is_error && (
                <Badge variant="destructive">Error</Badge>
              )}
            </div>
          </CardHeader>
          <CardContent>
            <div
              className={`rounded-md bg-muted/50 p-3 overflow-x-auto ${
                toolCall.is_error ? "border-l-2 border-destructive" : ""
              }`}
            >
              {formatResult(toolCall.result)}
            </div>
          </CardContent>
        </Card>

        <Separator />

        {/* Metadata */}
        <div className="space-y-2">
          <p
            className="text-xs text-muted-foreground truncate"
            title={toolCall.tool_call_id}
          >
            ID: {toolCall.tool_call_id.slice(0, 12)}...
          </p>
          {stepEndTokenUsage && (
            <>
              <p className="text-xs text-muted-foreground">
                Tokens: {formatTokens(stepEndTokenUsage.total_tokens)} (prompt:{" "}
                {formatTokens(stepEndTokenUsage.prompt_tokens)}, completion:{" "}
                {formatTokens(stepEndTokenUsage.completion_tokens)})
              </p>
              {estimatedCost !== null && (
                <p className="text-xs font-medium text-primary">
                  Cost: {formatCost(estimatedCost)}
                </p>
              )}
            </>
          )}
        </div>
      </div>
    </ScrollArea>
  );
}

export default ToolDetail;
