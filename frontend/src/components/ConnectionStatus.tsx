import { useCallback } from "react";
import { AlertTriangle } from "lucide-react";
import { useUIStore } from "@/stores/uiStore";
import type { SSEStatus } from "@/lib/eventTypes";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";

// ── Status config ────────────────────────────────────────────────────────

interface StatusConfig {
  dotClass: string;
  label: string;
  pulse: boolean;
}

const SSE_STATUS_CONFIG: Record<SSEStatus, StatusConfig> = {
  connected: {
    dotClass: "bg-green-500",
    label: "Live",
    pulse: false,
  },
  connecting: {
    dotClass: "bg-amber-400",
    label: "Connecting...",
    pulse: true,
  },
  reconnecting: {
    dotClass: "bg-red-500",
    label: "Reconnecting...",
    pulse: true,
  },
  failed: {
    dotClass: "bg-red-600",
    label: "Connection Failed",
    pulse: false,
  },
};

// ── ConnectionStatus ─────────────────────────────────────────────────────

function ConnectionStatus() {
  const sseStatus = useUIStore((s) => s.sseStatus);
  const retryCount = useUIStore((s) => s.sseRetryCount);
  const config = SSE_STATUS_CONFIG[sseStatus];

  const handleRetry = useCallback(() => {
    // Reload the page to trigger a fresh SSE connection
    window.location.reload();
  }, []);

  const label =
    sseStatus === "reconnecting"
      ? `Reconnecting (attempt ${retryCount})...`
      : config.label;

  return (
    <div className="flex flex-col">
      {/* Inline indicator in header */}
      <div className="flex items-center gap-2">
        <span className="relative flex h-2.5 w-2.5">
          {config.pulse && (
            <span
              className={`absolute inline-flex h-full w-full animate-ping rounded-full opacity-75 ${config.dotClass}`}
            />
          )}
          <span
            className={`relative inline-flex h-2.5 w-2.5 rounded-full ${config.dotClass}`}
          />
        </span>
        <span className="text-sm text-muted-foreground">{label}</span>
      </div>

      {/* Alert banner for reconnecting / failed states */}
      {(sseStatus === "reconnecting" || sseStatus === "failed") && (
        <Alert
          variant={sseStatus === "failed" ? "destructive" : "default"}
          className="mt-2 border-amber-400/50 bg-amber-50/50 dark:bg-amber-950/20"
        >
          <AlertTriangle className="size-3.5 text-amber-600" />
          <AlertDescription className="text-xs">
            {sseStatus === "failed"
              ? "The live stream was interrupted and could not reconnect. Check that the backend server is running."
              : `The live stream was interrupted. Reconnecting automatically... (attempt ${retryCount})`}
          </AlertDescription>
          {sseStatus === "failed" && (
            <Button
              variant="outline"
              size="xs"
              className="mt-1"
              onClick={handleRetry}
            >
              Retry Now
            </Button>
          )}
        </Alert>
      )}
    </div>
  );
}

export default ConnectionStatus;
