<template>
  <div class="manual-image-card" data-testid="manual-image-card">
    <header class="card-header">
      <span class="attempt-label" data-testid="manual-image-card-attempt">
        {{ t('illustration.manual.image_card.attempt', {
          n: message.manual_attempt_index ?? 0, max: MAX,
        }) }}
      </span>
      <div class="header-icons">
        <VDropdown
          :triggers="conceptDisabled ? [] : ['click', 'hover', 'focus']"
          placement="bottom-end"
          :delay="{ show: 80, hide: 120 }"
        >
          <button
            type="button"
            class="info-trigger"
            :class="{ disabled: conceptDisabled }"
            :aria-label="t('illustration.manual.image_card.concept_aria')"
            :aria-disabled="conceptDisabled || undefined"
            :disabled="conceptDisabled"
            data-testid="manual-image-card-concept-trigger"
          >
            <svg
              viewBox="0 0 24 24"
              width="16"
              height="16"
              aria-hidden="true"
              focusable="false"
            >
              <circle cx="12" cy="12" r="10" fill="none" stroke="currentColor" stroke-width="1.6" />
              <circle cx="12" cy="8" r="1.2" fill="currentColor" />
              <path d="M12 11v6" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" />
            </svg>
          </button>
          <template #popper>
            <div class="popover-body" data-testid="manual-image-card-concept-body">
              <p class="popover-text">{{ message.concept_used }}</p>
            </div>
          </template>
        </VDropdown>

        <VDropdown
          :triggers="promptsDisabled ? [] : ['click', 'hover', 'focus']"
          placement="bottom-end"
          :delay="{ show: 80, hide: 120 }"
        >
          <button
            type="button"
            class="info-trigger"
            :class="{ disabled: promptsDisabled }"
            :aria-label="t('illustration.manual.image_card.prompts_aria')"
            :aria-disabled="promptsDisabled || undefined"
            :disabled="promptsDisabled"
            data-testid="manual-image-card-prompts-trigger"
          >
            <svg
              viewBox="0 0 24 24"
              width="16"
              height="16"
              aria-hidden="true"
              focusable="false"
            >
              <path d="M4 6h16M4 12h16M4 18h10" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" fill="none" />
            </svg>
          </button>
          <template #popper>
            <div class="popover-body" data-testid="manual-image-card-prompts-body">
              <template v-if="message.positive_prompt">
                <strong>{{ t('illustration.manual.image_card.positive_label') }}</strong>
                <p class="popover-text">{{ message.positive_prompt }}</p>
              </template>
              <template v-if="message.negative_prompt">
                <strong>{{ t('illustration.manual.image_card.negative_label') }}</strong>
                <p class="popover-text">{{ message.negative_prompt }}</p>
              </template>
            </div>
          </template>
        </VDropdown>
      </div>
    </header>

    <div class="card-image" v-if="message.image_url">
      <a :href="message.image_url" target="_blank" rel="noopener">
        <img
          :src="message.image_url"
          :alt="t('illustration.manual.attempt_alt', {
            n: message.manual_attempt_index ?? 0,
          })"
        />
      </a>
    </div>

    <footer v-if="footerVariant !== 'none'" class="card-footer">
      <template v-if="footerVariant === 'choose'">
        <button
          type="button"
          class="ghost-btn accept-btn"
          :disabled="actionInFlight"
          data-testid="manual-image-card-accept"
          @click="onAccept"
        >
          <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true" focusable="false">
            <path d="M5 12l4 4 10-10" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
          <span>{{ t('illustration.manual.image_card.accept') }}</span>
        </button>
        <button
          type="button"
          class="ghost-btn iterate-btn"
          :disabled="actionInFlight"
          data-testid="manual-image-card-iterate"
          @click="onIterate"
        >
          <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true" focusable="false">
            <path d="M6 6l12 12M18 6L6 18" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" />
          </svg>
          <span>{{ t('illustration.manual.image_card.iterate') }}</span>
        </button>
      </template>
      <template v-else>
        <button
          type="button"
          class="ghost-btn accept-btn"
          :disabled="actionInFlight"
          data-testid="manual-image-card-use"
          @click="onAccept"
        >
          <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true" focusable="false">
            <path d="M5 12l4 4 10-10" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
          <span>{{ t('illustration.manual.image_card.use') }}</span>
        </button>
      </template>
    </footer>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Dropdown as VDropdown } from 'floating-vue'
import type { Illustration, ManualMessage } from '@/types'

const props = defineProps<{
  illustration: Illustration
  message: ManualMessage
  isLatestImage: boolean
  hasMessagesAfter: boolean
  budgetExhausted: boolean
}>()

const emit = defineEmits<{
  (e: 'accept'): void
  (e: 'iterate'): void
}>()

const { t } = useI18n()
const MAX = 5
const actionInFlight = ref(false)

const conceptDisabled = computed(() => !props.message.concept_used)
const promptsDisabled = computed(
  () => !props.message.positive_prompt && !props.message.negative_prompt,
)

// 'choose' = latest image, no messages typed since, illustration still
// in a manual state, budget remaining → Accept + Iterate buttons.
// 'use'    = older attempt, or budget exhausted on the latest → Use only.
// 'none'   = illustration already COMPLETED (defensive — chat is hidden).
const footerVariant = computed<'choose' | 'use' | 'none'>(() => {
  if (props.illustration.state === 'COMPLETED') return 'none'
  if (
    props.isLatestImage &&
    !props.hasMessagesAfter &&
    !props.budgetExhausted
  ) {
    return 'choose'
  }
  return 'use'
})

async function onAccept(): Promise<void> {
  if (actionInFlight.value) return
  actionInFlight.value = true
  try {
    emit('accept')
  } finally {
    // Parent resets via reactive state change; clear flag after the
    // microtask so a fast re-click guard remains effective.
    setTimeout(() => {
      actionInFlight.value = false
    }, 0)
  }
}

async function onIterate(): Promise<void> {
  if (actionInFlight.value) return
  actionInFlight.value = true
  try {
    emit('iterate')
  } finally {
    setTimeout(() => {
      actionInFlight.value = false
    }, 0)
  }
}

defineExpose({ actionInFlight })
</script>

<style scoped lang="scss">
.manual-image-card {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 0.85em;
}

.attempt-label {
  font-weight: 600;
  color: #555;
}

.header-icons {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.info-trigger {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: none;
  padding: 4px;
  color: #777;
  cursor: pointer;
  border-radius: 50%;
  transition: color 0.15s, background-color 0.15s;

  &:hover:not(.disabled),
  &:focus-visible:not(.disabled) {
    color: #2c2c2c;
    background-color: rgba(0, 0, 0, 0.04);
    outline: none;
  }

  &.disabled {
    color: #ccc;
    cursor: not-allowed;
    pointer-events: none;
  }
}

.popover-body {
  max-width: 360px;
  padding: 10px 12px;
  font-family: var(--font-body);
  font-size: 0.9rem;
  line-height: 1.45;
  color: #2a2a2a;

  strong {
    display: block;
    font-size: 0.78rem;
    text-transform: uppercase;
    letter-spacing: 0.03em;
    color: #555;
    margin-top: 8px;
    margin-bottom: 2px;

    &:first-child {
      margin-top: 0;
    }
  }

  .popover-text {
    margin: 0;
    white-space: pre-wrap;
  }
}

.card-image img {
  width: 100%;
  display: block;
  border-radius: 4px;
}

.card-footer {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}

.ghost-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  background: transparent;
  border: 1px solid #d4d4d8;
  border-radius: 6px;
  font-size: 0.85em;
  color: #2c2c2c;
  cursor: pointer;
  transition: background-color 0.15s, border-color 0.15s, color 0.15s;

  &:hover:not(:disabled),
  &:focus-visible:not(:disabled) {
    background-color: rgba(0, 0, 0, 0.04);
    border-color: #9ca3af;
    outline: none;
  }

  &:disabled {
    color: #aaa;
    cursor: not-allowed;
  }

  &.accept-btn {
    color: #2e7d32;
    border-color: #c8e6c9;

    &:hover:not(:disabled),
    &:focus-visible:not(:disabled) {
      background-color: rgba(46, 125, 50, 0.06);
      border-color: #81c784;
    }
  }

  &.iterate-btn {
    color: #c62828;
    border-color: #ffcdd2;

    &:hover:not(:disabled),
    &:focus-visible:not(:disabled) {
      background-color: rgba(198, 40, 40, 0.06);
      border-color: #ef9a9a;
    }
  }
}
</style>
