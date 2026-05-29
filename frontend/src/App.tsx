import { TooltipProvider } from "@/components/ui/tooltip";
import { useUIStore } from "@/stores/uiStore";
import type { SSEStatus } from "@/lib/eventTypes";

// ── SSE status indicator ──────────────────────────────────────────────

const SSE_STATUS_CONFIG: Record<
  SSEStatus,
  { dotClass: string; label: string; pulse: boolean }
> = {
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

function ConnectionStatus() {
  const sseStatus = useUIStore((s) => s.sseStatus);
  const config = SSE_STATUS_CONFIG[sseStatus];

  return (
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
      <span className="text-sm text-muted-foreground">{config.label}</span>
    </div>
  );
}

// ── App ───────────────────────────────────────────────────────────────

function App() {
  return (
    <TooltipProvider>
      <div className="flex min-h-screen flex-col bg-background text-foreground">
        {/* Top bar */}
        <header className="flex h-12 items-center justify-between border-b border-border px-6">
          <h1 className="text-[28px] font-semibold leading-tight tracking-tight">
            loopAI -- Observability Dashboard
          </h1>
          <ConnectionStatus />
        </header>

        {/* Three-panel body */}
        <main className="flex flex-1 min-w-[1024px] max-md:flex-col">
          {/* Left panel: Session List — 260px */}
          <aside className="flex w-[260px] shrink-0 flex-col border-r border-border bg-card">
            <div className="border-b border-border px-4 py-3">
              <h2 className="text-[20px] font-semibold leading-tight">Session List</h2>
            </div>
            <div className="flex flex-1 items-center justify-center p-6">
              <div className="text-center space-y-2">
                <p className="text-sm font-medium text-foreground">No Agent Sessions Yet</p>
                <p className="text-xs text-muted-foreground">
                  Start your first agent session to see real-time reasoning steps,
                  tool calls, and token usage right here.
                </p>
              </div>
            </div>
          </aside>

          {/* Center panel: Agent Timeline — flex-1 */}
          <section className="flex flex-1 flex-col bg-card">
            <div className="border-b border-border px-4 py-3">
              <h2 className="text-[20px] font-semibold leading-tight">Agent Timeline</h2>
            </div>
            <div className="flex flex-1 items-center justify-center p-6">
              <div className="text-center space-y-2">
                <p className="text-sm text-muted-foreground">
                  Select a session to view the agent timeline.
                </p>
              </div>
            </div>
          </section>

          {/* Right panel: Tool Detail — 360px */}
          <aside className="flex w-[360px] shrink-0 flex-col border-l border-border bg-card">
            <div className="border-b border-border px-4 py-3">
              <h2 className="text-[20px] font-semibold leading-tight">Tool Detail</h2>
            </div>
            <div className="flex flex-1 items-center justify-center p-6">
              <div className="text-center space-y-2">
                <p className="text-sm font-medium text-foreground">Select a tool call</p>
                <p className="text-xs text-muted-foreground">
                  Click any tool call in the timeline to view its arguments, result,
                  and performance metrics.
                </p>
              </div>
            </div>
          </aside>
        </main>
      </div>
    </TooltipProvider>
  );
}

export default App;
