import { createRouter, createWebHistory } from "vue-router";
import HomeView from "@/views/HomeView.vue";
import RunView from "@/views/RunView.vue";
import { detectInitialLanguage } from "@/i18n";
import { i18n } from "@/i18n";
import { SUPPORTED_LANGUAGES, type Language } from "@/i18n/supported";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: "/:lang(sk|cs|en)",
      children: [
        {
          path: "",
          name: "home",
          component: HomeView,
        },
        {
          path: "runs/:run_id",
          name: "run",
          component: RunView,
        },
      ],
    },
    {
      path: "/",
      redirect: () => {
        const lang = detectInitialLanguage();
        localStorage.setItem("illustration-app:language", lang);
        return `/${lang}/`;
      },
    },
    {
      path: "/runs/:run_id",
      redirect: (to) => {
        const lang = detectInitialLanguage();
        return `/${lang}/runs/${to.params.run_id}`;
      },
    },
    {
      path: "/:pathMatch(.*)*",
      redirect: () => {
        const lang = detectInitialLanguage();
        return `/${lang}/`;
      },
    },
  ],
});

router.beforeEach(async (to) => {
  const lang = to.params.lang as string;
  if (lang && SUPPORTED_LANGUAGES.includes(lang as Language)) {
    const targetLang = lang as Language;

    // Update i18n
    i18n.global.locale.value = targetLang;
    document.documentElement.lang = targetLang;
    localStorage.setItem("illustration-app:language", targetLang);

    // Dynamically import and update locale store to avoid circular dependency
    const { useLocaleStore } = await import('@/stores/locale');
    const localeStore = useLocaleStore();

    // Update store if language changed (avoid triggering setLanguage's URL update)
    if (localeStore.currentLanguage !== targetLang) {
      localeStore.$patch({ currentLanguage: targetLang });
    }
  }
});

export default router;
