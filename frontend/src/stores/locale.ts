import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { i18n, detectInitialLanguage } from '@/i18n'
import type { Language } from '@/i18n/supported'
import { useRunStore } from './run'

export const useLocaleStore = defineStore('locale', () => {
  const currentLanguage = ref<Language>(detectInitialLanguage())
  const languageLockedByUser = ref(false)

  const router = useRouter()
  const route = useRoute()

  function setLanguage(language: Language, options: { silent?: boolean } = {}) {
    if (language === currentLanguage.value) return

    currentLanguage.value = language
    i18n.global.locale.value = language
    document.documentElement.lang = language

    // Persist to localStorage
    localStorage.setItem('illustration-app:language', language)

    // Update URL
    const currentPath = route.path
    const newPath = currentPath.replace(/^\/(sk|cs|en)(\/|$)/, `/${language}$2`)
    router.replace(newPath)

    // If on a run page, trigger translation refresh
    if (route.name === 'run' && route.params.run_id) {
      const runStore = useRunStore()
      runStore.switchLanguage(language)
    }

    // Mark as manually locked if not silent
    if (!options.silent) {
      languageLockedByUser.value = true
    }
  }

  return {
    currentLanguage,
    languageLockedByUser,
    setLanguage,
  }
})
