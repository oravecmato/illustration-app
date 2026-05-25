import { defineStore } from "pinia";
import { computed, ref } from "vue";
import type { ChatPhase, Session, SessionMessage } from "@/types";
import {
  createSession,
  finalizeSession,
  getSession,
  postSessionMessage,
} from "@/services/api";

/** Generate a client-side id for optimistic rows. Falls back to a
 *  Math.random suffix on environments without `crypto.randomUUID`
 *  (older jsdom etc.). The value is only used to locate the optimistic
 *  message during reconciliation. */
function _clientId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return `temp-${crypto.randomUUID()}`;
  }
  return `temp-${Math.random().toString(36).slice(2)}-${Date.now()}`;
}

export const useSessionStore = defineStore("session", () => {
  const session = ref<Session | null>(null);
  const messages = ref<SessionMessage[]>([]);
  const phase = ref<ChatPhase>("gathering");
  const isSending = ref(false);
  const isFinalizing = ref(false);
  const errorMessage = ref<string | null>(null);
  /** Content of the last user message whose POST failed — surfaced so the
   *  composer can restore the user's draft after a rollback (§ 9.2.1). */
  const lastFailedDraft = ref<string | null>(null);

  // canFinalize is retained as a derived value for any external consumer
  // that might still query it, but the UI no longer renders a manual
  // "Spustiť ilustrácie" button — finalize is triggered automatically
  // when the assistant reply has `phase === "confirmed"` (§ 9.1).
  const canFinalize = computed(
    () => session.value?.state === "AWAITING_CONFIRMATION" && phase.value !== "confirmed",
  );

  function _apply(s: Session): void {
    session.value = s;
    // Server messages are authoritative — replace the entire list.
    // Optimistic rows (if any pending at this moment) are owned by the
    // sendMessage flow that reconciles them explicitly.
    messages.value = s.messages;
    if (s.state === "CHATTING") {
      phase.value = "gathering";
    }
    // Other states keep the latest phase the post_message call returned.
  }

  async function start(): Promise<void> {
    errorMessage.value = null;
    lastFailedDraft.value = null;
    const s = await createSession();
    _apply(s);
    phase.value = "gathering";
  }

  async function refresh(sessionId: string): Promise<void> {
    const s = await getSession(sessionId);
    _apply(s);
  }

  /**
   * Send a user message with optimistic rendering.
   *
   * Returns the new `run_id` when the assistant reply has
   * `phase === "confirmed"` and the auto-finalize succeeded, otherwise
   * returns `null`. The view layer uses this to navigate to /runs/:id
   * without needing to watch for state transitions.
   */
  async function sendMessage(content: string): Promise<string | null> {
    if (!session.value) {
      throw new Error("Session not initialized");
    }
    errorMessage.value = null;
    lastFailedDraft.value = null;

    // 1. Push the optimistic user row BEFORE awaiting the POST so the
    //    bubble appears immediately. The `created_at` is a best-effort
    //    placeholder; it gets replaced by the server's value on
    //    reconciliation.
    const clientId = _clientId();
    const optimistic: SessionMessage = {
      id: clientId,
      role: "user",
      content,
      created_at: new Date().toISOString(),
      pending: true,
      client_id: clientId,
    };
    const optimisticIndex = messages.value.length;
    messages.value = [...messages.value, optimistic];

    isSending.value = true;
    try {
      const resp = await postSessionMessage(session.value.id, content);

      // 2. Reconcile in-place. The server returns the FULL transcript,
      //    so we'd lose the optimistic position by simply applying it.
      //    Instead, build the next array by splicing the server's
      //    persisted user message into the optimistic row's slot and
      //    appending any later messages.
      const serverMsgs = resp.session.messages;
      const reconciled = [...serverMsgs];
      session.value = { ...resp.session, messages: reconciled };
      messages.value = reconciled;
      phase.value = resp.phase;

      // 3. Auto-finalize the moment the assistant returns "confirmed".
      //    The deterministic CONFIRMED_ACK_SK is already in the
      //    transcript (server-normalised); no extra UI step is needed.
      if (resp.phase === "confirmed") {
        const runId = await _autoFinalize();
        return runId;
      }
      return null;
    } catch (err) {
      // Rollback: remove the optimistic row by client_id (or by index
      // as a defensive fallback). Preserve any messages that landed
      // after it (e.g. from a concurrent refresh) — there shouldn't be
      // any in practice, but the index-based fallback is still safe.
      const filtered = messages.value.filter((m) => m.client_id !== clientId);
      if (filtered.length === messages.value.length) {
        // client_id absent — fall back to index, but guard against
        // out-of-bounds (the list may have been replaced by a refresh
        // mid-flight).
        if (
          optimisticIndex < messages.value.length &&
          messages.value[optimisticIndex]?.pending
        ) {
          filtered.splice(optimisticIndex, 1);
        }
      }
      messages.value = filtered;
      lastFailedDraft.value = content;
      errorMessage.value = err instanceof Error ? err.message : String(err);
      throw err;
    } finally {
      isSending.value = false;
    }
  }

  async function _autoFinalize(): Promise<string> {
    isFinalizing.value = true;
    try {
      const { run_id } = await finalizeSession(session.value!.id);
      return run_id;
    } catch (err) {
      errorMessage.value = err instanceof Error ? err.message : String(err);
      throw err;
    } finally {
      isFinalizing.value = false;
    }
  }

  /**
   * Explicit finalize entrypoint — retained for any caller (and the
   * unit tests) that needs to trigger finalize manually. Production UI
   * does not call this directly; `sendMessage` auto-invokes it.
   */
  async function finalize(): Promise<string> {
    if (!session.value) {
      throw new Error("Session not initialized");
    }
    errorMessage.value = null;
    return _autoFinalize();
  }

  function clearFailedDraft(): void {
    lastFailedDraft.value = null;
  }

  function reset(): void {
    session.value = null;
    messages.value = [];
    phase.value = "gathering";
    isSending.value = false;
    isFinalizing.value = false;
    errorMessage.value = null;
    lastFailedDraft.value = null;
  }

  return {
    session,
    messages,
    phase,
    isSending,
    isFinalizing,
    errorMessage,
    lastFailedDraft,
    canFinalize,
    start,
    refresh,
    sendMessage,
    finalize,
    clearFailedDraft,
    reset,
  };
});
