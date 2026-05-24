<template>
  <div class="home-view">
    <h1 class="app-title">Anime ilustrátor</h1>

    <p class="intro-text">
      Spolu s asistentom vymyslite krátky ilustrovaný príbeh.
      Asistent sa ťa pýta v slovenčine.
    </p>

    <ChatPanel
      :messages="store.messages"
      :phase="store.phase"
      :is-sending="store.isSending"
      :is-finalizing="store.isFinalizing"
      :can-finalize="store.canFinalize"
      :error-message="store.errorMessage"
      @send="handleSend"
      @finalize="handleFinalize"
    />
  </div>
</template>

<script setup lang="ts">
import { onMounted } from "vue";
import { useRouter } from "vue-router";
import ChatPanel from "@/components/ChatPanel.vue";
import { useSessionStore } from "@/stores/session";

const router = useRouter();
const store = useSessionStore();

onMounted(async () => {
  // Always start a fresh session when the user lands on home.
  store.reset();
  await store.start();
});

async function handleSend(content: string) {
  try {
    await store.sendMessage(content);
  } catch {
    // Error already surfaced via store.errorMessage.
  }
}

async function handleFinalize() {
  try {
    const runId = await store.finalize();
    await router.push(`/runs/${runId}`);
  } catch {
    // Error already surfaced via store.errorMessage.
  }
}
</script>

<style scoped lang="scss">
.home-view {
  max-width: 760px;
  margin: 48px auto;
  padding: 0 24px;
}

.app-title {
  font-size: 2rem;
  font-weight: 700;
  margin-bottom: 8px;
  color: #1a1a1a;
}

.intro-text {
  color: #555;
  margin-bottom: 24px;
}
</style>
