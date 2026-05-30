import { useEffect, useCallback, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { History, Plus, ChevronDown, Wrench, Send, Loader2 } from "lucide-react";
import { TooltipProvider } from "@/components/ui/tooltip";
import { useUIStore } from "@/stores/uiStore";
import { useEventStore } from "@/stores/eventStore";
import { useSessionEvents } from "@/hooks/useSessionEvents";
import { startSession, sendMessage } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import ConnectionStatus from "@/components/ConnectionStatus";
import ConfirmationDialog from "@/components/ConfirmationDialog";
import SessionList from "@/components/SessionList";
import { fixMarkdownTable } from "@/utils/markdown";
import { formatTokens, formatCost, calculateCost } from "@/lib/costCalculator";
import type { Event, UserMessageEvent, ToolCallInfo, TokenUsage } from "@/lib/eventTypes";

// ── Round display type ──────────────────────────────────────────────────

type RoundDisplay = {
  round_num: number;
  userMessage: UserMessageEvent | null;
  agentEvents: Event[];
  toolCalls: ToolCallInfo[];
  tokenUsage: TokenUsage | null;
};

function getAccumulatedText(events: Event[]): string {
  return events
    .filter((e): e is Event & { event_type: "llm_token"; content_delta: string } =>
      e.event_type === "llm_token"
    )
    .map((e) => e.content_delta)
    .join("");
}

function buildRound(
  roundNum: number,
  userMsg: UserMessageEvent | null,
  events: Event[],
  toolCalls: ToolCallInfo[]
): RoundDisplay {
  let promptTokens = 0, completionTokens = 0;
  for (const e of events) {
    if (e.event_type === "step_end" && (e as Event & { token_usage?: TokenUsage }).token_usage) {
      const tu = (e as Event & { token_usage: TokenUsage }).token_usage;
      promptTokens += tu.prompt_tokens;
      completionTokens += tu.completion_tokens;
    }
  }
  const cumulativeTokenUsage: TokenUsage | null =
    promptTokens > 0 || completionTokens > 0
      ? { prompt_tokens: promptTokens, completion_tokens: completionTokens, total_tokens: promptTokens + completionTokens }
      : null;

  const toolCallIds = new Set(
    events.filter((e) => e.event_type === "tool_call_start")
      .map((e) => (e as Event & { tool_call_id: string }).tool_call_id)
  );
  const roundToolCalls = toolCalls.filter((tc) => toolCallIds.has(tc.tool_call_id));

  return {
    round_num: roundNum,
    userMessage: userMsg,
    agentEvents: events,
    toolCalls: roundToolCalls,
    tokenUsage: cumulativeTokenUsage,
  };
}

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
  const [expandedToolCall, setExpandedToolCall] = useState<string | null>(null);
  const [showHistory, setShowHistory] = useState(false);
  const [startPrompt, setStartPrompt] = useState("");

  // Connect SSE stream when an active session is set
  useSessionEvents(activeSessionId);

  // ── Round grouping ────────────────────────────────────────────────────

  const rounds = useMemo<RoundDisplay[]>(() => {
    if (!activeSessionId) return [];
    const events = eventsBySession[activeSessionId] ?? [];
    const tc = toolCallsBySession[activeSessionId] ?? [];

    const result: RoundDisplay[] = [];
    let currentEvents: Event[] = [];
    let currentUserMsg: UserMessageEvent | null = null;

    for (const event of events) {
      if (event.event_type === "user_message") {
        if (currentUserMsg || currentEvents.length > 0) {
          result.push(buildRound(result.length + 1, currentUserMsg, currentEvents, tc));
        }
        currentUserMsg = event as UserMessageEvent;
        currentEvents = [];
      } else if (event.event_type === "round_end") {
        currentEvents.push(event);
        result.push(buildRound(result.length + 1, currentUserMsg, currentEvents, tc));
        currentUserMsg = null;
        currentEvents = [];
      } else {
        currentEvents.push(event);
      }
    }

    // Flush remaining events (active round, no round_end yet)
    if (currentUserMsg || currentEvents.length > 0) {
      result.push(buildRound(result.length + 1, currentUserMsg, currentEvents, tc));
    }

    return result;
  }, [eventsBySession, activeSessionId, toolCallsBySession]);

  // ── Handlers ──────────────────────────────────────────────────────────

  const handleNewChat = useCallback(() => {
    setActiveSession(null);
    setExpandedToolCall(null);
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

  // ── Message stream ───────────────────────────────────────────────────

  const messageStream = activeSessionId && (
    <div className="flex-1 overflow-y-auto px-4 py-6 space-y-6">
      {rounds.length === 0 && (
        <div className="flex items-center justify-center h-full">
          <p className="text-sm text-muted-foreground italic">
            Waiting for agent response...
          </p>
        </div>
      )}

      {rounds.map((round) => {
        const accumulatedText = getAccumulatedText(round.agentEvents);

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

            {/* Agent response -- left aligned */}
            {round.agentEvents.length > 0 && (
              <div className="flex justify-start">
                <div className="max-w-[85%] rounded-2xl bg-card border border-border px-4 py-3">
                  {/* Thinking text */}
                  {accumulatedText && (
                    <div className="text-sm leading-relaxed prose prose-sm dark:prose-invert max-w-none">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>
                        {fixMarkdownTable(accumulatedText)}
                      </ReactMarkdown>
                    </div>
                  )}

                  {/* Tool call cards -- expandable inline */}
                  {round.toolCalls.length > 0 && (
                    <div className="mt-2 space-y-1 border-t border-border pt-2">
                      {round.toolCalls.map((tc) => (
                        <div key={tc.tool_call_id}>
                          <button
                            className="flex items-center gap-2 w-full rounded-md border border-border px-2.5 py-1.5 text-left text-xs hover:bg-accent/50 transition-colors cursor-pointer"
                            onClick={() =>
                              setExpandedToolCall(
                                expandedToolCall === tc.tool_call_id ? null : tc.tool_call_id
                              )
                            }
                          >
                            <Wrench className="size-3 text-muted-foreground shrink-0" />
                            <span className="font-mono text-xs font-medium truncate flex-1">
                              {tc.tool_name}
                            </span>
                            <Badge variant={tc.is_error ? "destructive" : "secondary"}>
                              {tc.status}
                            </Badge>
                            <ChevronDown
                              className={`size-3 transition-transform ${
                                expandedToolCall === tc.tool_call_id ? "rotate-180" : ""
                              }`}
                            />
                          </button>

                          {/* Expandable details -- args + result */}
                          {expandedToolCall === tc.tool_call_id && (
                            <div className="ml-2 mt-1 p-2 rounded-md bg-muted/50 text-xs font-mono space-y-1">
                              {tc.full_args && Object.keys(tc.full_args).length > 0 && (
                                <div>
                                  <p className="text-muted-foreground mb-0.5">Arguments:</p>
                                  <pre className="whitespace-pre-wrap">
                                    {JSON.stringify(tc.full_args, null, 2)}
                                  </pre>
                                </div>
                              )}
                              {tc.result && (
                                <div>
                                  <p className="text-muted-foreground mb-0.5">Result:</p>
                                  <pre className="whitespace-pre-wrap">{tc.result}</pre>
                                </div>
                              )}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Token info -- lightweight */}
                  {round.tokenUsage && (
                    <div className="mt-2 flex items-center gap-2 text-xs text-muted-foreground border-t border-border pt-2">
                      <span>Tokens: {formatTokens(round.tokenUsage.total_tokens)}</span>
                      <span>
                        Cost: {formatCost(
                          calculateCost(
                            round.tokenUsage.prompt_tokens,
                            round.tokenUsage.completion_tokens
                          )
                        )}
                      </span>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        );
      })}

      {/* Loading indicator when agent is thinking */}
      {isAgentThinking && (
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
