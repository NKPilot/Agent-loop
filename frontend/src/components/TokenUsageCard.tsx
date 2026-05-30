/**
 * TokenUsageCard — Token/成本摘要卡片 + recharts 图表组件。
 *
 * 功能：显示 prompt/completion token 数量、预估成本、上下文窗口进度条、
 * AreaChart 累积成本曲线和 PieChart token 拆分。
 * 满足 OBS-04 Token/成本追踪需求。
 */

import { useMemo } from "react";
import { useUIStore } from "@/stores/uiStore";
import { useEventStore } from "@/stores/eventStore";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { calculateCost, formatCost, formatTokens } from "@/lib/costCalculator";
import type { Event, StepEndEvent, TokenWarningEvent } from "@/lib/eventTypes";
import {
  AreaChart,
  Area,
  PieChart,
  Pie,
  Cell,
  ResponsiveContainer,
  XAxis,
  YAxis,
  Tooltip as RechartsTooltip,
  Legend,
} from "recharts";

// ── Color palette ───────────────────────────────────────────────────────

const PRIMARY_COLOR = "hsl(var(--primary))";
const SUCCESS_COLOR = "#16a34a";
const MUTED_COLOR = "hsl(var(--muted-foreground))";

// ── Data extraction helpers ──────────────────────────────────────────────

interface TokenMetrics {
  totalPromptTokens: number;
  totalCompletionTokens: number;
  totalTokens: number;
  estimatedCost: number;
  contextUsedPct: number;
}

function extractMetrics(events: readonly Event[]): TokenMetrics {
  let totalPromptTokens = 0;
  let totalCompletionTokens = 0;
  let contextUsedPct = 0;

  // Latest token warning for context window percentage
  let latestWarningPct = 0;

  for (const event of events) {
    if (event.event_type === "step_end") {
      if (event.token_usage) {
        totalPromptTokens += event.token_usage.prompt_tokens;
        totalCompletionTokens += event.token_usage.completion_tokens;
      }
    }

    if (event.event_type === "token_warning") {
      if (event.used_pct) {
        latestWarningPct = Math.max(latestWarningPct, event.used_pct);
      }
    }
  }

  const totalTokens = totalPromptTokens + totalCompletionTokens;
  const estimatedCost = calculateCost(totalPromptTokens, totalCompletionTokens);

  // Context window: use token warning pct, or estimate from total / 128000
  if (latestWarningPct > 0) {
    contextUsedPct = latestWarningPct;
  } else if (totalTokens > 0) {
    contextUsedPct = Math.min(100, Math.round((totalTokens / 128000) * 100));
  }

  return { totalPromptTokens, totalCompletionTokens, totalTokens, estimatedCost, contextUsedPct };
}

interface AreaDataPoint {
  step: number;
  cumulativeCost: number;
}

function buildAreaChartData(events: readonly Event[]): AreaDataPoint[] {
  const dataPoints: AreaDataPoint[] = [];
  let runningCost = 0;

  for (const event of events) {
    if (event.event_type === "step_end") {
      const stepNum = event.step_num;
      if (event.token_usage) {
        runningCost += calculateCost(
          event.token_usage.prompt_tokens,
          event.token_usage.completion_tokens
        );
      }
      dataPoints.push({ step: stepNum, cumulativeCost: Number(runningCost.toFixed(6)) });
    }
  }

  return dataPoints;
}

// ── Context window color ────────────────────────────────────────────────

function contextBarColor(pct: number): string {
  if (pct >= 90) return "bg-red-500";
  if (pct >= 75) return "bg-amber-500";
  return "bg-primary";
}

// ── TokenUsageCard ──────────────────────────────────────────────────────

function TokenUsageCard() {
  const activeSessionId = useUIStore((s) => s.activeSessionId);
  const eventsBySession = useEventStore((s) => s.eventsBySession);

  const events = activeSessionId ? (eventsBySession[activeSessionId] ?? []) : [];

  const metrics = useMemo(() => extractMetrics(events), [events]);
  const areaData = useMemo(() => buildAreaChartData(events), [events]);

  // Pie chart data
  const pieData = useMemo(() => {
    if (metrics.totalTokens === 0) return [];
    return [
      { name: "Prompt", value: metrics.totalPromptTokens },
      { name: "Completion", value: metrics.totalCompletionTokens },
    ];
  }, [metrics]);

  const hasTokenData = metrics.totalTokens > 0;
  const hasWarning = events.some((e) => e.event_type === "token_warning");

  // ── Empty state ──────────────────────────────────────────────────────────

  if (!activeSessionId) {
    return (
      <div className="flex flex-1 items-center justify-center p-6">
        <p className="text-sm text-muted-foreground">
          Select a session to view token usage.
        </p>
      </div>
    );
  }

  if (!hasTokenData) {
    return (
      <div className="flex flex-1 items-center justify-center p-6">
        <p className="text-sm text-muted-foreground">
          No token data available yet.
        </p>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto p-4 space-y-4">
      {/* Summary Card */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-medium">Token Usage Summary</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <p className="text-xs text-muted-foreground">Prompt Tokens</p>
              <p className="text-sm font-mono">{formatTokens(metrics.totalPromptTokens)}</p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Completion Tokens</p>
              <p className="text-sm font-mono">{formatTokens(metrics.totalCompletionTokens)}</p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Total Tokens</p>
              <p className="text-sm font-mono">{formatTokens(metrics.totalTokens)}</p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Estimated Cost</p>
              <p className="text-sm font-mono text-primary font-semibold">{formatCost(metrics.estimatedCost)}</p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Context Window Progress */}
      <Card>
        <CardHeader className="pb-1">
          <div className="flex items-center justify-between">
            <CardTitle className="text-sm font-medium">Context Window</CardTitle>
            {hasWarning && (
              <Badge variant="outline" className="border-amber-400/50 text-amber-600 text-xs">
                Token {Math.round(metrics.contextUsedPct)}%
              </Badge>
            )}
          </div>
        </CardHeader>
        <CardContent>
          <div className="space-y-1">
            <div className="flex justify-between text-xs">
              <span className="text-muted-foreground">
                {Math.round(metrics.contextUsedPct)}% used
              </span>
            </div>
            <div className="relative flex h-1 w-full items-center overflow-hidden rounded-full bg-muted">
              <div
                className={`h-full transition-all ${contextBarColor(metrics.contextUsedPct)}`}
                style={{ width: `${Math.min(100, metrics.contextUsedPct)}%` }}
              />
            </div>
          </div>
        </CardContent>
      </Card>

      {/* AreaChart — Cumulative Cost */}
      {areaData.length > 0 && (
        <Card>
          <CardHeader className="pb-1">
            <CardTitle className="text-sm font-medium">Cumulative Cost</CardTitle>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={200}>
              <AreaChart data={areaData} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
                <defs>
                  <linearGradient id="costGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor={PRIMARY_COLOR} stopOpacity={0.3} />
                    <stop offset="95%" stopColor={PRIMARY_COLOR} stopOpacity={0.05} />
                  </linearGradient>
                </defs>
                <XAxis
                  dataKey="step"
                  tick={{ fontSize: 11 }}
                  stroke={MUTED_COLOR}
                  tickLine={false}
                  axisLine={false}
                  label={{ value: "Step", position: "insideBottomRight", offset: -5, fontSize: 11, fill: MUTED_COLOR }}
                />
                <YAxis
                  tick={{ fontSize: 11 }}
                  stroke={MUTED_COLOR}
                  tickLine={false}
                  axisLine={false}
                  tickFormatter={(v: number) => `$${v.toFixed(3)}`}
                  width={50}
                />
                <RechartsTooltip
                  // eslint-disable-next-line @typescript-eslint/no-explicit-any
                  formatter={(value: any) => {
                    if (typeof value === "number") return [`$${value.toFixed(4)}`, "Cost"];
                    return [String(value), "Cost"];
                  }}
                  // eslint-disable-next-line @typescript-eslint/no-explicit-any
                  labelFormatter={(label: any) => {
                    if (typeof label === "number") return `Step ${label}`;
                    return String(label);
                  }}
                />
                <Area
                  type="monotone"
                  dataKey="cumulativeCost"
                  stroke={PRIMARY_COLOR}
                  fill="url(#costGradient)"
                  strokeWidth={2}
                />
              </AreaChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      )}

      {/* PieChart — Token Breakdown */}
      {pieData.length > 0 && (
        <Card>
          <CardHeader className="pb-1">
            <CardTitle className="text-sm font-medium">Token Breakdown</CardTitle>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={180}>
              <PieChart>
                <Pie
                  data={pieData}
                  cx="50%"
                  cy="50%"
                  innerRadius={40}
                  outerRadius={70}
                  dataKey="value"
                  label={({ name, percent }: { name?: string; percent?: number }) =>
                    `${name ?? ""} ${((percent ?? 0) * 100).toFixed(0)}%`
                  }
                  labelLine={false}
                >
                  {pieData.map((entry, idx) => (
                    <Cell
                      key={idx}
                      fill={idx === 0 ? PRIMARY_COLOR : SUCCESS_COLOR}
                    />
                  ))}
                </Pie>
                <Legend
                  formatter={(value: string) => (
                    <span className="text-xs text-muted-foreground">{value}</span>
                  )}
                />
              </PieChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

export default TokenUsageCard;
