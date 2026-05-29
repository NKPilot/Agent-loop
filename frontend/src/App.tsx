import { useEffect, useCallback } from "react";
import { TooltipProvider } from "@/components/ui/tooltip";
import { useUIStore } from "@/stores/uiStore";
import SessionList from "@/components/SessionList";
import AgentTimeline from "@/components/AgentTimeline";
import ConnectionStatus from "@/components/ConnectionStatus";

// ── App ───────────────────────────────────────────────────────────────

function App() {
  const setActiveSession = useUIStore((s) => s.setActiveSession);
  const activeSessionId = useUIStore((s) => s.activeSessionId);
  const clearPendingConfirmation = useUIStore((s) => s.clearPendingConfirmation);

  // ── Keyboard navigation ──────────────────────────────────────────────

  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      // Escape: close confirmation dialog (pre-registered for Plan 06)
      if (e.key === "Escape") {
        const pending = useUIStore.getState().pendingConfirmation;
        if (pending) {
          clearPendingConfirmation();
        }
        return;
      }

      // j / ArrowDown: next session (placeholder — sessions list navigation
      // is handled within SessionList component via focus management)
      // k / ArrowUp: previous session
      // These are registered for future interop with SessionList focus API

      // Enter: open selected session (when focus is on a session item,
      // handled by SessionItem's onKeyDown)
    },
    [clearPendingConfirmation]
  );

  useEffect(() => {
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [handleKeyDown]);

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
            <SessionList />
          </aside>

          {/* Center panel: Agent Timeline — flex-1 */}
          <section className="flex flex-1 flex-col bg-card">
            <div className="border-b border-border px-4 py-3">
              <h2 className="text-[20px] font-semibold leading-tight">Agent Timeline</h2>
            </div>
            <AgentTimeline />
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
