import { createI18n } from 'vue-i18n'
import sk from './locales/sk'
import cs from './locales/cs'
import en from './locales/en'
import { SUPPORTED_LANGUAGES, type Language } from './supported'

export function detectInitialLanguage(): Language {
  // 1. Check URL prefix
  const path = window.location.pathname
  for (const lang of SUPPORTED_LANGUAGES) {
    if (path.startsWith(`/${lang}/`) || path === `/${lang}`) {
      return lang
    }
  }

  // 2. Check localStorage
  const stored = localStorage.getItem('illustration-app:language')
  if (stored && SUPPORTED_LANGUAGES.includes(stored as Language)) {
    return stored as Language
  }

  // 3. Check browser locale
  const browserLang = navigator.language.split('-')[0]
  if (SUPPORTED_LANGUAGES.includes(browserLang as Language)) {
    return browserLang as Language
  }

  // 4. Fallback to English
  return 'en'
}

export const i18n = createI18n({
  legacy: false,
  locale: detectInitialLanguage(),
  fallbackLocale: 'en',
  messages: { sk, cs, en },
  missingWarn: import.meta.env.DEV,
  fallbackWarn: import.meta.env.DEV,
})
