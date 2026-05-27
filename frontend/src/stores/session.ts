import { defineStore } from "pinia";
import { computed, ref, watch } from "vue";
import type { ChatPhase, Language, Session, SessionMessage } from "@/types";
import {
  createSession,
  getSession,
  postSessionMessage,
} from "@/services/api";
import { useLocaleStore } from "@/stores/locale";
import { i18n } from "@/i18n";
import { useToast } from "@/composables/useToast";

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
  const errorMessage = ref<string | null>(null);
  /** Content of the last user message whose POST failed — surfaced so the
   *  composer can restore the user's draft after a rollback (§ 9.2.1). */
  const lastFailedDraft = ref<string | null>(null);
  /** Last detected language from Agent 0a (used to avoid redundant UI switches) */
  const lastDetectedLanguage = ref<string | null>(null);
  /** Topic short phrase extracted during the confirmation turn (used as the
   *  RunView loader fallback h1 until SSE delivers the real story title). */
  const topicShort = ref<string | null>(null);

  // canFinalize is retained as a derived value for any external consumer
  // that might still query it, but the UI no longer renders a manual
  // "Spustiť ilustrácie" button — when the assistant reply has
  // `phase === "confirmed"`, the messages endpoint already pre-allocated
  // the run id and scheduled Agent 0b + the pipeline as a background
  // task (§ 9.1). The frontend just navigates to /runs/:id.
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

    // Add synthetic welcome message from the assistant
    const welcomeMessage: SessionMessage = {
      id: "welcome",
      role: "assistant",
      content: i18n.global.t("chat.welcome"),
      created_at: new Date().toISOString(),
      pending: false,
    };
    messages.value = [welcomeMessage, ...messages.value];
  }

  async function refresh(sessionId: string): Promise<void> {
    const s = await getSession(sessionId);
    _apply(s);
  }

  /**
   * Send a user message with optimistic rendering.
   *
   * Returns the pre-allocated `run_id` when the assistant reply has
   * `phase === "confirmed"` — the messages endpoint already scheduled
   * Agent 0b + the pipeline as a background task and persisted the
   * run_id on the session. The view layer uses this id to navigate
   * immediately to /runs/:id, where the RunView loader stays on screen
   * until SSE delivers the snapshot.
   *
   * Returns `null` for non-terminal turns.
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

      // Language detection: if Agent 0a detected a language and we haven't
      // auto-switched yet in this session, switch the UI locale and
      // announce it with a toast (§ 9.6.6, § 9.7). The lastDetectedLanguage
      // guard prevents re-toasting on subsequent identical detections;
      // languageLockedByUser suppresses auto-switch after the user has
      // manually picked a language via LanguageSwitcher.
      if (resp.detected_language && !lastDetectedLanguage.value) {
        lastDetectedLanguage.value = resp.detected_language;
        const localeStore = useLocaleStore();
        const detected = resp.detected_language;
        if (
          (detected === "sk" || detected === "cs" || detected === "en") &&
          !localeStore.languageLockedByUser &&
          detected !== localeStore.currentLanguage
        ) {
          localeStore.setLanguage(detected as Language, { silent: false });
          const toast = useToast();
          toast.info(
            i18n.global.t("toast.language_switched", {
              language: i18n.global.t(`language.${detected}`),
            }),
          );
        }
      }

      // Store topic_short from confirmation response — RunView's loader
      // uses it as the h1 fallback while Agent 0b is still running.
      if (resp.topic_short) {
        topicShort.value = resp.topic_short;
      }

      // The messages endpoint pre-allocates the run_id and schedules
      // Agent 0b + the pipeline as a background task when phase ===
      // "confirmed". We return it so the view layer can navigate to
      // /runs/:id without awaiting Agent 0b.
      if (resp.phase === "confirmed" && resp.run_id) {
        return resp.run_id;
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

  function clearFailedDraft(): void {
    lastFailedDraft.value = null;
  }

  function reset(): void {
    session.value = null;
    messages.value = [];
    phase.value = "gathering";
    isSending.value = false;
    errorMessage.value = null;
    lastFailedDraft.value = null;
    lastDetectedLanguage.value = null;
    topicShort.value = null;
  }

  // Watch for locale changes and update welcome message if present
  watch(
    () => i18n.global.locale.value,
    () => {
      // If there's a welcome message (id='welcome'), update its content
      const welcomeIndex = messages.value.findIndex((m) => m.id === "welcome");
      if (welcomeIndex !== -1) {
        messages.value = [
          ...messages.value.slice(0, welcomeIndex),
          {
            ...messages.value[welcomeIndex],
            content: i18n.global.t("chat.welcome"),
          },
          ...messages.value.slice(welcomeIndex + 1),
        ];
      }
    },
  );

  return {
    session,
    messages,
    phase,
    isSending,
    errorMessage,
    lastFailedDraft,
    lastDetectedLanguage,
    topicShort,
    canFinalize,
    start,
    refresh,
    sendMessage,
    clearFailedDraft,
    reset,
  };
});
