<template>
  <div class="chat-message" :class="`role-${role}`">
    <div class="bubble">{{ content }}</div>
  </div>
</template>

<script setup lang="ts">
import type { MessageRole } from "@/types";

defineProps<{
  role: MessageRole;
  content: string;
}>();
</script>

<style scoped lang="scss">
.chat-message {
  display: flex;
  width: 100%;
}

.role-user {
  justify-content: flex-end;
}

.role-assistant {
  justify-content: flex-start;
}

.bubble {
  max-width: 80%;
  padding: 10px 14px;
  border-radius: 12px;
  white-space: pre-wrap;
  line-height: 1.45;
  font-size: 0.98rem;
}

.role-user .bubble {
  background: #2c2c2c;
  color: #fff;
  border-bottom-right-radius: 4px;
}

.role-assistant .bubble {
  background: #fff;
  color: #1a1a1a;
  border: 1px solid #e0e0e0;
  border-bottom-left-radius: 4px;
}
</style>
