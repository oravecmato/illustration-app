<template>
  <div
    class="illustration-card"
    :class="{
      cancelled: illustration.state === 'CANCELLED',
      completed: illustration.state === 'COMPLETED',
      failed: illustration.state === 'FAILED',
    }"
  >
    <div class="card-header">
      <span class="scene-number">{{ t('story.illustration_n', { n: illustration.scene_index + 1 }) }}</span>
      <span class="state-label">{{ stateLabel }}</span>
      <span v-if="isNonTerminal" class="spinner" :aria-label="t('a11y.loading')" />
      <span class="header-spacer" />
      <ConceptPopover
        v-if="illustration.current_concept"
        :concept="illustration.current_concept"
      />
    </div>

    <div v-if="showAttemptCounter" class="attempt-counter">
      {{ t('illustration.attempt', { current: attemptNumber, max: 3 }) }}
    </div>

    <div v-if="illustration.companion" class="companion-subtitle">
      {{ t('illustration.companion_subtitle', { description: illustration.companion.description }) }}
    </div>

    <div class="image-slot">
      <a
        v-if="illustration.state === 'COMPLETED' && illustration.image_url"
        :href="illustration.image_url"
        target="_blank"
        rel="noopener"
      >
        <img
          :src="illustration.image_url"
          :alt="t('story.illustration_n', { n: illustration.scene_index + 1 })"
          class="illustration-image"
        />
      </a>
      <div
        v-else-if="illustration.state === 'FAILED'"
        class="image-failed"
      >
        <span class="sad-face">:(</span>
        {{ t('story.illustration_failed') }}
      </div>
      <SkeletonBlock v-else shape="rect" aspect-ratio="1 / 1" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import type { Illustration, IllustrationState } from "@/types";
import ConceptPopover from "./ConceptPopover.vue";
import SkeletonBlock from "./SkeletonBlock.vue";

const props = defineProps<{ illustration: Illustration }>();

const { t } = useI18n();

const TERMINAL_STATES: IllustrationState[] = ["COMPLETED", "FAILED", "CANCELLED"];

const ATTEMPT_STATES: IllustrationState[] = ["RENDERING", "REVISING_PROMPTS", "RETHINKING_CONCEPT"];

const stateLabel = computed(() => {
  const base = t(`illustration.state.${props.illustration.state}`);
  if (props.illustration.state === "RENDERING") {
    return `${base} (${t("illustration.attempt", { current: props.illustration.prompt_attempt, max: 3 })})`;
  }
  return base;
});

const isNonTerminal = computed(() => !TERMINAL_STATES.includes(props.illustration.state));

const showAttemptCounter = computed(() => ATTEMPT_STATES.includes(props.illustration.state));

const attemptNumber = computed(() => {
  if (props.illustration.state === "RETHINKING_CONCEPT") {
    return props.illustration.concept_attempt;
  }
  return props.illustration.prompt_attempt;
});
</script>

<style scoped lang="scss">
.illustration-card {
  border: 1px solid #ddd;
  border-radius: 8px;
  padding: 16px;
  background: #fff;
  transition: opacity 0.3s;

  &.cancelled {
    opacity: 0.5;
  }

  &.completed {
    border-color: #4caf50;
  }

  &.failed {
    border-color: #f44336;
  }
}

.card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.scene-number {
  font-family: var(--font-heading);
  font-weight: 600;
  color: #333;
}

.state-label {
  font-size: 0.85em;
  color: #666;
}

.header-spacer {
  flex: 1 1 auto;
}

.spinner {
  display: inline-block;
  width: 14px;
  height: 14px;
  border: 2px solid #ccc;
  border-top-color: #555;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.attempt-counter {
  font-size: 0.8em;
  color: #888;
  margin-bottom: 6px;
}

.companion-subtitle {
  font-size: 0.8em;
  color: #777;
  margin-bottom: 12px;
  font-family: var(--font-body);
}

.image-slot {
  width: 100%;
  aspect-ratio: 1 / 1;
  display: flex;
  align-items: stretch;
  justify-content: stretch;
}

.illustration-image {
  width: 100%;
  height: 100%;
  object-fit: cover;
  border-radius: 4px;
  display: block;
}

.image-slot a {
  display: block;
  width: 100%;
  height: 100%;
}

.image-failed {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  text-align: center;
  color: #c62828;
  font-size: 0.9em;
  background: #faf2f2;
  border: 1px dashed #e7b6b6;
  border-radius: 4px;
  padding: 12px;
}

.sad-face {
  margin-right: 4px;
}
</style>
