import { useEffect, useCallback, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Loader2 } from "lucide-react";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { useUIStore } from "@/stores/uiStore";
import { useEventStore } from "@/stores/eventStore";
import { useSessionEvents } from "@/hooks/useSessionEvents";
import { startSession } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Alert, AlertDescription } from "@/components/ui/alert";
import SessionList from "@/components/SessionList";
import AgentTimeline from "@/components/AgentTimeline";
import ConnectionStatus from "@/components/ConnectionStatus";
import ToolDetail from "@/components/ToolDetail";
import TokenUsageCard from "@/components/TokenUsageCard";
import ConfirmationDialog from "@/components/ConfirmationDialog";
import { ScrollArea } from "@/components/ui/scroll-area";

// ── App ───────────────────────────────────────────────────────────────

function App() {
  const setActiveSession = useUIStore((s) => s.setActiveSession);
  const activeSessionId = useUIStore((s) => s.activeSessionId);
  const clearPendingConfirmation = useUIStore((s) => s.clearPendingConfirmation);
  const eventsBySession = useEventStore((s) => s.eventsBySession);
  const [activeTab, setActiveTab] = useState("timeline");

  // ── Start Agent state and handler ─────────────────────────────────────
  const queryClient = useQueryClient();
  const [prompt, setPrompt] = useState("");
  const [maxSteps, setMaxSteps] = useState(15);
  const [isStarting, setIsStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);

  // Connect SSE stream when an active session is set
  useSessionEvents(activeSessionId);

  const handleStartSession = useCallback(async () => {
    const trimmed = prompt.trim();
    if (!trimmed) return;

    setIsStarting(true);
    setStartError(null);
    try {
      clearPendingConfirmation();
      setActiveSession(null);
      const { session_id } = await startSession(trimmed, maxSteps);
      setActiveSession(session_id);
      queryClient.invalidateQueries({ queryKey: ["sessions"] });
      setPrompt("");
    } catch (err) {
      setStartError(
        err instanceof Error ? err.message : "启动 agent 会话失败"
      );
    } finally {
      setIsStarting(false);
    }
  }, [prompt, maxSteps, setActiveSession, clearPendingConfirmation, queryClient]);

  // Raw events data for the Raw Events tab
  const rawEvents = activeSessionId ? (eventsBySession[activeSessionId] ?? []) : [];

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

      // Tab switching: t -> Timeline, u -> Token Usage, r -> Raw Events
      if (e.key === "t") { setActiveTab("timeline"); return; }
      if (e.key === "u") { setActiveTab("token-usage"); return; }
      if (e.key === "r") { setActiveTab("raw-events"); return; }

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
          {/* Left panel: Session List + Start Agent — 260px */}
          <aside className="flex w-[260px] shrink-0 flex-col border-r border-border bg-card">
            <div className="border-b border-border px-4 py-3">
              <h2 className="text-[20px] font-semibold leading-tight">Session List</h2>
            </div>

            {/* Start Agent form */}
            <div className="border-b border-border space-y-2 px-3 py-3">
              <Input
                placeholder="Enter your prompt for the agent..."
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                disabled={isStarting}
                className="h-8 text-xs"
              />
              <div className="flex items-center gap-2">
                <Input
                  type="number"
                  placeholder="Steps"
                  value={maxSteps}
                  onChange={(e) => setMaxSteps(Number(e.target.value))}
                  disabled={isStarting}
                  className="h-8 w-[72px] text-xs"
                  min={1}
                  max={200}
                />
                <Button
                  size="sm"
                  className="flex-1 h-8 text-xs"
                  onClick={handleStartSession}
                  disabled={isStarting || !prompt.trim()}
                >
                  {isStarting && <Loader2 className="size-3.5 animate-spin mr-1" />}
                  Start Agent
                </Button>
              </div>
              {startError && (
                <Alert variant="destructive" className="py-2 px-3">
                  <AlertTriangle className="size-3" />
                  <AlertDescription className="text-xs">{startError}</AlertDescription>
                </Alert>
              )}
            </div>

            <SessionList />
          </aside>

          {/* Center panel: Tabs (Timeline / Token Usage / Raw Events) — flex-1 */}
          <section className="flex flex-1 flex-col bg-card overflow-hidden">
            <div className="border-b border-border px-4 py-3">
              <Tabs value={activeTab} onValueChange={setActiveTab}>
                <TabsList>
                  <TabsTrigger value="timeline">Timeline</TabsTrigger>
                  <TabsTrigger value="token-usage">Token Usage</TabsTrigger>
                  <TabsTrigger value="raw-events">Raw Events</TabsTrigger>
                </TabsList>
              </Tabs>
            </div>

            <div className="flex flex-1 overflow-hidden">
              {activeTab === "timeline" && <AgentTimeline />}
              {activeTab === "token-usage" && <TokenUsageCard />}
              {activeTab === "raw-events" && (
                <ScrollArea className="h-full w-full">
                  <pre className="p-4 text-xs font-mono whitespace-pre-wrap">
                    {rawEvents.length === 0
                      ? "No events yet."
                      : rawEvents.map((event, i) => JSON.stringify(event, null, 2)).join("\n\n")}
                  </pre>
                </ScrollArea>
              )}
            </div>
          </section>

          {/* Right panel: Tool Detail — 360px */}
          <aside className="flex w-[360px] shrink-0 flex-col border-l border-border bg-card">
            <div className="border-b border-border px-4 py-3">
              <h2 className="text-[20px] font-semibold leading-tight">Tool Detail</h2>
            </div>
            <ToolDetail />
          </aside>
        </main>

        {/* Confirmation Dialog (portal — renders to document.body) */}
        <ConfirmationDialog />
      </div>
    </TooltipProvider>
  );
}

export default App;
