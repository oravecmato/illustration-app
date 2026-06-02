/**
 * Unit tests for the access-key Pinia store (§ 8.11.6).
 *
 * The store is a thin wrapper around localStorage + an in-memory
 * `gateError` ref. We exercise the four state transitions the gate
 * relies on:
 *
 *   1. Initial load reads localStorage.
 *   2. setKey persists + clears any error banner.
 *   3. handleAuthError(MISSING/REVOKED) wipes the persisted key.
 *   4. handleAuthError(QUOTA_EXHAUSTED) keeps the key intact.
 */

import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useAccessKeyStore } from '../src/stores/accessKey'

const STORAGE_KEY = 'illustration-app:access-key'

describe('accessKey store', () => {
  beforeEach(() => {
    localStorage.clear()
    setActivePinia(createPinia())
  })

  it('starts with null key and null error when storage is empty', () => {
    const store = useAccessKeyStore()
    expect(store.key).toBeNull()
    expect(store.gateError).toBeNull()
  })

  it('loads the persisted key from localStorage on first access', () => {
    localStorage.setItem(STORAGE_KEY, 'persisted-key-abc')
    const store = useAccessKeyStore()
    expect(store.key).toBe('persisted-key-abc')
  })

  it('setKey persists to localStorage and clears any error banner', () => {
    const store = useAccessKeyStore()
    store.handleAuthError('MISSING_ACCESS_KEY')
    expect(store.gateError).toBe('MISSING_ACCESS_KEY')

    store.setKey('fresh-key')
    expect(store.key).toBe('fresh-key')
    expect(store.gateError).toBeNull()
    expect(localStorage.getItem(STORAGE_KEY)).toBe('fresh-key')
  })

  it('handleAuthError MISSING_ACCESS_KEY clears the persisted key', () => {
    localStorage.setItem(STORAGE_KEY, 'stale-key')
    const store = useAccessKeyStore()
    expect(store.key).toBe('stale-key')

    store.handleAuthError('MISSING_ACCESS_KEY')

    expect(store.gateError).toBe('MISSING_ACCESS_KEY')
    expect(store.key).toBeNull()
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull()
  })

  it('handleAuthError ACCESS_KEY_REVOKED clears the persisted key', () => {
    localStorage.setItem(STORAGE_KEY, 'revoked-key')
    const store = useAccessKeyStore()

    store.handleAuthError('ACCESS_KEY_REVOKED')

    expect(store.gateError).toBe('ACCESS_KEY_REVOKED')
    expect(store.key).toBeNull()
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull()
  })

  it('handleAuthError QUOTA_EXHAUSTED keeps the persisted key intact', () => {
    localStorage.setItem(STORAGE_KEY, 'exhausted-key')
    const store = useAccessKeyStore()

    store.handleAuthError('QUOTA_EXHAUSTED')

    expect(store.gateError).toBe('QUOTA_EXHAUSTED')
    // Key stays so the user does NOT have to retype it after the
    // operator extends quota out-of-band.
    expect(store.key).toBe('exhausted-key')
    expect(localStorage.getItem(STORAGE_KEY)).toBe('exhausted-key')
  })

  it('clearError clears the error banner without touching the key', () => {
    localStorage.setItem(STORAGE_KEY, 'good-key')
    const store = useAccessKeyStore()
    store.handleAuthError('QUOTA_EXHAUSTED')

    store.clearError()

    expect(store.gateError).toBeNull()
    expect(store.key).toBe('good-key')
  })

  it('clearKey wipes both the in-memory ref and storage', () => {
    localStorage.setItem(STORAGE_KEY, 'goodbye-key')
    const store = useAccessKeyStore()

    store.clearKey()

    expect(store.key).toBeNull()
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull()
  })
})
