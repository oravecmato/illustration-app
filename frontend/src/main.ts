import { createApp } from "vue";
import { createPinia } from "pinia";
import FloatingVue from "floating-vue";
import "floating-vue/dist/style.css";
import App from "./App.vue";
import router from "./router";
import { i18n } from "./i18n";
import "./assets/styles/main.scss";

const app = createApp(App);
app.use(createPinia());
app.use(i18n);
app.use(router);
app.use(FloatingVue);
app.mount("#app");
