<template>
  <div class="manual-chat-panel" :data-state="illustration.state">
    <header class="manual-header">
      <span class="manual-title">{{ t('illustration.manual.title') }}</span>
      <span class="manual-budget">
        {{ t('illustration.manual.budget', { used: attemptsUsed, max: MAX }) }}
      </span>
      <button
        v-if="canClose"
        type="button"
        class="manual-close"
        :aria-label="t('illustration.manual.close_aria')"
        data-testid="manual-chat-close"
        @click="emit('close')"
      >
        ×
      </button>
    </header>

    <ol ref="messagesEl" class="manual-messages" aria-live="polite">
      <li
        v-for="msg in messages"
        :key="msg.id"
        class="manual-message"
        :class="`role-${msg.role}`"
      >
        <template v-if="msg.role === 'image' && msg.image_url">
          <ManualImageCard
            :illustration="illustration"
            :message="msg"
            :is-latest-image="msg.id === latestImageMessageId"
            :has-messages-after="hasMessagesAfter(msg)"
            :budget-exhausted="budgetExhausted"
            @accept="handleAccept(msg)"
            @iterate="handleIterate"
          />
        </template>
        <template v-else>
          <span v-html="renderBold(msg.content)" />
        </template>
      </li>
    </ol>

    <div v-if="isBusy" class="manual-busy">
      <span class="spinner" :aria-label="t('a11y.loading')" />
      <span>{{ busyLabel }}</span>
    </div>

    <p v-if="canSend && inputLocked" class="manual-input-lock-hint" data-testid="manual-input-locked">
      {{ t('illustration.manual.input_locked') }}
    </p>

    <form
      v-if="canSend"
      class="manual-form"
      @submit.prevent="handleSubmit"
    >
      <input
        v-model="draft"
        type="text"
        :placeholder="placeholder"
        :disabled="sending || inputLocked"
        class="manual-input"
        data-testid="manual-input"
      />
      <button
        type="submit"
        :disabled="!draft.trim() || sending || inputLocked"
        class="manual-send"
        data-testid="manual-send"
      >
        {{ t('illustration.manual.send') }}
      </button>
    </form>

    <div v-if="errorMessage" class="manual-error">
      {{ errorMessage }}
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Illustration, ManualMessage } from '@/types'
import { useRunStore } from '@/stores/run'
import ManualImageCard from '@/components/ManualImageCard.vue'

const props = withDefaults(
  defineProps<{ illustration: Illustration; canClose?: boolean }>(),
  { canClose: true },
)
const emit = defineEmits<{ (e: 'close'): void }>()
const { t } = useI18n()
const runStore = useRunStore()

const MAX = 5
const draft = ref('')
const sending = ref(false)
const errorMessage = ref<string | null>(null)
const messagesEl = ref<HTMLElement | null>(null)

// Scroll the message list to the bottom on initial mount and whenever a
// new message arrives (user, assistant, or rendered image). Wrapped in
// `nextTick` so the new DOM node is laid out before we measure.
function scrollMessagesToBottom(): void {
  const el = messagesEl.value
  if (!el) return
  el.scrollTop = el.scrollHeight
}

// Bootstrap the chat when the panel mounts for an illustration that has no
// session yet. This handles legacy FAILED rows (from before § 6A existed):
// the backend GET /manual endpoint auto-opens the flow, seeds the welcome
// bubble, and transitions the illustration to MANUAL_CHATTING.
onMounted(() => {
  if (!props.illustration.manual_session) {
    runStore.loadManualChat(props.illustration.id).catch((err) => {
      errorMessage.value = err instanceof Error ? err.message : t('illustration.manual.error')
    })
  }
  // Show the newest message immediately when the chat opens (default
  // scrolled to the bottom).
  nextTick(scrollMessagesToBottom)
})

const messages = computed<ManualMessage[]>(() => props.illustration.manual_session?.messages ?? [])
const attemptsUsed = computed(() => props.illustration.manual_attempts ?? 0)

// Only spin while the user is actually waiting for the image pipeline:
// prompt (re)generation by Agent 1 and the RunPod render call. The
// sum of these two periods is the "image being made" wait. The brief
// HTTP-in-flight period after the user hits Send is not surfaced as a
// spinner — the Send button's disabled state already reflects it.
const isBusy = computed(() => {
  return (
    props.illustration.state === 'MANUAL_GENERATING_PROMPTS' ||
    props.illustration.state === 'MANUAL_RENDERING'
  )
})

const busyLabel = computed(() => {
  if (props.illustration.state === 'MANUAL_GENERATING_PROMPTS') {
    return t('illustration.state.MANUAL_GENERATING_PROMPTS')
  }
  return t('illustration.state.MANUAL_RENDERING')
})

// Auto-scroll on every new bubble so the latest message is always
// visible. Watching `length` avoids double-firing when the same array
// is reassigned with identical content (reconciliation after POST).
// Also re-scroll when the busy indicator appears so it stays in view.
watch([() => messages.value.length, isBusy], () => {
  nextTick(scrollMessagesToBottom)
})

const canSend = computed(() => {
  return (
    props.illustration.state === 'MANUAL_CHATTING' &&
    attemptsUsed.value < MAX
  )
})

const budgetExhausted = computed(() => attemptsUsed.value >= MAX)

const latestImageMessage = computed<ManualMessage | undefined>(() => {
  for (let i = messages.value.length - 1; i >= 0; i--) {
    if (messages.value[i].role === 'image') return messages.value[i]
  }
  return undefined
})

const latestImageMessageId = computed(() => latestImageMessage.value?.id ?? null)

function hasMessagesAfter(msg: ManualMessage): boolean {
  const idx = messages.value.indexOf(msg)
  if (idx < 0) return false
  for (let i = idx + 1; i < messages.value.length; i++) {
    if (messages.value[i].role !== 'image') return true
  }
  return false
}

// § 6A.10: lock input while the latest rendered image awaits an explicit
// Accept/Iterate choice (variant 1 footer). Iterate (or any non-image
// follow-up) unlocks the input.
const inputLocked = computed(() => {
  const latest = latestImageMessage.value
  if (!latest) return false
  if (budgetExhausted.value) return false
  if (props.illustration.state !== 'MANUAL_CHATTING') return false
  return !hasMessagesAfter(latest)
})

async function handleAccept(msg: ManualMessage): Promise<void> {
  if (msg.manual_attempt_index == null) return
  errorMessage.value = null
  try {
    await runStore.acceptManualAttempt(props.illustration.id, msg.manual_attempt_index)
  } catch (err) {
    errorMessage.value = err instanceof Error
      ? err.message
      : t('illustration.manual.image_card.action_error')
  }
}

async function handleIterate(): Promise<void> {
  errorMessage.value = null
  try {
    await runStore.requestIterate(props.illustration.id)
  } catch (err) {
    errorMessage.value = err instanceof Error
      ? err.message
      : t('illustration.manual.image_card.action_error')
  }
}

// Placeholder depends on the active sub-phase (§ 6A.4): in `concept_design`
// the user is describing the scene they want; in `feedback_gathering` they
// are critiquing the rendered image.
const placeholder = computed(() => {
  const subPhase = props.illustration.manual_session?.sub_phase ?? 'concept_design'
  return subPhase === 'feedback_gathering'
    ? t('illustration.manual.placeholder_feedback')
    : t('illustration.manual.placeholder_concept')
})

// Render `#…#` bold markers in localized welcome / canned bubbles.
function renderBold(content: string): string {
  const escaped = content
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
  return escaped.replace(/#([^#]+)#/g, '<strong>$1</strong>')
}

async function handleSubmit(): Promise<void> {
  const text = draft.value.trim()
  if (!text) return
  sending.value = true
  errorMessage.value = null
  draft.value = ''
  try {
    await runStore.sendManualMessage(props.illustration.id, text)
  } catch (err) {
    errorMessage.value = err instanceof Error ? err.message : t('illustration.manual.error')
  } finally {
    sending.value = false
  }
}
</script>

<style scoped lang="scss">
.manual-chat-panel {
  margin-top: 12px;
  border: 1px solid #d4d4d8;
  border-radius: 6px;
  background: #fafafa;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.manual-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  font-size: 0.85em;
}

.manual-title {
  font-weight: 600;
  color: #444;
}

.manual-budget {
  color: #777;
  margin-left: auto;
}

.manual-close {
  background: transparent;
  border: none;
  color: #777;
  cursor: pointer;
  font-size: 1.2em;
  line-height: 1;
  padding: 2px 6px;
  border-radius: 4px;
  transition:
    color 0.15s,
    background-color 0.15s;

  &:hover,
  &:focus-visible {
    color: #2c2c2c;
    background-color: rgba(0, 0, 0, 0.06);
    outline: none;
  }
}

.manual-messages {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 360px;
  overflow-y: auto;
}

.manual-message {
  padding: 6px 10px;
  border-radius: 8px;
  font-size: 0.9em;
  line-height: 1.4;

  &.role-user {
    align-self: flex-end;
    background: #e3f2fd;
    max-width: 85%;
  }

  &.role-assistant {
    align-self: flex-start;
    background: #fff;
    border: 1px solid #e5e7eb;
    max-width: 90%;
  }

  &.role-image {
    align-self: stretch;
    background: transparent;
    padding: 0;
  }
}

.manual-image {
  width: 100%;
  border-radius: 4px;
  display: block;
}

.manual-busy {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.85em;
  color: #555;
}

.manual-form {
  display: flex;
  gap: 8px;
}

.manual-input {
  flex: 1 1 auto;
  padding: 8px 10px;
  border: 1px solid #d4d4d8;
  border-radius: 4px;
  font-size: 0.95em;
}

.manual-send {
  padding: 8px 14px;
  border: none;
  border-radius: 4px;
  background: #1976d2;
  color: #fff;
  cursor: pointer;
  font-size: 0.9em;

  &:disabled {
    background: #b0bec5;
    cursor: not-allowed;
  }
}

.manual-error {
  color: #c62828;
  font-size: 0.85em;
}

.manual-input-lock-hint {
  margin: 0;
  font-size: 0.82em;
  color: #6b7280;
  font-style: italic;
}

.spinner {
  display: inline-block;
  width: 12px;
  height: 12px;
  border: 2px solid #ccc;
  border-top-color: #555;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
