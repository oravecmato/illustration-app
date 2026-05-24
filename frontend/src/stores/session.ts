import { defineStore } from "pinia";
import { computed, ref } from "vue";
import type { ChatPhase, Session, SessionMessage } from "@/types";
import {
  createSession,
  finalizeSession,
  getSession,
  postSessionMessage,
} from "@/services/api";

export const useSessionStore = defineStore("session", () => {
  const session = ref<Session | null>(null);
  const messages = ref<SessionMessage[]>([]);
  const phase = ref<ChatPhase>("gathering");
  const isSending = ref(false);
  const isFinalizing = ref(false);
  const errorMessage = ref<string | null>(null);

  const canFinalize = computed(
    () => session.value?.state === "AWAITING_CONFIRMATION" && phase.value !== "confirmed",
  );

  function _apply(s: Session): void {
    session.value = s;
    messages.value = s.messages;
    if (s.state === "AWAITING_CONFIRMATION") {
      // ``phase`` is the latest reply's phase; keep it unless the server
      // explicitly says otherwise.
    } else if (s.state === "CHATTING") {
      phase.value = "gathering";
    }
  }

  async function start(): Promise<void> {
    errorMessage.value = null;
    const s = await createSession();
    _apply(s);
    phase.value = "gathering";
  }

  async function refresh(sessionId: string): Promise<void> {
    const s = await getSession(sessionId);
    _apply(s);
  }

  async function sendMessage(content: string): Promise<void> {
    if (!session.value) {
      throw new Error("Session not initialized");
    }
    errorMessage.value = null;
    isSending.value = true;
    try {
      const resp = await postSessionMessage(session.value.id, content);
      _apply(resp.session);
      phase.value = resp.phase;
    } catch (err) {
      errorMessage.value = err instanceof Error ? err.message : String(err);
      throw err;
    } finally {
      isSending.value = false;
    }
  }

  async function finalize(): Promise<string> {
    if (!session.value) {
      throw new Error("Session not initialized");
    }
    errorMessage.value = null;
    isFinalizing.value = true;
    try {
      const { run_id } = await finalizeSession(session.value.id);
      return run_id;
    } catch (err) {
      errorMessage.value = err instanceof Error ? err.message : String(err);
      throw err;
    } finally {
      isFinalizing.value = false;
    }
  }

  function reset(): void {
    session.value = null;
    messages.value = [];
    phase.value = "gathering";
    isSending.value = false;
    isFinalizing.value = false;
    errorMessage.value = null;
  }

  return {
    session,
    messages,
    phase,
    isSending,
    isFinalizing,
    errorMessage,
    canFinalize,
    start,
    refresh,
    sendMessage,
    finalize,
    reset,
  };
});
