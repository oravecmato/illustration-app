<template>
  <div v-if="run !== null && run.status === 'FAILED'" class="run-error-banner">
    {{ message }}
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import type { Run } from "@/types";
import { getRunErrorMessage } from "@/i18n/runErrors";

const props = defineProps<{ run: Run | null }>();

const message = computed(() => getRunErrorMessage(props.run?.error_code));
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
