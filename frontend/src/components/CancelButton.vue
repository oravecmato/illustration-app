<template>
  <div v-if="runStatus === 'RUNNING'" class="cancel-button-wrapper">
    <template v-if="!confirming">
      <button class="cancel-btn" @click="confirming = true">Zrušiť beh</button>
    </template>
    <template v-else>
      <span class="confirm-text">Naozaj zrušiť?</span>
      <button class="confirm-yes" @click="onConfirm">Áno</button>
      <button class="confirm-no" @click="confirming = false">Nie</button>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref } from "vue";
import type { RunStatus } from "@/types";

defineProps<{ runStatus: RunStatus | null }>();
const emit = defineEmits<{ cancel: [] }>();

const confirming = ref(false);

function onConfirm() {
  confirming.value = false;
  emit("cancel");
}
</script>

<style scoped lang="scss">
.cancel-button-wrapper {
  display: flex;
  align-items: center;
  gap: 8px;
}

.cancel-btn {
  padding: 6px 16px;
  border: 1px solid #c62828;
  background: transparent;
  color: #c62828;
  border-radius: 4px;
  cursor: pointer;

  &:hover {
    background: #ffebee;
  }
}

.confirm-text {
  font-size: 0.9em;
  color: #555;
}

.confirm-yes,
.confirm-no {
  padding: 4px 12px;
  border-radius: 4px;
  cursor: pointer;
  border: 1px solid #ccc;
  background: #fff;

  &:hover {
    background: #f5f5f5;
  }
}

.confirm-yes {
  border-color: #c62828;
  color: #c62828;
}
</style>
