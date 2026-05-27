<template>
  <div
    class="skeleton-block"
    :class="`shape-${shape}`"
    :style="blockStyle"
    role="status"
    aria-busy="true"
    :aria-label="$t('a11y.loading')"
  >
    <template v-if="shape === 'text'">
      <div
        v-for="i in lines"
        :key="i"
        class="skeleton-line"
        :style="{ width: lineWidth(i) }"
      />
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";

const props = withDefaults(
  defineProps<{
    shape?: "text" | "rect";
    lines?: number;
    aspectRatio?: string;
  }>(),
  {
    shape: "text",
    lines: 3,
    aspectRatio: "1 / 1",
  },
);

const blockStyle = computed(() => {
  if (props.shape === "rect") {
    return { aspectRatio: props.aspectRatio };
  }
  return {};
});

function lineWidth(index: number): string {
  // Vary widths so the placeholder reads as prose, not bars of equal length.
  const last = index === props.lines;
  if (last) return `${50 + ((index * 7) % 25)}%`;
  return `${85 + ((index * 5) % 15)}%`;
}
</script>

<style scoped lang="scss">
.skeleton-block {
  --skeleton-base: #e8e4dc;
  --skeleton-highlight: #f4f0e6;

  &.shape-rect {
    width: 100%;
    background: var(--skeleton-base);
    border-radius: 4px;
    background-image: linear-gradient(
      90deg,
      var(--skeleton-base) 0%,
      var(--skeleton-highlight) 50%,
      var(--skeleton-base) 100%
    );
    background-size: 200% 100%;
    animation: skeleton-shimmer 1.4s ease-in-out infinite;
  }

  &.shape-text {
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 4px 0;
  }
}

.skeleton-line {
  height: 0.9em;
  background: var(--skeleton-base);
  border-radius: 3px;
  background-image: linear-gradient(
    90deg,
    var(--skeleton-base) 0%,
    var(--skeleton-highlight) 50%,
    var(--skeleton-base) 100%
  );
  background-size: 200% 100%;
  animation: skeleton-shimmer 1.4s ease-in-out infinite;
}

@keyframes skeleton-shimmer {
  0% {
    background-position: 200% 0;
  }
  100% {
    background-position: -200% 0;
  }
}
</style>
