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
      <span v-if="showHeaderSpinner" class="spinner" :aria-label="t('a11y.loading')" />
      <span class="header-spacer" />
      <IllustrationCardMenu
        v-if="showMenu"
        :can-regenerate="canRegenerate"
        :can-show-chat="canShowChat"
        :is-chat-shown="viewMode === 'chat'"
        @regenerate="handleRegenerateClick"
        @show-chat="runStore.showManualChat(illustration.id)"
        @hide-chat="runStore.hideManualChat(illustration.id)"
      />
      <ConceptPopover
        v-if="illustration.current_concept"
        :concept="illustration.current_concept"
      />
    </div>

    <div v-if="showAttemptCounter" class="attempt-counter">
      {{ t('illustration.attempt', { current: attemptNumber, max: 3 }) }}
    </div>

    <div v-if="illustration.contains_entity_label" class="entity-subtitle">
      {{ t('illustration.entity_subtitle', { label: illustration.contains_entity_label }) }}
    </div>

    <div v-if="viewMode !== 'chat'" class="image-slot">
      <a
        v-if="hasImage"
        :href="illustration.image_url!"
        target="_blank"
        rel="noopener"
      >
        <img
          :src="illustration.image_url!"
          :alt="t('story.illustration_n', { n: illustration.scene_index + 1 })"
          class="illustration-image"
        />
      </a>
      <div
        v-else-if="showFailedPlaceholder"
        class="image-failed"
      >
        <span class="sad-face">:(</span>
        {{ t('story.illustration_failed') }}
      </div>
      <SkeletonBlock v-else shape="rect" aspect-ratio="1 / 1" />
    </div>

    <ManualChatPanel
      v-if="viewMode === 'chat'"
      :illustration="illustration"
      @close="runStore.hideManualChat(illustration.id)"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import type { Illustration, IllustrationState } from "@/types";
import { useRunStore } from "@/stores/run";
import ConceptPopover from "./ConceptPopover.vue";
import IllustrationCardMenu from "./IllustrationCardMenu.vue";
import ManualChatPanel from "./ManualChatPanel.vue";
import SkeletonBlock from "./SkeletonBlock.vue";

const props = defineProps<{ illustration: Illustration }>();

const { t } = useI18n();
const runStore = useRunStore();

const TERMINAL_STATES: IllustrationState[] = ["COMPLETED", "FAILED", "CANCELLED"];

const ATTEMPT_STATES: IllustrationState[] = [
  "RENDERING",
  "REVISING_PROMPTS",
  "RETHINKING_CONCEPT",
  "RETHINKING_ENVIRONMENT",
];

const MANUAL_STATES: IllustrationState[] = [
  "MANUAL_CHATTING",
  "MANUAL_GENERATING_PROMPTS",
  "MANUAL_RENDERING",
];

const MAX_MANUAL_ATTEMPTS = 5;

const regenInFlight = ref(false);

const hasImage = computed(
  () => !!props.illustration.image_url && props.illustration.state !== "FAILED",
);
const isCompleted = computed(() => props.illustration.state === "COMPLETED");
const isManualState = computed(() => MANUAL_STATES.includes(props.illustration.state));
const budgetLeft = computed(
  () => (props.illustration.manual_attempts ?? 0) < MAX_MANUAL_ATTEMPTS,
);
// A session exists when we are mid-manual or have any persisted manual data.
const sessionExists = computed(
  () =>
    isManualState.value ||
    !!props.illustration.manual_session ||
    props.illustration.state === "FAILED",
);

// View mode resolution (§ 6A.9):
//   - explicit toggle wins
//   - otherwise default to image when one exists (even mid-regen)
//   - otherwise show chat if a session exists with budget left
//   - otherwise placeholder
const viewMode = computed<"image" | "chat" | "placeholder">(() => {
  const toggle = runStore.chatToggle[props.illustration.id];
  if (toggle === "shown") return "chat";
  if (toggle === "hidden") return hasImage.value ? "image" : "placeholder";

  if (hasImage.value) return "image";
  if (sessionExists.value && budgetLeft.value) return "chat";
  return "placeholder";
});

const canRegenerate = computed(
  () => isCompleted.value && budgetLeft.value && !regenInFlight.value,
);
// Chat remains accessible after budget exhaustion (§ 6A.10): the user
// can still open the chat to click "Use" on a prior ManualImageCard
// attempt and promote it to the canonical illustration.
const canShowChat = computed(() => sessionExists.value && !isCompleted.value);
const showMenu = computed(() => canRegenerate.value || canShowChat.value);

// The "could not be created" placeholder only after even the manual budget
// has been exhausted.
const showFailedPlaceholder = computed(() => {
  return (
    props.illustration.state === "FAILED" &&
    (props.illustration.manual_attempts ?? 0) >= MAX_MANUAL_ATTEMPTS
  );
});

async function handleRegenerateClick(): Promise<void> {
  if (props.illustration.state === "COMPLETED") {
    regenInFlight.value = true;
    try {
      await runStore.regenerateIllustration(props.illustration.id);
    } finally {
      regenInFlight.value = false;
    }
  } else {
    // MANUAL_CHATTING / FAILED-with-budget: no API call — just reveal chat.
    runStore.showManualChat(props.illustration.id);
  }
}

const stateLabel = computed(() => {
  const base = t(`illustration.state.${props.illustration.state}`);
  if (props.illustration.state === "RENDERING") {
    return `${base} (${t("illustration.attempt", { current: props.illustration.prompt_attempt, max: 3 })})`;
  }
  return base;
});

const isNonTerminal = computed(() => !TERMINAL_STATES.includes(props.illustration.state));

// Header spinner is suppressed in MANUAL_CHATTING — that's an
// idle-waiting-for-user state, not a "work in progress" state. It only
// spins during the actual image pipeline: prompt generation and render
// (both auto and manual variants).
const showHeaderSpinner = computed(
  () => isNonTerminal.value && props.illustration.state !== "MANUAL_CHATTING",
);

const showAttemptCounter = computed(() => ATTEMPT_STATES.includes(props.illustration.state));

const attemptNumber = computed(() => {
  if (
    props.illustration.state === "RETHINKING_CONCEPT" ||
    props.illustration.state === "RETHINKING_ENVIRONMENT"
  ) {
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

.entity-subtitle {
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
