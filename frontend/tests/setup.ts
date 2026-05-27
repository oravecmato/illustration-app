// jsdom in this project ships an experimental Storage implementation
// that doesn't always expose getItem/setItem as functions before any
// tests run. The production `@/i18n` module touches `localStorage` at
// import time (detectInitialLanguage), and several test files import
// stores that transitively pull in `@/i18n`. Replacing localStorage
// with a tiny in-memory stub before anything else loads keeps those
// imports working regardless of jsdom version.
const storage = new Map<string, string>();
const localStorageStub: Storage = {
  get length() {
    return storage.size;
  },
  clear() {
    storage.clear();
  },
  getItem(key: string) {
    return storage.has(key) ? storage.get(key)! : null;
  },
  key(index: number) {
    return Array.from(storage.keys())[index] ?? null;
  },
  removeItem(key: string) {
    storage.delete(key);
  },
  setItem(key: string, value: string) {
    storage.set(key, String(value));
  },
};
Object.defineProperty(globalThis, "localStorage", {
  value: localStorageStub,
  configurable: true,
});

import { config } from "@vue/test-utils";
import { createI18n } from "vue-i18n";
import sk from "../src/i18n/locales/sk";
import cs from "../src/i18n/locales/cs";
import en from "../src/i18n/locales/en";

// Standalone i18n instance for tests — avoids importing the production
// `@/i18n` singleton, which calls `detectInitialLanguage()` at module
// load and touches `localStorage`/`navigator.language` in ways that
// don't always agree with vitest's jsdom environment.
const i18n = createI18n({
  legacy: false,
  locale: "sk",
  fallbackLocale: "en",
  messages: { sk, cs, en },
});

// Install vue-i18n globally for all @vue/test-utils mounts so components
// that call useI18n() (or use $t in templates) get the real translation
// catalogue. Without this, every mount throws "Need to install with
// app.use" from vue-i18n.
config.global.plugins = [i18n];
