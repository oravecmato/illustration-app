<template>
  <Toaster position="bottom-left" rich-colors />
  <header class="app-topbar">
    <div class="app-topbar-inner">
      <LanguageSwitcher />
    </div>
  </header>
  <router-view v-if="!gateVisible" />
  <AccessGate v-if="gateVisible" />
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { Toaster } from 'vue-sonner'
import LanguageSwitcher from '@/components/LanguageSwitcher.vue'
import AccessGate from '@/components/AccessGate.vue'
import { useAccessKeyStore } from '@/stores/accessKey'

const accessKey = useAccessKeyStore()

// Show the gate whenever the store is empty or the last paid request
// bounced with a gating error_code. QUOTA_EXHAUSTED keeps the key
// stored (so the user doesn't have to retype it) but still blocks the
// router-view so they don't see a stale session screen.
const gateVisible = computed(
  () => accessKey.key === null || accessKey.gateError !== null,
)

onMounted(() => {
  // Invite-link bootstrap (§ 8.11.6): operators share
  // https://.../?invite=<key> via DM. We pull the key off the URL,
  // store it, and strip the query string so it doesn't linger in the
  // address bar / browser history.
  const url = new URL(window.location.href)
  const invite = url.searchParams.get('invite')
  if (invite) {
    accessKey.setKey(invite)
    url.searchParams.delete('invite')
    window.history.replaceState({}, '', url.toString())
  }
})
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
