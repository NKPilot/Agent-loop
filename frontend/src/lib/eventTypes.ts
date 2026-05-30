/**
 * TypeScript event type definitions mirroring Python schemas.py.
 *
 * All 22 event types are defined with literal event_type discriminators
 * forming a discriminated union for type-safe event handling.
 */

// ── Helper types ──────────────────────────────────────────────────────

export interface TokenUsage {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
}

export interface ToolCallInfo {
  tool_name: string;
  tool_call_id: string;
  step_num: number;
  full_args?: Record<string, unknown>;
  result?: string;
  is_error?: boolean;
  duration_ms?: number;
  status: "pending" | "running" | "done" | "error";
}

export interface CostRates {
  promptPer1K: number;
  completionPer1K: number;
}

export type SSEStatus = "connected" | "connecting" | "reconnecting" | "failed";

// ── Base event ────────────────────────────────────────────────────────

export interface EventBase {
  event_type: string;
  session_id: string;
  timestamp: string;
}

// ── Top-level lifecycle events ────────────────────────────────────────

export interface StepStartEvent extends EventBase {
  event_type: "step_start";
  step_num: number;
}

export interface StepEndEvent extends EventBase {
  event_type: "step_end";
  step_num: number;
  state_transition: string;
  token_usage?: TokenUsage | null;
}

export interface SessionEndEvent extends EventBase {
  event_type: "session_end";
  final_state: string;
  total_steps: number;
  exit_reason: string;
}

// ── Inner streaming events ────────────────────────────────────────────

export interface LLMTokenEvent extends EventBase {
  event_type: "llm_token";
  step_num: number;
  content_delta: string;
}

export interface LLMContentDoneEvent extends EventBase {
  event_type: "llm_content_done";
  step_num: number;
  full_content: string;
}

export interface ToolCallStartEvent extends EventBase {
  event_type: "tool_call_start";
  step_num: number;
  tool_name: string;
  tool_call_id: string;
}

export interface ToolCallArgsEvent extends EventBase {
  event_type: "tool_call_args";
  step_num: number;
  tool_name: string;
  args_delta: string;
}

export interface ToolCallDoneEvent extends EventBase {
  event_type: "tool_call_done";
  step_num: number;
  tool_name: string;
  tool_call_id: string;
  full_args: Record<string, unknown>;
}

export interface ToolResultEvent extends EventBase {
  event_type: "tool_result";
  step_num: number;
  tool_name: string;
  tool_call_id: string;
  result: string;
  is_error: boolean;
  duration_ms: number;
}

// ── Guard events ──────────────────────────────────────────────────────

export interface BudgetWarningEvent extends EventBase {
  event_type: "budget_warning";
  step_num: number;
  used_pct: number;
  max_steps: number;
}

export interface BudgetExhaustedEvent extends EventBase {
  event_type: "budget_exhausted";
  step_num: number;
}

export interface LoopDetectedEvent extends EventBase {
  event_type: "loop_detected";
  step_num: number;
  tool_name: string;
  consecutive_count: number;
}

export interface ErrorEvent extends EventBase {
  event_type: "error";
  step_num: number;
  error_type: string;
  message: string;
  traceback?: string | null;
}

// ── Confirmation events ───────────────────────────────────────────────

export interface ConfirmationRequiredEvent extends EventBase {
  event_type: "confirmation_required";
  step_num: number;
  confirmation_id: string;
  tool_name: string;
  tool_args: Record<string, unknown>;
  permission_level: string;
  reason: string;
}

export interface ConfirmationResponseEvent extends EventBase {
  event_type: "confirmation_response";
  step_num: number;
  confirmation_id: string;
  approved: boolean;
}

// ── Context management events ─────────────────────────────────────────

export interface ContextCompactedEvent extends EventBase {
  event_type: "context_compacted";
  step_num: number;
  tokens_before: number;
  tokens_after: number;
  tokens_saved: number;
  rounds_preserved: number;
  summary_message_count: number;
}

export interface TokenWarningEvent extends EventBase {
  event_type: "token_warning";
  step_num: number;
  token_count: number;
  max_tokens: number;
  used_pct: number;
  action: string;
}

// ── Agent-as-Tool events (Phase 6) ────────────────────────────────────

export interface AgentCallStartEvent extends EventBase {
  event_type: "agent_call_start";
  step_num: number;
  agent_name: string;
  child_session_id: string;
  tool_call_id: string;
}

export interface AgentCallEndEvent extends EventBase {
  event_type: "agent_call_end";
  step_num: number;
  agent_name: string;
  child_session_id: string;
  summary: string;
  tool_calls_count: number;
  token_usage: TokenUsage | null;
  steps: number;
  success: boolean;
}

// ── Resilience events (Phase 4) ───────────────────────────────────────

export interface CheckpointSavedEvent extends EventBase {
  event_type: "checkpoint_saved";
  step_count: number;
  state: string;
  file_path: string;
}

export interface CircuitOpenedEvent extends EventBase {
  event_type: "circuit_opened";
  tool_name: string;
  failure_rate: number;
  window_size: number;
  previous_state: string;
  new_state: string;
}

export interface CircuitClosedEvent extends EventBase {
  event_type: "circuit_closed";
  tool_name: string;
  previous_state: string;
  new_state: string;
}

export interface FailureRegisteredEvent extends EventBase {
  event_type: "failure_registered";
  tool_name: string;
  signature: string;
  error_message: string;
}

export interface EscalationRequiredEvent extends EventBase {
  event_type: "escalation_required";
  tool_name: string;
  layer: number;
  attempt_count: number;
  error_message: string;
}

// ── Discriminated union type ──────────────────────────────────────────

export type Event =
  | StepStartEvent
  | StepEndEvent
  | SessionEndEvent
  | LLMTokenEvent
  | LLMContentDoneEvent
  | ToolCallStartEvent
  | ToolCallArgsEvent
  | ToolCallDoneEvent
  | ToolResultEvent
  | BudgetWarningEvent
  | BudgetExhaustedEvent
  | LoopDetectedEvent
  | ErrorEvent
  | ConfirmationRequiredEvent
  | ConfirmationResponseEvent
  | ContextCompactedEvent
  | TokenWarningEvent
  | CheckpointSavedEvent
  | CircuitOpenedEvent
  | CircuitClosedEvent
  | FailureRegisteredEvent
  | EscalationRequiredEvent
  | AgentCallStartEvent
  | AgentCallEndEvent;

// ── Human-readable label map ──────────────────────────────────────────

export const EVENT_TYPE_MAP: Record<string, string> = {
  step_start: "Step Start",
  step_end: "Step End",
  session_end: "Session End",
  llm_token: "Thinking",
  llm_content_done: "Thinking Done",
  tool_call_start: "Tool Call Start",
  tool_call_args: "Tool Arguments",
  tool_call_done: "Tool Call Done",
  tool_result: "Tool Result",
  budget_warning: "Budget Warning",
  budget_exhausted: "Budget Exhausted",
  loop_detected: "Loop Detected",
  error: "Error",
  confirmation_required: "Confirmation Required",
  confirmation_response: "Confirmation Response",
  context_compacted: "Context Compacted",
  token_warning: "Token Warning",
  checkpoint_saved: "Checkpoint Saved",
  circuit_opened: "Circuit Opened",
  circuit_closed: "Circuit Closed",
  failure_registered: "Failure Registered",
  escalation_required: "Escalation Required",
  agent_call_start: "Agent Call Start",
  agent_call_end: "Agent Call End",
};
