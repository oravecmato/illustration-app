import type { Run, Illustration, SseEvent } from "@/types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

export interface RunDetailResponse {
  run: Run;
  illustrations: Illustration[];
}

export async function postRun(storyText: string): Promise<{ run_id: string }> {
  const res = await fetch(`${API_BASE}/api/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ story_text: storyText }),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail ?? `HTTP ${res.status}`);
  }
  return res.json();
}

export async function getRun(runId: string): Promise<RunDetailResponse> {
  const res = await fetch(`${API_BASE}/api/runs/${runId}`);
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail ?? `HTTP ${res.status}`);
  }
  return res.json();
}

export async function cancelRun(runId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/runs/${runId}/cancel`, {
    method: "POST",
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail ?? `HTTP ${res.status}`);
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
    "style_guide_ready",
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
