import { createApp } from "vue";
import { createPinia } from "pinia";
import FloatingVue from "floating-vue";
import "floating-vue/dist/style.css";
import "vue-sonner/style.css";
import App from "./App.vue";
import router from "./router";
import { i18n } from "./i18n";
import { useAccessKeyStore } from "./stores/accessKey";
import "./assets/styles/main.scss";

const app = createApp(App);
const pinia = createPinia();
app.use(pinia);
app.use(i18n);
app.use(router);
app.use(FloatingVue);

// Invite-link bootstrap (§ 8.11.6) MUST happen BEFORE app.mount() so the
// store is populated before any component's setup/mounted hooks fire
// their first paid API call. In Vue 3, child mounted hooks run before
// parent ones — putting this in App.vue's onMounted means HomeView's
// createSession() already fired (and 401'd) by the time the invite key
// reaches the store. Doing it here is order-deterministic.
{
  const url = new URL(window.location.href);
  const invite = url.searchParams.get("invite");
  if (invite) {
    useAccessKeyStore().setKey(invite);
    url.searchParams.delete("invite");
    window.history.replaceState({}, "", url.toString());
  }
}

app.mount("#app");
