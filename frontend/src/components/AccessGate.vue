<!--
  AccessGate (§ 8.11.6).

  Full-viewport overlay rendered by App.vue when the access-key store
  has no key, or when a paid endpoint just returned a gating
  error_code (MISSING_ACCESS_KEY / ACCESS_KEY_REVOKED /
  QUOTA_EXHAUSTED).

  This component does not call the backend on submit — the entered key
  is simply stored, and the next paid request will either succeed or
  bounce back through `handleAuthError` (which re-renders the gate
  with a fresh banner). That keeps the gate stateless and avoids a
  dedicated /api/access-key/verify endpoint.
-->

<template>
  <div class="access-gate" role="dialog" aria-modal="true" :aria-labelledby="titleId">
    <div class="access-gate-card">
      <h1 :id="titleId" class="access-gate-title">{{ $t('access.title') }}</h1>
      <p class="access-gate-intro">{{ $t('access.intro') }}</p>

      <div v-if="errorMessage" class="access-gate-error" role="alert">
        {{ errorMessage }}
      </div>

      <form class="access-gate-form" @submit.prevent="onSubmit">
        <label class="access-gate-label" :for="inputId">
          {{ $t('access.key_label') }}
        </label>
        <input
          :id="inputId"
          ref="inputEl"
          v-model="draft"
          type="text"
          class="access-gate-input"
          :placeholder="$t('access.key_placeholder')"
          autocomplete="off"
          spellcheck="false"
          @input="onInput"
        />
        <button type="submit" class="access-gate-submit" :disabled="!canSubmit">
          {{ $t('access.submit') }}
        </button>
      </form>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAccessKeyStore } from '@/stores/accessKey'

const store = useAccessKeyStore()
const { t } = useI18n()

const draft = ref('')
const inputEl = ref<HTMLInputElement | null>(null)
// Stable per-instance ids so the label/aria-labelledby wiring works
// without colliding if the gate ever gets mounted twice during a
// transition.
const inputId = `access-gate-input-${Math.random().toString(36).slice(2, 9)}`
const titleId = `access-gate-title-${Math.random().toString(36).slice(2, 9)}`

const canSubmit = computed(() => draft.value.trim().length > 0)

const errorMessage = computed<string | null>(() => {
  const code = store.gateError
  if (!code) return null
  // Per-code i18n string under `access.errors.<code>`.
  return t(`access.errors.${code}`)
})

function onInput() {
  // The user typing dismisses any stale error banner so the form
  // doesn't show "revoked" while they're correcting the key.
  if (store.gateError) store.clearError()
}

function onSubmit() {
  const trimmed = draft.value.trim()
  if (!trimmed) return
  store.setKey(trimmed)
  draft.value = ''
}

onMounted(() => {
  inputEl.value?.focus()
})
</script>

<style scoped lang="scss">
.access-gate {
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: rgba(20, 20, 28, 0.72);
  backdrop-filter: blur(4px);
}

.access-gate-card {
  width: 100%;
  max-width: 480px;
  background: var(--surface-bg, #ffffff);
  color: var(--surface-fg, #1a1a1a);
  border-radius: 12px;
  padding: 28px 28px 24px;
  box-shadow: 0 24px 64px rgba(0, 0, 0, 0.32);
}

.access-gate-title {
  margin: 0 0 8px;
  font-size: 22px;
  font-weight: 600;
}

.access-gate-intro {
  margin: 0 0 20px;
  font-size: 14px;
  line-height: 1.5;
  color: var(--muted-fg, #555);
}

.access-gate-error {
  margin: 0 0 16px;
  padding: 10px 12px;
  border-radius: 8px;
  background: #fdecea;
  color: #8a1f12;
  font-size: 13px;
  line-height: 1.4;
}

.access-gate-form {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.access-gate-label {
  font-size: 13px;
  font-weight: 500;
}

.access-gate-input {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid #cfd2d8;
  border-radius: 8px;
  font-size: 15px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  box-sizing: border-box;

  &:focus {
    outline: 2px solid #4f8cff;
    outline-offset: 1px;
    border-color: transparent;
  }
}

.access-gate-submit {
  margin-top: 8px;
  padding: 10px 16px;
  border: 0;
  border-radius: 8px;
  background: #4f8cff;
  color: white;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;

  &:disabled {
    background: #c2cee8;
    cursor: not-allowed;
  }
}
</style>
