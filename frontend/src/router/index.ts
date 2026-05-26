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

router.beforeEach((to) => {
  const lang = to.params.lang as string;
  if (lang && SUPPORTED_LANGUAGES.includes(lang as Language)) {
    i18n.global.locale.value = lang as Language;
    document.documentElement.lang = lang;
    localStorage.setItem("illustration-app:language", lang);
  }
});

export default router;
