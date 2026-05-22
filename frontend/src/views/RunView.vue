<template>
  <div class="run-view">
    <div class="run-header">
      <router-link to="/" class="back-link">← Nový text</router-link>
      <h1>Generovanie anime ilustrácií</h1>
    </div>

    <div v-if="store.run" class="run-meta">
      <span class="status-pill" :class="statusClass">
        <span v-if="store.run.status === 'RUNNING'" class="inline-spinner" />
        {{ statusLabel }}
      </span>

      <RunErrorBanner :run="store.run" />

      <ProgressCounter
        :completed-count="store.run.completed_count"
        :illustration-count="store.run.illustration_count > 0 ? store.run.illustration_count : null"
        :hidden="store.run.status === 'FAILED' && store.run.error_code === 'NO_SUITABLE_SCENES'"
      />

      <CancelButton
        :run-status="store.run.status"
        @cancel="handleCancel"
      />
    </div>

    <div v-if="store.sseError" class="sse-error">
      {{ store.sseError }}
    </div>

    <div v-if="store.illustrations.length > 0" class="illustration-grid">
      <IllustrationCard
        v-for="ill in store.illustrations"
        :key="ill.id"
        :illustration="ill"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted } from "vue";
import { useRoute } from "vue-router";
import { useRunStore } from "@/stores/run";
import IllustrationCard from "@/components/IllustrationCard.vue";
import ProgressCounter from "@/components/ProgressCounter.vue";
import CancelButton from "@/components/CancelButton.vue";
import RunErrorBanner from "@/components/RunErrorBanner.vue";

const route = useRoute();
const store = useRunStore();

const runId = computed(() => route.params.run_id as string);

const statusLabel = computed(() => {
  switch (store.run?.status) {
    case "RUNNING": return "Beží";
    case "COMPLETED": return "Hotovo";
    case "FAILED": return "Zlyhalo";
    case "CANCELLED": return "Zrušené";
    default: return "";
  }
});

const statusClass = computed(() => ({
  running: store.run?.status === "RUNNING",
  completed: store.run?.status === "COMPLETED",
  failed: store.run?.status === "FAILED",
  cancelled: store.run?.status === "CANCELLED",
}));

async function handleCancel() {
  await store.cancel();
}

onMounted(async () => {
  try {
    await store.loadRun(runId.value);
  } catch {
    // SSE snapshot will provide the state
  }
  store.subscribe(runId.value);
});

onUnmounted(() => {
  store.unsubscribe();
});
</script>

<style scoped lang="scss">
.run-view {
  max-width: 1000px;
  margin: 32px auto;
  padding: 0 24px;
}

.run-header {
  margin-bottom: 24px;
}

.back-link {
  display: inline-block;
  color: #555;
  text-decoration: none;
  font-size: 0.9em;
  margin-bottom: 8px;

  &:hover {
    color: #111;
  }
}

h1 {
  font-size: 1.8rem;
  font-weight: 700;
  color: #1a1a1a;
  margin: 0;
}

.run-meta {
  margin-bottom: 24px;
}

.status-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  border-radius: 16px;
  font-size: 0.85em;
  font-weight: 600;
  margin-bottom: 12px;

  &.running {
    background: #e3f2fd;
    color: #1565c0;
  }

  &.completed {
    background: #e8f5e9;
    color: #2e7d32;
  }

  &.failed {
    background: #ffebee;
    color: #c62828;
  }

  &.cancelled {
    background: #f5f5f5;
    color: #757575;
  }
}

.inline-spinner {
  display: inline-block;
  width: 12px;
  height: 12px;
  border: 2px solid rgba(21, 101, 192, 0.3);
  border-top-color: #1565c0;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.run-error,
.sse-error {
  color: #c62828;
  margin-bottom: 16px;
  font-size: 0.9em;
}

.illustration-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 20px;
}
</style>
