/**
 * Access-key store (§ 8.11.6).
 *
 * Holds the operator-issued access key in memory + localStorage and
 * exposes the gate state the UI branches on:
 *
 *   - `key === null` → AccessGate is shown.
 *   - `gateError !== null` → AccessGate is shown with an error banner.
 *
 * `setKey` is called from two places:
 *   1. The invite-link bootstrap in `App.vue` (reads `?invite=...`,
 *      stores the key, strips the query param via `history.replaceState`).
 *   2. The AccessGate form submit.
 *
 * `handleAuthError` is called from the api fetch wrapper when the
 * backend responds with a 401/402/403 carrying one of our gating
 * error_codes. It writes the error into `gateError` and (for
 * MISSING_ACCESS_KEY / ACCESS_KEY_REVOKED) clears the persisted key so
 * the user sees a fresh empty gate.
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'

const STORAGE_KEY = 'illustration-app:access-key'

export type GateErrorCode =
  | 'MISSING_ACCESS_KEY'
  | 'ACCESS_KEY_REVOKED'
  | 'QUOTA_EXHAUSTED'

function loadInitialKey(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY)
  } catch {
    // localStorage can throw on safari-private / no-cookies.
    return null
  }
}

export const useAccessKeyStore = defineStore('accessKey', () => {
  const key = ref<string | null>(loadInitialKey())
  const gateError = ref<GateErrorCode | null>(null)

  function setKey(newKey: string) {
    key.value = newKey
    gateError.value = null
    try {
      localStorage.setItem(STORAGE_KEY, newKey)
    } catch {
      // Best-effort: if storage is unavailable the key still works
      // for the current tab via the in-memory ref.
    }
  }

  function clearKey() {
    key.value = null
    try {
      localStorage.removeItem(STORAGE_KEY)
    } catch {
      /* noop */
    }
  }

  function handleAuthError(errorCode: GateErrorCode) {
    gateError.value = errorCode
    // For MISSING / REVOKED the persisted key is dead — wipe it so the
    // user starts from an empty input on the gate. QUOTA_EXHAUSTED
    // keeps the key around so the user can simply request more quota
    // out-of-band and retry without re-entering.
    if (errorCode === 'MISSING_ACCESS_KEY' || errorCode === 'ACCESS_KEY_REVOKED') {
      clearKey()
    }
  }

  function clearError() {
    gateError.value = null
  }

  return { key, gateError, setKey, clearKey, handleAuthError, clearError }
})
