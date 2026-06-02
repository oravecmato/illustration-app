<template>
  <div class="run-view">
    <div class="run-header">
      <router-link to="/" class="back-link">{{ $t('app.new_story') }}</router-link>
      <h1>{{ headingText }}</h1>
    </div>

    <div class="run-meta">
      <div class="status-row">
        <span class="status-pill" :class="statusClass">
          <span v-if="isLoading || store.run?.status === 'RUNNING'" class="inline-spinner" />
          {{ statusLabel }}
        </span>
        <span v-if="isTranslating" class="status-pill translating">
          <span class="inline-spinner translating-spinner" />
          {{ t('run.status.translating') }}
        </span>
      </div>

      <RunErrorBanner v-if="store.run" :run="store.run" :illustrations="store.illustrations" />

      <IndeterminateProgress v-if="isLoading" />
      <ProgressCounter
        v-else-if="store.run"
        :completed-count="store.completedCount"
        :illustration-count="store.run.illustration_count > 0 ? store.run.illustration_count : null"
      />

      <CancelButton v-if="store.run" :run-status="store.run.status" @cancel="handleCancel" />
    </div>

    <div v-if="store.sseError" class="sse-error">
      {{ store.sseError }}
    </div>

    <StoryView
      :loading="isLoading"
      :blocks="store.run?.story_blocks"
      :illustration-by-scene="store.illustrationByScene"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, watch } from "vue";
import { useRoute } from "vue-router";
import { useI18n } from "vue-i18n";
import { useRunStore } from "@/stores/run";
import { useSessionStore } from "@/stores/session";
import type { Language } from "@/types";
import StoryView from "@/components/StoryView.vue";
import ProgressCounter from "@/components/ProgressCounter.vue";
import IndeterminateProgress from "@/components/IndeterminateProgress.vue";
import CancelButton from "@/components/CancelButton.vue";
import RunErrorBanner from "@/components/RunErrorBanner.vue";

const route = useRoute();
const store = useRunStore();
const sessionStore = useSessionStore();
const { t } = useI18n();

const runId = computed(() => route.params.run_id as string);
const urlLang = computed(() => route.params.lang as Language | undefined);

// "Loading" means the run object has not yet been materialised — either
// because we just navigated in from finalize and the first snapshot has
// not arrived, or because the page was refreshed mid-generation and
// loadRun is still in flight. Once `store.run` is set, the page swaps
// to the live variant at the leaf-slot level (no shell remount).
const isLoading = computed(() => store.run === null);

// Title fallback chain (see TECHNICAL_DECISIONS.md > Refresh resilience):
//   real story_title → topicShort from chat session → localised
//   "Generating story…" placeholder. Keeps the <h1> non-empty at every
//   frame, including after a browser refresh that drops Pinia state.
const headingText = computed(
  () => store.run?.story_title ?? sessionStore.topicShort ?? t("story.building"),
);

const statusLabel = computed(() => {
  if (isLoading.value) return t("story.building");
  const status = store.run?.status;
  return status ? t(`run.status.${status}`) : "";
});

// True while Agent 5 is translating at least one paragraph of the run
// into the currently displayed language. Mirrors the per-paragraph
// skeletons in StoryParagraph so the user sees a single, app-level
// indicator that the translation is in flight.
const isTranslating = computed(() => store.pendingParagraphTranslations.size > 0);

const statusClass = computed(() => ({
  running: isLoading.value || store.run?.status === "RUNNING",
  completed: !isLoading.value && store.run?.status === "COMPLETED",
  failed: !isLoading.value && store.run?.status === "FAILED",
  cancelled: !isLoading.value && store.run?.status === "CANCELLED",
}));

async function handleCancel() {
  await store.cancel();
}

onMounted(() => {
  // Don't call GET /api/runs/:id here — the SSE endpoint already returns
  // a fully-formed snapshot in all three cases (pre-creation race with
  // Agent 0b, active run, terminal run after server restart). Calling
  // GET first would race with Agent 0b and 404 during the pre-creation
  // window.
  store.reset();
  store.subscribe(runId.value, urlLang.value);
});

// First-mount equivalent of switchLanguage: once the SSE snapshot
// hydrates `store.run`, if the URL targets a non-source language,
// request any missing/stale translations. The route.params.lang watch
// below only fires on *changes*, so without this, landing directly on
// /en/runs/:id never triggers translation.
const stopRunWatch = watch(
  () => store.run,
  async (run) => {
    if (!run) return;
    stopRunWatch();
    if (urlLang.value && urlLang.value !== run.source_language) {
      await store.ensureTranslations(urlLang.value);
    }
  },
);

// React to URL-driven language changes (browser back/forward, or any other
// route mutation that doesn't go through localeStore.setLanguage, which
// already calls runStore.switchLanguage for switcher-initiated changes).
watch(
  () => route.params.lang,
  (newLang) => {
    if (newLang && store.run) {
      store.switchLanguage(newLang as Language);
    }
  },
);

onUnmounted(() => {
  store.unsubscribe();
});
</script>

<style scoped lang="scss">
.run-view {
  max-width: 760px;
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

.status-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}

.status-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  border-radius: 16px;
  font-size: 0.85em;
  font-weight: 600;

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

  &.translating {
    background: #fff7e6;
    color: #b26a00;
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

.inline-spinner.translating-spinner {
  border-color: rgba(178, 106, 0, 0.3);
  border-top-color: #b26a00;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.sse-error {
  color: #c62828;
  margin-bottom: 16px;
  font-size: 0.9em;
}
</style>
