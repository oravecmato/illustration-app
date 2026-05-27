<template>
  <div v-if="!hidden" class="progress-counter">
    <span class="label">{{ labelText }}</span>
    <div v-if="illustrationCount !== null && illustrationCount > 0" class="progress-bar">
      <div
        class="progress-fill"
        :style="{ width: `${(completedCount / illustrationCount) * 100}%` }"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";

const props = withDefaults(
  defineProps<{
    completedCount: number;
    illustrationCount: number | null;
    hidden?: boolean;
  }>(),
  { hidden: false }
);

const { t } = useI18n();

const labelText = computed(() =>
  props.illustrationCount === null
    ? t("run.progress_unknown", { completed: props.completedCount })
    : t("run.progress", { completed: props.completedCount, total: props.illustrationCount }),
);
</script>

<style scoped lang="scss">
.progress-counter {
  margin-bottom: 16px;
}

.label {
  font-size: 0.95em;
  color: #444;
  display: block;
  margin-bottom: 6px;
}

.progress-bar {
  height: 6px;
  background: #e0e0e0;
  border-radius: 3px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: #4caf50;
  border-radius: 3px;
  transition: width 0.3s ease;
}
</style>
