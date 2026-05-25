<template>
  <div class="chat-panel">
    <div ref="scrollEl" class="chat-scroll" data-testid="chat-scroll">
      <ChatMessage
        v-for="m in messages"
        :key="m.id"
        :role="m.role"
        :content="m.content"
        :pending="m.pending"
      />
      <div v-if="isSending" class="typing-indicator" aria-live="polite">
        Asistent píše…
      </div>
    </div>

    <p v-if="errorMessage" class="error-msg" role="alert">{{ errorMessage }}</p>

    <form class="composer" @submit.prevent="onSubmit">
      <textarea
        v-model="draft"
        class="composer-input"
        rows="3"
        :maxlength="MAX_LEN"
        :placeholder="placeholder"
        :disabled="inputDisabled"
        @keydown.enter.exact.prevent="onSubmit"
      />
      <div class="composer-row">
        <span class="char-counter" :class="{ over: draft.length > MAX_LEN }">
          {{ draft.length }} / {{ MAX_LEN }}
        </span>
        <div class="composer-actions">
          <button type="submit" class="send-btn" :disabled="!canSend">
            <span v-if="isSending" class="btn-spinner" />
            Odoslať
          </button>
        </div>
      </div>
    </form>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import ChatMessage from "@/components/ChatMessage.vue";
import type { ChatPhase, SessionMessage } from "@/types";

const props = defineProps<{
  messages: SessionMessage[];
  phase: ChatPhase;
  isSending: boolean;
  isFinalizing: boolean;
  errorMessage: string | null;
  // Set by the parent (HomeView) when sendMessage rejects, so the
  // composer can restore the user's text and let them retry/edit.
  restoreDraft?: string | null;
}>();

const emit = defineEmits<{
  (e: "send", content: string): void;
  (e: "restored"): void;
}>();

const MAX_LEN = 4000;
const draft = ref("");
const scrollEl = ref<HTMLElement | null>(null);

// While `isFinalizing` is true the input becomes read-only — but during
// the user's normal send the input is cleared optimistically and the
// only progress indicator is the typing indicator below, so the field
// itself remains enabled (allowing them to start composing the next
// message immediately).
const inputDisabled = computed(() => props.isFinalizing);

const canSend = computed(
  () => draft.value.trim().length > 0 && draft.value.length <= MAX_LEN && !props.isFinalizing,
);

const placeholder = computed(() => {
  if (props.phase === "awaiting_confirmation") {
    return "Napíš „áno“ pre potvrdenie alebo navrhni zmenu…";
  }
  return "Napíš odpoveď…";
});

watch(
  () => props.messages.length,
  async () => {
    await nextTick();
    if (scrollEl.value) {
      scrollEl.value.scrollTop = scrollEl.value.scrollHeight;
    }
  },
);

watch(
  () => props.restoreDraft,
  (val) => {
    if (val && !draft.value) {
      draft.value = val;
      emit("restored");
    }
  },
);

function onSubmit() {
  if (!canSend.value) return;
  const content = draft.value.trim();
  // Clear the input immediately — the optimistic bubble appears in
  // the thread so the user has visible feedback without keeping the
  // text in the composer.
  draft.value = "";
  emit("send", content);
}
</script>

<style scoped lang="scss">
.chat-panel {
  border: 1px solid #ddd;
  border-radius: 10px;
  background: #fafafa;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.chat-scroll {
  flex: 1;
  min-height: 320px;
  max-height: 480px;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.typing-indicator {
  align-self: flex-start;
  color: #777;
  font-style: italic;
  font-size: 0.9em;
}

.error-msg {
  color: #c62828;
  margin: 0;
  padding: 12px 16px;
  background: #fff;
  border-top: 1px solid #ddd;
}

.composer {
  border-top: 1px solid #ddd;
  background: #fff;
  padding: 12px 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.composer-input {
  width: 100%;
  resize: vertical;
  padding: 10px;
  border: 1px solid #ccc;
  border-radius: 6px;
  font-family: inherit;
  font-size: 1rem;
  line-height: 1.4;
  box-sizing: border-box;

  &:focus {
    outline: none;
    border-color: #555;
  }

  &:disabled {
    background: #f0f0f0;
    cursor: not-allowed;
  }
}

.composer-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.char-counter {
  font-size: 0.8em;
  color: #888;

  &.over {
    color: #c62828;
    font-weight: 600;
  }
}

.composer-actions {
  display: flex;
  gap: 8px;
}

.send-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border: none;
  border-radius: 6px;
  font-size: 0.95rem;
  cursor: pointer;
  background: #2c2c2c;
  color: #fff;

  &:hover:not(:disabled) {
    background: #444;
  }

  &:disabled {
    background: #aaa;
    cursor: not-allowed;
  }
}

.btn-spinner {
  display: inline-block;
  width: 12px;
  height: 12px;
  border: 2px solid rgba(255, 255, 255, 0.4);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
