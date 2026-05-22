<template>
  <div class="home-view">
    <h1 class="app-title">Anime ilustrátor</h1>

    <div class="form-group">
      <label for="story-input" class="form-label">Text príbehu</label>
      <textarea
        id="story-input"
        v-model="storyText"
        class="story-textarea"
        rows="12"
        :maxlength="STORY_MAX_CHARS"
        placeholder="Sem vložte text rozprávky..."
      />
      <div class="char-counter" :class="{ over: storyText.length > STORY_MAX_CHARS }">
        {{ storyText.length }} / {{ STORY_MAX_CHARS }}
      </div>
    </div>

    <button
      class="submit-btn"
      :disabled="!canSubmit"
      @click="handleSubmit"
    >
      <span v-if="loading" class="btn-spinner" />
      Vygenerovať ilustrácie
    </button>

    <p v-if="error" class="error-msg">{{ error }}</p>

    <p class="hint-text">
      Aplikácia vyberie vhodné miesta v texte a vygeneruje k nim anime ilustrácie.
      Trvá to niekoľko minút.
    </p>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from "vue";
import { useRouter } from "vue-router";
import { useRunStore } from "@/stores/run";

const STORY_MAX_CHARS = 50000;

const router = useRouter();
const store = useRunStore();

const storyText = ref("");
const loading = ref(false);
const error = ref<string | null>(null);

const canSubmit = computed(
  () => storyText.value.trim().length > 0 && storyText.value.length <= STORY_MAX_CHARS && !loading.value
);

async function handleSubmit() {
  if (!canSubmit.value) return;
  loading.value = true;
  error.value = null;
  try {
    const runId = await store.startRun(storyText.value);
    await router.push(`/runs/${runId}`);
  } catch (err) {
    error.value = err instanceof Error ? err.message : "Nastala chyba. Skúste znova.";
  } finally {
    loading.value = false;
  }
}
</script>

<style scoped lang="scss">
.home-view {
  max-width: 700px;
  margin: 48px auto;
  padding: 0 24px;
}

.app-title {
  font-size: 2rem;
  font-weight: 700;
  margin-bottom: 32px;
  color: #1a1a1a;
}

.form-group {
  margin-bottom: 16px;
}

.form-label {
  display: block;
  font-weight: 600;
  margin-bottom: 8px;
  color: #333;
}

.story-textarea {
  width: 100%;
  resize: vertical;
  padding: 12px;
  border: 1px solid #ccc;
  border-radius: 6px;
  font-size: 1rem;
  line-height: 1.5;
  font-family: inherit;
  box-sizing: border-box;

  &:focus {
    outline: none;
    border-color: #555;
  }
}

.char-counter {
  text-align: right;
  font-size: 0.8em;
  color: #888;
  margin-top: 4px;

  &.over {
    color: #c62828;
    font-weight: 600;
  }
}

.submit-btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 10px 24px;
  background: #2c2c2c;
  color: #fff;
  border: none;
  border-radius: 6px;
  font-size: 1rem;
  cursor: pointer;
  margin-bottom: 16px;

  &:hover:not(:disabled) {
    background: #444;
  }

  &:disabled {
    background: #aaa;
    cursor: not-allowed;
  }
}

.btn-spinner {
  display: inline-block;
  width: 14px;
  height: 14px;
  border: 2px solid rgba(255, 255, 255, 0.4);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.error-msg {
  color: #c62828;
  margin-bottom: 12px;
}

.hint-text {
  color: #777;
  font-size: 0.9em;
  margin-top: 8px;
}
</style>
