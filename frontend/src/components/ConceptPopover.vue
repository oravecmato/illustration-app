<template>
  <VDropdown
    :triggers="['click', 'hover', 'focus']"
    placement="bottom-end"
    :delay="{ show: 80, hide: 120 }"
  >
    <button
      type="button"
      class="info-trigger"
      :aria-label="$t('a11y.show_concept')"
      data-testid="concept-popover-trigger"
    >
      <svg
        viewBox="0 0 24 24"
        width="18"
        height="18"
        aria-hidden="true"
        focusable="false"
      >
        <circle cx="12" cy="12" r="10" fill="none" stroke="currentColor" stroke-width="1.6" />
        <circle cx="12" cy="8" r="1.2" fill="currentColor" />
        <path
          d="M12 11v6"
          fill="none"
          stroke="currentColor"
          stroke-width="1.6"
          stroke-linecap="round"
        />
      </svg>
    </button>
    <template #popper>
      <div class="concept-popover-body" data-testid="concept-popover-body">
        <div class="concept-label">{{ $t('illustration.currentConcept') }}</div>
        <div class="concept-text">{{ concept }}</div>
        <div
          v-if="salvage"
          class="salvage-note"
          data-testid="concept-popover-salvage-note"
        >
          {{ $t('illustration.salvaged') }}
        </div>
        <div
          v-if="salvage?.paragraph_text_override"
          class="salvage-note"
          data-testid="concept-popover-salvage-paragraph-note"
        >
          {{ $t('illustration.salvagedParagraphPatched') }}
        </div>
      </div>
    </template>
  </VDropdown>
</template>

<script setup lang="ts">
import { Dropdown as VDropdown } from "floating-vue";
import type { IllustrationSalvage } from "@/types";

defineProps<{ concept: string; salvage?: IllustrationSalvage | null }>();
</script>

<style scoped lang="scss">
.info-trigger {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: none;
  padding: 2px;
  color: #777;
  cursor: pointer;
  border-radius: 50%;
  transition: color 0.15s, background-color 0.15s;

  &:hover,
  &:focus-visible {
    color: #2c2c2c;
    background-color: rgba(0, 0, 0, 0.04);
    outline: none;
  }
}

.concept-popover-body {
  max-width: 320px;
  padding: 10px 12px;
  font-family: var(--font-body);
  font-size: 0.9rem;
  line-height: 1.45;
  color: #2a2a2a;
}

.concept-label {
  font-family: var(--font-heading);
  font-weight: 600;
  font-size: 0.8rem;
  letter-spacing: 0.02em;
  text-transform: uppercase;
  color: #555;
  margin-bottom: 4px;
}

.concept-text {
  white-space: normal;
}

.salvage-note {
  margin-top: 8px;
  padding-top: 6px;
  border-top: 1px dashed #ddd;
  font-size: 0.82rem;
  font-style: italic;
  color: #5a5a5a;
}
</style>
