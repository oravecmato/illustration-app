<template>
  <VDropdown
    :triggers="['click']"
    placement="bottom-end"
    :delay="{ show: 0, hide: 80 }"
  >
    <button
      type="button"
      class="kebab-trigger"
      :aria-label="$t('illustration.menu.aria_label')"
      data-testid="illustration-card-menu-trigger"
    >
      <svg
        viewBox="0 0 24 24"
        width="18"
        height="18"
        aria-hidden="true"
        focusable="false"
      >
        <circle cx="12" cy="5" r="1.6" fill="currentColor" />
        <circle cx="12" cy="12" r="1.6" fill="currentColor" />
        <circle cx="12" cy="19" r="1.6" fill="currentColor" />
      </svg>
    </button>
    <template #popper="{ hide }">
      <div class="menu-body" data-testid="illustration-card-menu-body">
        <button
          type="button"
          class="menu-item"
          :disabled="!canRegenerate"
          data-testid="illustration-card-menu-regenerate"
          @click="
            emit('regenerate');
            hide();
          "
        >
          {{ $t('illustration.menu.regenerate') }}
        </button>
        <button
          v-if="canShowChat && !isChatShown"
          type="button"
          class="menu-item"
          data-testid="illustration-card-menu-show-chat"
          @click="
            emit('show-chat');
            hide();
          "
        >
          {{ $t('illustration.menu.show_chat') }}
        </button>
        <button
          v-if="canShowChat && isChatShown"
          type="button"
          class="menu-item"
          data-testid="illustration-card-menu-hide-chat"
          @click="
            emit('hide-chat');
            hide();
          "
        >
          {{ $t('illustration.menu.hide_chat') }}
        </button>
      </div>
    </template>
  </VDropdown>
</template>

<script setup lang="ts">
import { Dropdown as VDropdown } from "floating-vue";

defineProps<{
  canRegenerate: boolean;
  canShowChat: boolean;
  isChatShown: boolean;
}>();

const emit = defineEmits<{
  (e: "regenerate"): void;
  (e: "show-chat"): void;
  (e: "hide-chat"): void;
}>();
</script>

<style scoped lang="scss">
.kebab-trigger {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: none;
  padding: 2px;
  color: #777;
  cursor: pointer;
  border-radius: 50%;
  transition:
    color 0.15s,
    background-color 0.15s;

  &:hover,
  &:focus-visible {
    color: #2c2c2c;
    background-color: rgba(0, 0, 0, 0.04);
    outline: none;
  }
}

.menu-body {
  display: flex;
  flex-direction: column;
  min-width: 180px;
  padding: 4px;
  font-family: var(--font-body);
  font-size: 0.9rem;
}

.menu-item {
  display: block;
  width: 100%;
  text-align: left;
  padding: 8px 12px;
  border: none;
  background: transparent;
  color: #2a2a2a;
  border-radius: 4px;
  cursor: pointer;
  font-size: inherit;
  font-family: inherit;

  &:hover:not(:disabled),
  &:focus-visible:not(:disabled) {
    background-color: rgba(0, 0, 0, 0.06);
    outline: none;
  }

  &:disabled {
    color: #aaa;
    cursor: not-allowed;
  }
}
</style>
