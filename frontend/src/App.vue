<template>
  <Toaster position="bottom-left" rich-colors />
  <header class="app-topbar">
    <div class="app-topbar-inner">
      <LanguageSwitcher />
    </div>
  </header>
  <router-view />
</template>

<script setup lang="ts">
import { Toaster } from 'vue-sonner'
import LanguageSwitcher from '@/components/LanguageSwitcher.vue'
</script>

<style scoped lang="scss">
.app-topbar {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 50;
  pointer-events: none;
}

.app-topbar-inner {
  max-width: 760px;
  margin: 0 auto;
  padding: 12px 24px 0;
  display: flex;
  justify-content: flex-end;

  // Re-enable interaction only on the switcher itself so the empty
  // flex space above the page content stays click-through.
  :deep(.language-switcher) {
    pointer-events: auto;
  }
}
</style>
