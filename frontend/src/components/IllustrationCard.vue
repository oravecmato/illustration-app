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
      <span class="scene-number">Ilustrácia {{ illustration.scene_index + 1 }}</span>
      <span class="state-label">{{ stateLabel }}</span>
      <span v-if="isNonTerminal" class="spinner" aria-label="Načítava sa" />
    </div>

    <div v-if="showAttemptCounter" class="attempt-counter">
      pokus {{ attemptNumber }}/3
    </div>

    <div class="scene-excerpt">
      {{ truncatedExcerpt }}
    </div>

    <div
      v-if="illustration.current_concept"
      class="concept-text"
      data-testid="concept-text"
    >
      <span class="concept-label">Koncept:</span>
      {{ illustration.current_concept }}
    </div>

    <template v-if="illustration.state === 'COMPLETED' && illustration.image_url">
      <a :href="illustration.image_url" target="_blank" rel="noopener">
        <img
          :src="illustration.image_url"
          :alt="`Ilustrácia ${illustration.scene_index + 1}`"
          class="illustration-image"
        />
      </a>
    </template>

    <div v-if="illustration.state === 'FAILED'" class="error-message">
      <span class="sad-face">:(</span>
      Túto ilustráciu sa nepodarilo vytvoriť.
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import type { Illustration, IllustrationState } from "@/types";

const props = defineProps<{ illustration: Illustration }>();

const STATE_LABELS: Record<IllustrationState, string> = {
  PENDING: "Čaká",
  GENERATING_PROMPTS: "Pripravujem prompty",
  RENDERING: "Kreslím (pokus",
  EVALUATING: "Vyhodnocujem výsledok",
  REVISING_PROMPTS: "Upravujem prompty",
  RETHINKING_CONCEPT: "Premýšľam koncept",
  COMPLETED: "Hotovo",
  FAILED: "Nepodarilo sa",
  CANCELLED: "Zrušené",
};

const TERMINAL_STATES: IllustrationState[] = ["COMPLETED", "FAILED", "CANCELLED"];

const ATTEMPT_STATES: IllustrationState[] = ["RENDERING", "REVISING_PROMPTS", "RETHINKING_CONCEPT"];

const stateLabel = computed(() => {
  const base = STATE_LABELS[props.illustration.state];
  if (props.illustration.state === "RENDERING") {
    return `${base} ${props.illustration.prompt_attempt}/3)`;
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

const truncatedExcerpt = computed(() => {
  const excerpt = props.illustration.scene_excerpt;
  return excerpt.length > 200 ? excerpt.slice(0, 200) + "…" : excerpt;
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
  font-weight: 600;
  color: #333;
}

.state-label {
  font-size: 0.85em;
  color: #666;
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

.scene-excerpt {
  font-size: 0.85em;
  color: #555;
  font-style: italic;
  margin-bottom: 12px;
  line-height: 1.4;
}

.concept-text {
  font-size: 0.85em;
  color: #444;
  margin-bottom: 12px;
  line-height: 1.4;
  padding: 8px 10px;
  background: #f5f5f5;
  border-radius: 4px;
  transition: background-color 0.4s ease;
}

.concept-label {
  font-weight: 600;
  margin-right: 4px;
  color: #2c2c2c;
}

.illustration-image {
  width: 100%;
  max-height: 400px;
  object-fit: contain;
  border-radius: 4px;
  display: block;
}

.error-message {
  color: #c62828;
  font-size: 0.85em;
  margin-top: 8px;
}

.sad-face {
  margin-right: 4px;
}
</style>
