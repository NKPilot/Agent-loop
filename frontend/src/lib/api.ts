/**
 * REST API client functions for the loopAI backend.
 *
 * All functions use fetch() with proper error handling for non-2xx responses.
 */

// ── API types ─────────────────────────────────────────────────────────

export interface SessionSummary {
  id: string;
  created_at: string;
  step_count: number;
  status: string;
  exit_reason?: string;
}

export interface SessionDetail {
  id: string;
  created_at: string;
  step_count: number;
  status: string;
  exit_reason?: string;
  events: Array<Record<string, unknown>>;
  token_usage?: { prompt_tokens: number; completion_tokens: number; total_tokens: number };
  cost?: number;
}

export interface StartSessionResponse {
  session_id: string;
}

// ── Helper ────────────────────────────────────────────────────────────

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail = "";
    try {
      const body = await response.json();
      detail = body.detail || body.message || "";
    } catch {
      detail = response.statusText;
    }
    throw new Error(
      `API error ${response.status}: ${detail || response.statusText}`
    );
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return response.json() as Promise<T>;
}

// ── Session list / detail ─────────────────────────────────────────────

export async function fetchSessions(): Promise<SessionSummary[]> {
  const response = await fetch("/api/sessions");
  const data = await handleResponse<{ sessions: SessionSummary[] }>(response);
  return data.sessions;
}

export async function fetchSession(id: string): Promise<SessionDetail> {
  const response = await fetch(`/api/sessions/${encodeURIComponent(id)}`);
  const data = await handleResponse<{ session: SessionDetail }>(response);
  return data.session;
}

// ── Session lifecycle ─────────────────────────────────────────────────

export async function startSession(
  prompt: string,
  maxSteps?: number
): Promise<StartSessionResponse> {
  const response = await fetch("/api/sessions/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt, ...(maxSteps !== undefined ? { max_steps: maxSteps } : {}) }),
  });
  return handleResponse<StartSessionResponse>(response);
}

export async function confirmCommand(
  sessionId: string,
  confirmationId: string,
  approved: boolean
): Promise<void> {
  const response = await fetch(
    `/api/sessions/${encodeURIComponent(sessionId)}/confirm`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirmation_id: confirmationId, approved }),
    }
  );
  return handleResponse<void>(response);
}

export async function deleteSession(id: string): Promise<void> {
  const response = await fetch(`/api/sessions/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
  return handleResponse<void>(response);
}

export function exportSessionUrl(id: string): string {
  return `/api/sessions/${encodeURIComponent(id)}/export`;
}
