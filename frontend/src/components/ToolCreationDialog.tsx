/**
 * ToolCreationDialog — 动态工具创建确认弹窗。
 *
 * 当 Agent 提议创建新动态工具时弹出 Dialog，展示工具源代码（Monaco Editor）、
 * 风险评估标记、自测代码预览、持久化级别选择、目录权限配置，并展示自测执行结果。
 *
 * 满足 DYN-03, DYN-05, DYN-06, DYN-07, DYN-08, DYN-10 需求。
 */

import { useState, useEffect, useCallback } from "react";
import {
  Hammer, ShieldAlert, Code2, TestTube, HardDrive, FolderOpen,
  ChevronDown, ChevronUp, CheckCircle2, XCircle, Clock,
  Loader2, BadgeCheck, AlertTriangle,
} from "lucide-react";
import Editor from "@monaco-editor/react";
import { useUIStore } from "@/stores/uiStore";
import { confirmToolCreation } from "@/lib/api";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { ScrollArea } from "@/components/ui/scroll-area";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";

// ── Helpers ──────────────────────────────────────────────────────────────

/** 将用户输入的目录字符串解析为路径数组 */
function parseExtraDirs(input: string): string[] {
  return input
    .split(/[\s,]+/)
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}

/** 获取风险严重程度对应的 Badge variant */
function riskBadgeVariant(severity: "high" | "medium" | "low") {
  switch (severity) {
    case "high":
      return "destructive" as const;
    case "medium":
      return "default" as const;
    case "low":
      return "secondary" as const;
  }
}

// ── Component ─────────────────────────────────────────────────────────────

function ToolCreationDialog() {
  // ── Store subscriptions ─────────────────────────────────────────────────
  const pendingToolCreation = useUIStore((s) => s.pendingToolCreation);
  const toolCreationTestResult = useUIStore((s) => s.toolCreationTestResult);
  const approveLoading = useUIStore((s) => s.toolCreationApproveLoading);
  const rejectLoading = useUIStore((s) => s.toolCreationRejectLoading);
  const storeError = useUIStore((s) => s.toolCreationError);
  const sseStatus = useUIStore((s) => s.sseStatus);

  // ── Local state ─────────────────────────────────────────────────────────
  const [persistence, setPersistence] = useState<"session" | "sandbox" | "project">("session");
  const [extraDirsInput, setExtraDirsInput] = useState("");
  const [testCodeExpanded, setTestCodeExpanded] = useState(false);

  const isOpen = pendingToolCreation !== null;
  const event = pendingToolCreation;

  // ── Reset local state when dialog opens ─────────────────────────────────
  useEffect(() => {
    if (isOpen) {
      setPersistence("session");
      setExtraDirsInput("");
      setTestCodeExpanded(false);
    }
  }, [isOpen]);

  // ── Handle approve ──────────────────────────────────────────────────────
  const handleApprove = useCallback(async () => {
    if (!event) return;
    const state = useUIStore.getState();
    const sessionId = state.activeSessionId;
    if (!sessionId) return;

    state.setToolCreationApproveLoading(true);
    state.setToolCreationError(null);
    try {
      await confirmToolCreation(
        sessionId,
        event.confirmation_id,
        true,
        persistence,
        parseExtraDirs(extraDirsInput),
      );
      // On success: keep dialog open, waiting for SSE test_result + tool_created
      state.setToolCreationApproveLoading(false);
    } catch (err) {
      state.setToolCreationError(
        err instanceof Error ? err.message : "Failed to approve tool creation",
      );
      state.setToolCreationApproveLoading(false);
    }
  }, [event, persistence, extraDirsInput]);

  // ── Handle reject ───────────────────────────────────────────────────────
  const handleReject = useCallback(async () => {
    if (!event) return;
    const state = useUIStore.getState();
    const sessionId = state.activeSessionId;
    if (!sessionId) return;

    state.setToolCreationRejectLoading(true);
    state.setToolCreationError(null);
    try {
      await confirmToolCreation(
        sessionId,
        event.confirmation_id,
        false,
        "session",
        [],
      );
      state.clearPendingToolCreation();
    } catch (err) {
      state.setToolCreationError(
        err instanceof Error ? err.message : "Failed to reject tool creation",
      );
      state.setToolCreationRejectLoading(false);
    }
  }, [event]);

  // ── Handle dialog close (Escape / backdrop) as reject ──────────────────
  const handleOpenChange = useCallback(
    (open: boolean) => {
      if (!open && event && !approveLoading && !rejectLoading) {
        const state = useUIStore.getState();
        const sessionId = state.activeSessionId;
        const confId = event.confirmation_id;
        if (sessionId && confId) {
          confirmToolCreation(sessionId, confId, false, "session", [])
            .catch(() => {})
            .finally(() => {
              state.clearPendingToolCreation();
            });
        }
      }
    },
    [event, approveLoading, rejectLoading],
  );

  // ── Don't render if no pending tool creation ────────────────────────────
  if (!event) return null;

  const isLoading = approveLoading || rejectLoading;

  // ── Render ──────────────────────────────────────────────────────────────
  return (
    <Dialog open={isOpen} onOpenChange={handleOpenChange}>
      <DialogContent
        className="sm:max-w-2xl lg:max-w-3xl max-h-[90vh]"
        showCloseButton={false}
      >
        {/* ── Dialog Header ──────────────────────────────────────────────── */}
        <DialogHeader>
          <div className="flex items-center gap-2">
            <Hammer className="size-5 text-primary" />
            <DialogTitle>Tool Creation</DialogTitle>
          </div>
          <DialogDescription>
            The agent has proposed a new dynamic tool. Review the code, risk
            assessment, and test plan before approving.
          </DialogDescription>
        </DialogHeader>

        <ScrollArea className="max-h-[calc(90vh-12rem)]">
          <div className="space-y-4 px-1">
            {/* ── Zone 1: Tool Metadata ──────────────────────────────────── */}
            <div className="space-y-2">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-sm font-semibold">{event.tool_name}</span>
                <Badge variant="secondary" className="text-xs">
                  {event.language === "python" ? "Python" : "Bash"}
                </Badge>
              </div>
              <p className="text-sm text-muted-foreground">
                {event.description}
              </p>
            </div>

            <Separator />

            {/* ── Zone 2: Source Code ────────────────────────────────────── */}
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <Code2 className="size-4 text-muted-foreground" />
                <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                  Source Code
                </span>
              </div>
              <div className="border rounded-md overflow-hidden min-h-[240px] max-h-[480px]">
                <Editor
                  height="240px"
                  language={event.language === "python" ? "python" : "shell"}
                  value={event.code}
                  theme="vs-dark"
                  options={{
                    readOnly: true,
                    minimap: { enabled: false },
                    lineNumbers: "on",
                    scrollBeyondLastLine: false,
                    wordWrap: "on",
                    fontSize: 13,
                    fontFamily:
                      "'Cascadia Code', 'Fira Code', 'JetBrains Mono', monospace",
                    padding: { top: 12, bottom: 12 },
                  }}
                  loading={
                    <Skeleton className="h-[240px] w-full rounded-md" />
                  }
                />
              </div>
            </div>

            <Separator />

            {/* ── Zone 3: Risk Assessment ────────────────────────────────── */}
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <ShieldAlert className="size-4 text-muted-foreground" />
                <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                  Risk Assessment
                </span>
              </div>
              <div className="flex flex-wrap gap-2">
                {event.risk_flags.length === 0 ? (
                  <Badge
                    variant="default"
                    className="bg-green-600/20 text-green-600 dark:text-green-400 border-green-600/30"
                  >
                    <BadgeCheck className="size-3.5 mr-1" />
                    No Risks Detected
                  </Badge>
                ) : (
                  event.risk_flags.map((flag, idx) => (
                    <Badge
                      key={idx}
                      variant={riskBadgeVariant(flag.severity)}
                      className={
                        flag.severity === "medium"
                          ? "text-amber-600 dark:text-amber-400 border-amber-600/30"
                          : ""
                      }
                      aria-label={`${flag.severity} risk: ${flag.name}`}
                    >
                      {flag.severity === "high" && (
                        <ShieldAlert className="size-3 mr-1" />
                      )}
                      {flag.name}
                    </Badge>
                  ))
                )}
              </div>
            </div>

            <Separator />

            {/* ── Zone 4: Self-Test Code ─────────────────────────────────── */}
            <div className="space-y-2">
              <button
                type="button"
                onClick={() => setTestCodeExpanded((prev) => !prev)}
                className="flex items-center gap-2 w-full text-left hover:text-foreground transition-colors"
              >
                <TestTube className="size-4 text-muted-foreground" />
                <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                  Self-Test Code
                </span>
                <span className="ml-auto">
                  {testCodeExpanded ? (
                    <ChevronUp className="size-4 text-muted-foreground" />
                  ) : (
                    <ChevronDown className="size-4 text-muted-foreground" />
                  )}
                </span>
              </button>
              {testCodeExpanded && (
                <div className="border rounded-md overflow-hidden max-h-[200px]">
                  <Editor
                    height="160px"
                    language={event.language === "python" ? "python" : "shell"}
                    value={event.test_code}
                    theme="vs-dark"
                    options={{
                      readOnly: true,
                      minimap: { enabled: false },
                      lineNumbers: "on",
                      scrollBeyondLastLine: false,
                      wordWrap: "on",
                      fontSize: 12,
                    }}
                    loading={
                      <Skeleton className="h-[160px] w-full rounded-md" />
                    }
                  />
                </div>
              )}
            </div>

            <Separator />

            {/* ── Zone 5: Persistence ────────────────────────────────────── */}
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <HardDrive className="size-4 text-muted-foreground" />
                <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                  Persistence
                </span>
              </div>
              <RadioGroup
                value={persistence}
                onValueChange={(v) =>
                  setPersistence(v as "session" | "sandbox" | "project")
                }
                aria-label="Persistence level"
              >
                <div className="flex items-center space-x-2">
                  <RadioGroupItem value="session" id="pers-session" />
                  <div>
                    <Label htmlFor="pers-session">Session</Label>
                    <p className="text-xs text-muted-foreground">
                      Removed when the session ends
                    </p>
                  </div>
                </div>
                <div className="flex items-center space-x-2">
                  <RadioGroupItem value="sandbox" id="pers-sandbox" />
                  <div>
                    <Label htmlFor="pers-sandbox">Sandbox</Label>
                    <p className="text-xs text-muted-foreground">
                      Saved to .sandbox/tools/ and loaded on next session
                    </p>
                  </div>
                </div>
                <div className="flex items-center space-x-2">
                  <RadioGroupItem value="project" id="pers-project" />
                  <div>
                    <Label htmlFor="pers-project">Project</Label>
                    <p className="text-xs text-muted-foreground">
                      Saved to src/loopai/tools/dynamic/ — can be committed to
                      git
                    </p>
                  </div>
                </div>
              </RadioGroup>
            </div>

            <Separator />

            {/* ── Zone 6: Directory Access ───────────────────────────────── */}
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <FolderOpen className="size-4 text-muted-foreground" />
                <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                  Directory Access
                </span>
              </div>
              <Input
                placeholder="e.g. /home/user/projects/data"
                value={extraDirsInput}
                onChange={(e) => setExtraDirsInput(e.target.value)}
                disabled={isLoading}
              />
              <p className="text-xs text-muted-foreground">
                Additional directories the tool can read or write. Leave empty
                for sandbox-only access.
              </p>
            </div>

            {/* ── Zone 7: Self-Test Result ───────────────────────────────── */}
            {(() => {
              // Show loading state when waiting for test result (after approve, before result arrives)
              if (approveLoading) {
                return (
                  <div className="space-y-2">
                    <Separator />
                    <div className="flex items-center gap-2">
                      <Loader2 className="size-4 text-muted-foreground animate-spin" />
                      <span className="text-xs text-muted-foreground">
                        Running self-test...
                      </span>
                    </div>
                    <Skeleton className="h-16 w-full rounded-md" />
                  </div>
                );
              }

              if (!toolCreationTestResult) return null;

              const result = toolCreationTestResult;
              const isPassed = result.status === "passed";
              const isFailed = result.status === "failed";
              const isTimeout = result.status === "timeout";

              return (
                <>
                  <Separator />
                  <Alert
                    variant={isPassed ? "default" : isFailed ? "destructive" : "default"}
                    className={
                      isPassed
                        ? "border-green-600/30 bg-green-600/10"
                        : isTimeout
                          ? "border-amber-400/50 bg-amber-50/50 dark:bg-amber-950/20"
                          : ""
                    }
                  >
                    <div className="flex items-start gap-2">
                      {isPassed && (
                        <CheckCircle2 className="size-4 text-green-600 dark:text-green-400 mt-0.5" />
                      )}
                      {isFailed && (
                        <XCircle className="size-4 text-destructive mt-0.5" />
                      )}
                      {isTimeout && (
                        <Clock className="size-4 text-amber-600 mt-0.5" />
                      )}
                      <div className="space-y-1 flex-1">
                        <AlertDescription className="text-xs font-semibold">
                          {isPassed &&
                            `Self-test passed in ${result.duration_ms}ms`}
                          {isFailed && "Self-test failed"}
                          {isTimeout &&
                            `Self-test timed out after ${Math.round(result.duration_ms / 1000)}s`}
                        </AlertDescription>
                        {result.output && (
                          <ScrollArea className="max-h-[160px] rounded-md border bg-background/50">
                            <pre className="font-mono text-xs whitespace-pre-wrap p-3">
                              {result.output}
                            </pre>
                          </ScrollArea>
                        )}
                        {result.error && (
                          <p className="text-xs text-destructive dark:text-red-400">
                            {result.error}
                          </p>
                        )}
                      </div>
                    </div>
                  </Alert>
                </>
              );
            })()}
          </div>
        </ScrollArea>

        {/* ── Error / Warning ────────────────────────────────────────────── */}
        {storeError && (
          <Alert variant="destructive" role="alert">
            <AlertTriangle className="size-4" />
            <AlertDescription className="text-xs">
              Failed to approve tool: {storeError}. Please try again.
            </AlertDescription>
          </Alert>
        )}

        {sseStatus === "failed" && isOpen && !storeError && (
          <Alert
            variant="default"
            className="border-amber-400/50 bg-amber-50/50 dark:bg-amber-950/20"
          >
            <AlertTriangle className="size-4 text-amber-600" />
            <AlertDescription className="text-xs">
              Connection lost. The tool request is still pending. Reconnect to
              continue.
            </AlertDescription>
          </Alert>
        )}

        {/* ── Dialog Footer ──────────────────────────────────────────────── */}
        <DialogFooter className="flex gap-2 sm:justify-end">
          <Button
            variant="destructive"
            onClick={handleReject}
            disabled={isLoading}
            aria-busy={rejectLoading}
          >
            {rejectLoading && <Loader2 className="size-3.5 animate-spin" />}
            Reject Tool
          </Button>
          <Button
            variant="default"
            onClick={handleApprove}
            disabled={isLoading}
            aria-busy={approveLoading}
          >
            {approveLoading && <Loader2 className="size-3.5 animate-spin" />}
            Approve Tool
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default ToolCreationDialog;
