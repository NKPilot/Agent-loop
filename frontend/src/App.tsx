import { useEffect, useCallback, useMemo, useState, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { History, Plus, Send, Loader2, ArrowDown } from "lucide-react";
import { TooltipProvider } from "@/components/ui/tooltip";
import { useUIStore } from "@/stores/uiStore";
import { useEventStore } from "@/stores/eventStore";
import { useSessionEvents } from "@/hooks/useSessionEvents";
import { startSession, sendMessage } from "@/lib/api";
import { Button } from "@/components/ui/button";
import ConnectionStatus from "@/components/ConnectionStatus";
import ConfirmationDialog from "@/components/ConfirmationDialog";
import SessionList from "@/components/SessionList";
import StepCard, { type StepGroup, groupEventsByStep } from "@/components/StepCard";
import type { Event, UserMessageEvent } from "@/lib/eventTypes";

// ── Round display type ──────────────────────────────────────────────────

type RoundDisplay = {
  round_num: number;
  userMessage: UserMessageEvent | null;
  agentEvents: Event[];
};

// ── App ────────────────────────────────────────────────────────────────

function App() {
  const queryClient = useQueryClient();

  const activeSessionId = useUIStore((s) => s.activeSessionId);
  const setActiveSession = useUIStore((s) => s.setActiveSession);
  const eventsBySession = useEventStore((s) => s.eventsBySession);
  const toolCallsBySession = useEventStore((s) => s.toolCallsBySession);
  const messageInput = useUIStore((s) => s.messageInput);
  const setMessageInput = useUIStore((s) => s.setMessageInput);
  const clearPendingConfirmation = useUIStore((s) => s.clearPendingConfirmation);

  const [isSending, setIsSending] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [startPrompt, setStartPrompt] = useState("");
  const [isAtBottom, setIsAtBottom] = useState(true);
  const streamEndRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);

  // Connect SSE stream when an active session is set
  useSessionEvents(activeSessionId);

  // ── Round grouping ────────────────────────────────────────────────────

  const rounds = useMemo<RoundDisplay[]>(() => {
    if (!activeSessionId) return [];
    const events = eventsBySession[activeSessionId] ?? [];

    const result: RoundDisplay[] = [];
    let currentEvents: Event[] = [];
    let currentUserMsg: UserMessageEvent | null = null;

    for (const event of events) {
      if (event.event_type === "user_message") {
        if (currentUserMsg || currentEvents.length > 0) {
          result.push({ round_num: result.length + 1, userMessage: currentUserMsg, agentEvents: currentEvents });
        }
        currentUserMsg = event as UserMessageEvent;
        currentEvents = [];
      } else if (event.event_type === "round_end") {
        currentEvents.push(event);
        result.push({ round_num: result.length + 1, userMessage: currentUserMsg, agentEvents: currentEvents });
        currentUserMsg = null;
        currentEvents = [];
      } else {
        currentEvents.push(event);
      }
    }

    // Flush remaining events (active round, no round_end yet)
    if (currentUserMsg || currentEvents.length > 0) {
      result.push({ round_num: result.length + 1, userMessage: currentUserMsg, agentEvents: currentEvents });
    }

    return result;
  }, [eventsBySession, activeSessionId]);

  // ── Handlers ──────────────────────────────────────────────────────────

  const handleNewChat = useCallback(() => {
    setActiveSession(null);
    setShowHistory(false);
  }, [setActiveSession]);

  const handleStartSession = useCallback(async () => {
    const trimmed = startPrompt.trim();
    if (!trimmed) return;
    setIsSending(true);
    try {
      setActiveSession(null);
      const { session_id } = await startSession(trimmed);
      setActiveSession(session_id);
      setStartPrompt("");
      queryClient.invalidateQueries({ queryKey: ["sessions"] });
    } catch (err) {
      console.error("Failed to start session:", err);
    } finally {
      setIsSending(false);
    }
  }, [startPrompt, setActiveSession, queryClient]);

  const handleSendMessage = useCallback(async () => {
    const trimmed = messageInput.trim();
    if (!trimmed || !activeSessionId || isSending) return;
    setIsSending(true);
    try {
      await sendMessage(activeSessionId, trimmed);
      setMessageInput("");
    } catch (err) {
      console.error("Failed to send message:", err);
    } finally {
      setIsSending(false);
    }
  }, [messageInput, activeSessionId, isSending, setMessageInput]);

  // ── Agent thinking indicator ──────────────────────────────────────────

  const isAgentThinking = useMemo(() => {
    if (!activeSessionId) return false;
    const lastRound = rounds[rounds.length - 1];
    if (!lastRound) return false;
    const hasRoundEnd = lastRound.agentEvents.some((e) => e.event_type === "round_end");
    return !hasRoundEnd && lastRound.agentEvents.length > 0;
  }, [activeSessionId, rounds]);

  // ── Keyboard navigation ──────────────────────────────────────────────

  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        const pending = useUIStore.getState().pendingConfirmation;
        if (pending) {
          clearPendingConfirmation();
        }
        return;
      }
    },
    [clearPendingConfirmation]
  );

  useEffect(() => {
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [handleKeyDown]);

  // ── Start screen (no active session) ─────────────────────────────────

  const startScreen = !activeSessionId && (
    <div className="flex-1 flex items-center justify-center px-4">
      <div className="text-center space-y-4 max-w-md">
        <h2 className="text-xl font-semibold">Start a conversation</h2>
        <p className="text-sm text-muted-foreground">
          Send a message to begin interacting with the agent.
        </p>
        <div className="flex gap-2">
          <textarea
            value={startPrompt}
            onChange={(e) => setStartPrompt(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleStartSession();
              }
            }}
            placeholder="Type your first message..."
            className="flex-1 resize-none rounded-xl border border-border bg-card px-4 py-3 text-sm
                       placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary
                       min-h-[44px] max-h-[200px]"
            rows={2}
            disabled={isSending}
          />
          <Button
            onClick={handleStartSession}
            disabled={!startPrompt.trim() || isSending}
            className="self-end h-[44px] rounded-xl"
          >
            {isSending ? <Loader2 className="size-4 animate-spin" /> : "Start"}
          </Button>
        </div>
      </div>
    </div>
  );

  // ── Auto-scroll ──────────────────────────────────────────────────────

  useEffect(() => {
    if (isAtBottom && streamEndRef.current) {
      streamEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [rounds, isAtBottom]);

  const handleScroll = useCallback(() => {
    const container = scrollContainerRef.current;
    if (!container) return;
    const scrollBottom = container.scrollHeight - container.scrollTop - container.clientHeight;
    setIsAtBottom(scrollBottom < 50);
  }, []);

  // ── Message stream ───────────────────────────────────────────────────

  const messageStream = activeSessionId && (
    <div
      className="flex-1 overflow-y-auto px-4 py-6"
      ref={scrollContainerRef}
      onScroll={handleScroll}
    >
      <div className="max-w-3xl mx-auto space-y-8">
        {rounds.length === 0 && (
          <div className="flex items-center justify-center h-full py-20">
            <p className="text-sm text-muted-foreground italic">
              Waiting for agent response...
            </p>
          </div>
        )}

        {rounds.map((round) => {
          const roundSteps = groupEventsByStep(round.agentEvents);
          const toolCallsForSession = activeSessionId
            ? (toolCallsBySession[activeSessionId] ?? [])
            : [];

          return (
            <div key={round.round_num} className="space-y-4">
              {/* User message -- right aligned */}
              {round.userMessage && (
                <div className="flex justify-end">
                  <div className="max-w-[80%] rounded-2xl bg-primary px-4 py-2.5 text-primary-foreground">
                    <p className="text-sm whitespace-pre-wrap">{round.userMessage.content}</p>
                  </div>
                </div>
              )}

              {/* Agent steps -- StepCard for each step in this round */}
              {roundSteps.length > 0 && (
                <div className="space-y-2">
                  {roundSteps.map((step, idx) => (
                    <StepCard
                      key={step.stepNum}
                      step={step}
                      toolCalls={toolCallsForSession}
                      isLastActive={
                        idx === roundSteps.length - 1 && step.status === "active"
                      }
                    />
                  ))}
                </div>
              )}

              {/* Agent thinking indicator for rounds with no steps yet */}
              {roundSteps.length === 0 && round.agentEvents.length > 0 && (
                <div className="flex justify-start">
                  <div className="rounded-2xl bg-card border border-border px-4 py-3">
                    <p className="text-sm text-muted-foreground italic">
                      Agent is thinking
                      <span className="animate-pulse">...</span>
                    </p>
                  </div>
                </div>
              )}
            </div>
          );
        })}

        {/* Loading indicator when agent is thinking (no events yet) */}
        {isAgentThinking && rounds.length === 0 && (
          <div className="flex justify-start">
            <div className="rounded-2xl bg-card border border-border px-4 py-3">
              <p className="text-sm text-muted-foreground italic">
                Agent is thinking
                <span className="animate-pulse">...</span>
              </p>
            </div>
          </div>
        )}

        <div ref={streamEndRef} />
      </div>

      {/* "Scroll to bottom" floating button */}
      {!isAtBottom && (
        <Button
          variant="secondary"
          size="icon-sm"
          className="absolute bottom-20 right-8 z-10 shadow-md rounded-full"
          onClick={() => {
            streamEndRef.current?.scrollIntoView({ behavior: "smooth" });
            setIsAtBottom(true);
          }}
        >
          <ArrowDown className="size-4" />
        </Button>
      )}
    </div>
  );

  // ── Input bar ────────────────────────────────────────────────────────

  const inputBar = activeSessionId && (
    <div className="border-t border-border p-4">
      <div className="flex items-end gap-2 max-w-4xl mx-auto">
        <div className="flex-1 relative">
          <textarea
            value={messageInput}
            onChange={(e) => setMessageInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSendMessage();
              }
            }}
            placeholder="Send a message..."
            className="w-full resize-none rounded-xl border border-border bg-card px-4 py-3 text-sm
                       placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary
                       min-h-[44px] max-h-[200px]"
            rows={1}
            disabled={isSending || !activeSessionId}
          />
        </div>
        <Button
          size="icon"
          onClick={handleSendMessage}
          disabled={!messageInput.trim() || isSending || !activeSessionId}
          className="h-[44px] w-[44px] rounded-xl shrink-0"
        >
          {isSending ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <Send className="size-4" />
          )}
        </Button>
      </div>
    </div>
  );

  // ── History sidebar ──────────────────────────────────────────────────

  const historySidebar = showHistory && (
    <div className="fixed inset-0 z-50 flex">
      <div className="w-72 bg-card border-r border-border shadow-lg overflow-y-auto">
        <div className="p-4 border-b border-border">
          <h2 className="text-sm font-semibold">History</h2>
        </div>
        <SessionList
          onSelect={(id) => {
            setActiveSession(id);
            setShowHistory(false);
          }}
        />
      </div>
      <div className="flex-1 bg-black/20" onClick={() => setShowHistory(false)} />
    </div>
  );

  // ── Render ───────────────────────────────────────────────────────────

  return (
    <TooltipProvider>
      <div className="flex min-h-screen flex-col bg-background text-foreground">
        {/* Header */}
        <header className="flex h-14 items-center justify-between border-b border-border px-4">
          <div className="flex items-center gap-3">
            <h1 className="text-lg font-semibold">loopAI</h1>
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setShowHistory(!showHistory)}
            >
              <History className="size-4" />
            </Button>
          </div>
          <div className="flex items-center gap-2">
            <ConnectionStatus />
            {activeSessionId && (
              <Button
                variant="ghost"
                size="icon"
                onClick={handleNewChat}
                title="New chat"
              >
                <Plus className="size-4" />
              </Button>
            )}
          </div>
        </header>

        {/* Main content */}
        {startScreen}
        {messageStream}
        {inputBar}

        {/* History sidebar overlay */}
        {historySidebar}

        {/* Confirmation dialog (portal -- renders to document.body) */}
        <ConfirmationDialog />
      </div>
    </TooltipProvider>
  );
}

export default App;
