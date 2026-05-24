import type {
  Illustration,
  PostMessageResponse,
  Run,
  Session,
  SseEvent,
} from "@/types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

export interface RunDetailResponse {
  run: Run;
  illustrations: Illustration[];
}

async function jsonOrThrow<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error((data as { detail?: string }).detail ?? `HTTP ${res.status}`);
  }
  return res.json();
}

// ── Sessions ───────────────────────────────────────────────────────────────

export async function createSession(): Promise<Session> {
  const res = await fetch(`${API_BASE}/api/sessions`, { method: "POST" });
  return jsonOrThrow<Session>(res);
}

export async function getSession(sessionId: string): Promise<Session> {
  const res = await fetch(`${API_BASE}/api/sessions/${sessionId}`);
  return jsonOrThrow<Session>(res);
}

export async function postSessionMessage(
  sessionId: string,
  content: string
): Promise<PostMessageResponse> {
  const res = await fetch(`${API_BASE}/api/sessions/${sessionId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
  return jsonOrThrow<PostMessageResponse>(res);
}

export async function finalizeSession(sessionId: string): Promise<{ run_id: string }> {
  const res = await fetch(`${API_BASE}/api/sessions/${sessionId}/finalize`, {
    method: "POST",
  });
  return jsonOrThrow<{ run_id: string }>(res);
}

// ── Runs ───────────────────────────────────────────────────────────────────

export async function getRun(runId: string): Promise<RunDetailResponse> {
  const res = await fetch(`${API_BASE}/api/runs/${runId}`);
  return jsonOrThrow<RunDetailResponse>(res);
}

export async function cancelRun(runId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/runs/${runId}/cancel`, {
    method: "POST",
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error((data as { detail?: string }).detail ?? `HTTP ${res.status}`);
  }
}

export function openSseStream(
  runId: string,
  onEvent: (event: SseEvent) => void,
  onError?: (err: Event) => void
): EventSource {
  const es = new EventSource(`${API_BASE}/api/runs/${runId}/events`);

  const eventTypes: SseEvent["type"][] = [
    "snapshot",
    "illustration_state",
    "illustration_completed",
    "illustration_failed",
    "run_completed",
    "run_failed",
    "run_cancelled",
    "heartbeat",
  ];

  for (const type of eventTypes) {
    es.addEventListener(type, (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data);
        onEvent({ type, data } as SseEvent);
      } catch {
        // ignore parse errors
      }
    });
  }

  if (onError) {
    es.onerror = onError;
  }

  return es;
}
