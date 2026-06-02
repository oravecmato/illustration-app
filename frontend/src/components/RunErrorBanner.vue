<template>
  <div v-if="visible" class="run-error-banner">
    {{ message }}
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import type { Illustration, Run } from "@/types";
import { runErrorKey } from "@/i18n/runErrors";

const { t } = useI18n();
const props = defineProps<{
  run: Run | null;
  illustrations?: Illustration[];
}>();

// Suppress the run-level FAILED banner whenever the user is actively
// recovering an illustration via the § 6A manual flow. The run row
// stays stamped (e.g. INTERNAL_ERROR from the orphan-run reaper) until
// the user accepts something, but the banner would mislead them into
// thinking a fresh failure just happened.
const manualRecoveryActive = computed(() =>
  (props.illustrations ?? []).some((ill) =>
    ill.state === "MANUAL_CHATTING" ||
    ill.state === "MANUAL_GENERATING_PROMPTS" ||
    ill.state === "MANUAL_RENDERING",
  ),
);

const visible = computed(
  () => props.run !== null && props.run.status === "FAILED" && !manualRecoveryActive.value,
);

const message = computed(() => {
  const key = runErrorKey(props.run?.error_code);
  return key ? t(key) : '';
});
</script>

<style scoped lang="scss">
.run-error-banner {
  background: #ffebee;
  border: 1px solid #ef9a9a;
  border-radius: 6px;
  color: #b71c1c;
  padding: 12px 16px;
  margin-bottom: 20px;
  font-size: 0.95em;
  line-height: 1.5;
}
</style>
