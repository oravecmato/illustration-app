<template>
  <div class="language-switcher">
    <button
      class="language-button"
      @click="toggleMenu"
      :aria-label="$t('nav.change_language')"
      aria-haspopup="menu"
      :aria-expanded="isOpen"
    >
      <span class="flag-icon" v-html="FLAG_MAP[currentLanguage]"></span>
      <svg
        class="chevron"
        :class="{ rotated: isOpen }"
        width="12"
        height="12"
        viewBox="0 0 12 12"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
      >
        <path
          d="M2 4L6 8L10 4"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
        />
      </svg>
    </button>

    <Transition name="menu">
      <div v-if="isOpen" class="menu" role="menu">
        <button
          v-for="lang in SUPPORTED_LANGUAGES"
          :key="lang"
          role="menuitemradio"
          :aria-checked="lang === currentLanguage"
          class="menu-item"
          :class="{ active: lang === currentLanguage }"
          @click="selectLanguage(lang)"
        >
          <span class="menu-flag" v-html="FLAG_MAP[lang]"></span>
          <span class="menu-label">{{ $t(`language.${lang}`) }}</span>
          <svg
            v-if="lang === currentLanguage"
            class="check-icon"
            width="16"
            height="16"
            viewBox="0 0 16 16"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
          >
            <path
              d="M13 4L6 11L3 8"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
            />
          </svg>
        </button>
      </div>
    </Transition>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import { useLocaleStore } from "@/stores/locale";
import type { Language } from "@/types";
import SK from "country-flag-icons/string/3x2/SK";
import CZ from "country-flag-icons/string/3x2/CZ";
import GB from "country-flag-icons/string/3x2/GB";

const SUPPORTED_LANGUAGES: Language[] = ["sk", "cs", "en"];

const FLAG_MAP: Record<Language, string> = {
  sk: SK,
  cs: CZ,
  en: GB,
};

const localeStore = useLocaleStore();

const isOpen = ref(false);
// Single source of truth: the active UI language lives in the locale store
// (kept in sync with the URL by the router guard). On the run page the
// runStore.switchLanguage() side-effect is dispatched by
// localeStore.setLanguage() and by RunView's route watcher, so the
// switcher never needs to read from the runStore.
const currentLanguage = computed(() => localeStore.currentLanguage);

function toggleMenu() {
  isOpen.value = !isOpen.value;
}

function selectLanguage(lang: Language) {
  isOpen.value = false;
  localeStore.setLanguage(lang, { silent: true });
}

// Close menu on click outside
function handleClickOutside(event: MouseEvent) {
  const target = event.target as HTMLElement;
  if (!target.closest(".language-switcher")) {
    isOpen.value = false;
  }
}

if (typeof window !== "undefined") {
  document.addEventListener("click", handleClickOutside);
}
</script>

<style scoped lang="scss">
.language-switcher {
  position: relative;
  z-index: 100;
}

.language-button {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  background: transparent;
  border: none;
  border-radius: 8px;
  color: #374151;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;

  &:hover {
    background: rgba(0, 0, 0, 0.05);
  }

  &:active {
    background: rgba(0, 0, 0, 0.08);
  }
}

.flag-icon {
  display: flex;
  align-items: center;
  width: 20px;
  height: 15px;

  :deep(svg) {
    width: 100%;
    height: 100%;
    border-radius: 2px;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.1);
  }
}

.chevron {
  transition: transform 0.2s ease;

  &.rotated {
    transform: rotate(180deg);
  }
}

.menu {
  position: absolute;
  top: calc(100% + 8px);
  right: 0;
  background: white;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  min-width: 120px;
  overflow: hidden;
}

.menu-item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 10px 12px;
  background: white;
  border: none;
  color: #374151;
  font-size: 14px;
  text-align: left;
  cursor: pointer;
  transition: background-color 0.15s ease;

  &:hover {
    background: #f3f4f6;
  }

  &.active {
    background: #eff6ff;
    color: #2563eb;
    font-weight: 600;
  }
}

.menu-flag {
  display: flex;
  align-items: center;
  width: 20px;
  height: 15px;
  flex-shrink: 0;

  :deep(svg) {
    width: 100%;
    height: 100%;
    border-radius: 2px;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.1);
  }
}

.menu-label {
  flex: 1;
}

.check-icon {
  flex-shrink: 0;
  color: #2563eb;
}

// Menu transition
.menu-enter-active,
.menu-leave-active {
  transition:
    opacity 0.15s ease,
    transform 0.15s ease;
}

.menu-enter-from {
  opacity: 0;
  transform: translateY(-4px);
}

.menu-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
</style>
