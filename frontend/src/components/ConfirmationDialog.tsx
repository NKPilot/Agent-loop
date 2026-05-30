/**
 * ConfirmationDialog — 危险命令确认弹窗。
 *
 * 当 agent 执行危险操作（如 rm）时自动弹出 Dialog，显示命令详情、
 * 标记原因、超时倒计时，提供批准/拒绝操作。满足 D-06 需求。
 */

import { useState, useEffect, useCallback } from "react";
import { AlertTriangle, Loader2 } from "lucide-react";
import { useUIStore } from "@/stores/uiStore";
import { confirmCommand } from "@/lib/api";
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

const DEFAULT_TIMEOUT = 120;

function ConfirmationDialog() {
  const pendingConfirmation = useUIStore((s) => s.pendingConfirmation);
  const setPendingConfirmation = useUIStore((s) => s.setPendingConfirmation);

  const [isLoading, setIsLoading] = useState<"approve" | "reject" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [countdown, setCountdown] = useState(DEFAULT_TIMEOUT);

  const isOpen = pendingConfirmation !== null;

  // Reset state when dialog opens
  useEffect(() => {
    if (isOpen) {
      setIsLoading(null);
      setError(null);
      setCountdown(DEFAULT_TIMEOUT);
    }
  }, [isOpen]);

  // Countdown timer — auto-reject on timeout
  useEffect(() => {
    if (!isOpen || !pendingConfirmation) return;

    const timer = setInterval(() => {
      setCountdown((prev) => {
        if (prev <= 1) {
          clearInterval(timer);
          // Auto-reject on timeout
          const state = useUIStore.getState();
          const sessionId = state.activeSessionId;
          const confId = state.pendingConfirmation?.confirmation_id;
          if (sessionId && confId) {
            confirmCommand(sessionId, confId, false)
              .catch(() => {})
              .finally(() => {
                state.setPendingConfirmation(null);
              });
          }
          return 0;
        }
        return prev - 1;
      });
    }, 1000);

    return () => clearInterval(timer);
  }, [isOpen, pendingConfirmation]);

  const handleApprove = useCallback(async () => {
    if (!pendingConfirmation) return;
    const sessionId = useUIStore.getState().activeSessionId;
    if (!sessionId) return;

    setIsLoading("approve");
    setError(null);
    try {
      await confirmCommand(sessionId, pendingConfirmation.confirmation_id, true);
      setPendingConfirmation(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to approve command");
      setIsLoading(null);
    }
  }, [pendingConfirmation, setPendingConfirmation]);

  const handleReject = useCallback(async () => {
    if (!pendingConfirmation) return;
    const sessionId = useUIStore.getState().activeSessionId;
    if (!sessionId) return;

    setIsLoading("reject");
    setError(null);
    try {
      await confirmCommand(sessionId, pendingConfirmation.confirmation_id, false);
      setPendingConfirmation(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to reject command");
      setIsLoading(null);
    }
  }, [pendingConfirmation, setPendingConfirmation]);

  // Handle dialog close (Escape / outside click) as reject
  const handleOpenChange = useCallback(
    (open: boolean) => {
      if (!open && pendingConfirmation && isLoading === null) {
        const state = useUIStore.getState();
        const sessionId = state.activeSessionId;
        const confId = state.pendingConfirmation?.confirmation_id;
        if (sessionId && confId) {
          confirmCommand(sessionId, confId, false)
            .catch(() => {})
            .finally(() => {
              state.setPendingConfirmation(null);
            });
        }
      }
    },
    [pendingConfirmation, isLoading]
  );

  if (!pendingConfirmation) return null;

  return (
    <Dialog open={isOpen} onOpenChange={handleOpenChange}>
      <DialogContent
        className="sm:max-w-lg"
        showCloseButton={false}
      >
        <DialogHeader>
          <div className="flex items-center gap-2">
            <AlertTriangle className="size-5 text-destructive" />
            <DialogTitle>Dangerous Command</DialogTitle>
          </div>
          <DialogDescription>
            The agent wants to execute a potentially dangerous command. Review the
            command below and approve or reject it.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          {/* Permission level badge */}
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground">Permission Level:</span>
            <Badge variant="destructive">{pendingConfirmation.permission_level}</Badge>
          </div>

          {/* Tool name */}
          <div>
            <p className="text-xs text-muted-foreground mb-1">Tool</p>
            <p className="text-sm font-semibold">{pendingConfirmation.tool_name}</p>
          </div>

          {/* Command arguments */}
          <div>
            <p className="text-xs text-muted-foreground mb-1">Arguments</p>
            <ScrollArea className="max-h-[200px] rounded-md border">
              <pre className="font-mono text-xs whitespace-pre-wrap p-3">
                {JSON.stringify(pendingConfirmation.tool_args, null, 2)}
              </pre>
            </ScrollArea>
          </div>

          {/* Reason */}
          {pendingConfirmation.reason && (
            <Alert
              variant="default"
              className="border-amber-400/50 bg-amber-50/50 dark:bg-amber-950/20"
            >
              <AlertTriangle className="size-3.5 text-amber-600" />
              <AlertDescription className="text-xs text-amber-700 dark:text-amber-400">
                {pendingConfirmation.reason}
              </AlertDescription>
            </Alert>
          )}

          {/* Countdown */}
          <p className="text-xs text-muted-foreground text-center">
            Auto-rejecting in {countdown} seconds
          </p>
        </div>

        {/* Error message */}
        {error && (
          <Alert variant="destructive">
            <AlertDescription className="text-xs">{error}</AlertDescription>
          </Alert>
        )}

        {/* Action buttons */}
        <DialogFooter className="flex gap-2 sm:justify-end">
          <Button
            variant="outline"
            onClick={handleReject}
            disabled={isLoading !== null}
          >
            {isLoading === "reject" && <Loader2 className="size-3.5 animate-spin" />}
            Reject Command
          </Button>
          <Button
            variant="destructive"
            onClick={handleApprove}
            disabled={isLoading !== null}
          >
            {isLoading === "approve" && <Loader2 className="size-3.5 animate-spin" />}
            Approve Command
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default ConfirmationDialog;
