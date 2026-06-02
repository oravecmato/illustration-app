import type {
  Illustration,
  ManualSessionResponse,
  PostMessageResponse,
  Run,
  Session,
  SseEvent,
} from "@/types";
import { useAccessKeyStore, type GateErrorCode } from "@/stores/accessKey";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

// Auth error codes the backend may return on a paid endpoint (§ 8.11).
// Anything else falls through to the generic error path.
const GATE_ERROR_CODES = new Set<GateErrorCode>([
  "MISSING_ACCESS_KEY",
  "ACCESS_KEY_REVOKED",
  "QUOTA_EXHAUSTED",
]);

export interface RunDetailResponse {
  run: Run;
  illustrations: Illustration[];
}

/**
 * Build the request init for a paid endpoint, attaching `X-Access-Key`
 * from the store when present. The header is omitted entirely when no
 * key is set so the backend returns 401 MISSING_ACCESS_KEY and the
 * AccessGate handles the empty-key bootstrap uniformly.
 */
function authedInit(init: RequestInit = {}): RequestInit {
  const accessKey = useAccessKeyStore().key;
  const headers = new Headers(init.headers);
  if (accessKey) {
    headers.set("X-Access-Key", accessKey);
  }
  return { ...init, headers };
}

/**
 * Inspect the response, route 401/402/403 with a known auth error_code
 * through the access-key store (so AccessGate re-renders), and otherwise
 * raise a generic Error with the backend message.
 */
async function jsonOrThrow<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const data = (await res.json().catch(() => ({}))) as {
      detail?: string | { error_code?: string; message?: string };
    };
    const detail = data.detail;
    const errorCode =
      detail && typeof detail === "object" ? detail.error_code : undefined;
    const message =
      detail && typeof detail === "object"
        ? detail.message
        : typeof detail === "string"
          ? detail
          : undefined;

    if (errorCode && GATE_ERROR_CODES.has(errorCode as GateErrorCode)) {
      useAccessKeyStore().handleAuthError(errorCode as GateErrorCode);
    }
    const err = new Error(message ?? errorCode ?? `HTTP ${res.status}`);
    // Surface the structured code so callers (e.g. session composer)
    // can branch on SESSION_USER_MESSAGE_LIMIT without string-matching.
    (err as Error & { code?: string }).code = errorCode;
    throw err;
  }
  return res.json();
}

// ── Sessions ───────────────────────────────────────────────────────────────

export async function createSession(): Promise<Session> {
  const res = await fetch(`${API_BASE}/api/sessions`, authedInit({ method: "POST" }));
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
  const res = await fetch(
    `${API_BASE}/api/sessions/${sessionId}/messages`,
    authedInit({
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    }),
  );
  return jsonOrThrow<PostMessageResponse>(res);
}

// ── Runs ───────────────────────────────────────────────────────────────────

export async function getRun(runId: string, lang?: string): Promise<RunDetailResponse> {
  const url = lang ? `${API_BASE}/api/runs/${runId}?lang=${lang}` : `${API_BASE}/api/runs/${runId}`;
  const res = await fetch(url);
  return jsonOrThrow<RunDetailResponse>(res);
}

export async function cancelRun(runId: string): Promise<void> {
  const res = await fetch(
    `${API_BASE}/api/runs/${runId}/cancel`,
    authedInit({ method: "POST" }),
  );
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error((data as { detail?: string }).detail ?? `HTTP ${res.status}`);
  }
}

export function openSseStream(
  runId: string,
  onEvent: (event: SseEvent) => void,
  onError?: (err: Event) => void,
  lang?: string
): EventSource {
  const url = lang
    ? `${API_BASE}/api/runs/${runId}/events?lang=${lang}`
    : `${API_BASE}/api/runs/${runId}/events`;
  const es = new EventSource(url);

  const eventTypes: SseEvent["type"][] = [
    "snapshot",
    "illustration_state",
    "illustration_completed",
    "illustration_failed",
    "illustration_entity_updated",
    "illustration_environment_updated",
    "illustration_role_updated",
    "illustration_manual_started",
    "manual_message_appended",
    "manual_image_rendered",
    "illustration_manual_ended",
    "translations_refreshed",
    "paragraph_updated",
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

export interface TranslateRunRequest {
  language: string;
  items: Array<{
    kind: "story_title" | "story_topic_description" | "paragraph" | "illustration_concept" | "scene_excerpt";
    paragraph_index?: number;
    scene_index?: number;
  }>;
}

export interface TranslateRunResponse {
  items: Array<{
    kind: "story_title" | "story_topic_description" | "paragraph" | "illustration_concept" | "scene_excerpt";
    paragraph_index?: number;
    scene_index?: number;
    text: string;
    source_hash: string;
  }>;
}

// ── § 6A manual illustration chat ─────────────────────────────────────────

export async function getManualChat(illustrationId: string): Promise<ManualSessionResponse> {
  const res = await fetch(
    `${API_BASE}/api/illustrations/${illustrationId}/manual`,
    authedInit(),
  );
  return jsonOrThrow<ManualSessionResponse>(res);
}

export async function postManualMessage(
  illustrationId: string,
  content: string,
): Promise<ManualSessionResponse> {
  const res = await fetch(
    `${API_BASE}/api/illustrations/${illustrationId}/manual/messages`,
    authedInit({
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    }),
  );
  return jsonOrThrow<ManualSessionResponse>(res);
}

export async function regenerateIllustration(
  illustrationId: string,
): Promise<ManualSessionResponse> {
  const res = await fetch(
    `${API_BASE}/api/illustrations/${illustrationId}/regenerate`,
    authedInit({ method: "POST" }),
  );
  return jsonOrThrow<ManualSessionResponse>(res);
}

export async function acceptIllustrationAttempt(
  illustrationId: string,
  manualAttemptIndex: number,
): Promise<ManualSessionResponse> {
  const res = await fetch(
    `${API_BASE}/api/illustrations/${illustrationId}/accept`,
    authedInit({
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ manual_attempt_index: manualAttemptIndex }),
    }),
  );
  return jsonOrThrow<ManualSessionResponse>(res);
}

export async function iterateManualImage(
  illustrationId: string,
): Promise<ManualSessionResponse> {
  const res = await fetch(
    `${API_BASE}/api/illustrations/${illustrationId}/manual/iterate`,
    authedInit({ method: "POST" }),
  );
  return jsonOrThrow<ManualSessionResponse>(res);
}

export async function translateRun(
  runId: string,
  language: string,
  items: Array<{
    kind: "story_title" | "story_topic_description" | "paragraph" | "illustration_concept" | "scene_excerpt";
    paragraph_index?: number;
    scene_index?: number;
    text: string;
    source_hash: string;
  }>
): Promise<TranslateRunResponse> {
  const res = await fetch(
    `${API_BASE}/api/runs/${runId}/translations`,
    authedInit({
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ language, items }),
    }),
  );
  return jsonOrThrow<TranslateRunResponse>(res);
}
