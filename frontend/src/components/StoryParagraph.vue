<template>
  <div class="story-paragraph">
    <SkeletonBlock v-if="isRegenerating" shape="text" :lines="3" />
    <p v-else class="paragraph-text" data-testid="story-paragraph">
      {{ text }}
    </p>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { useRunStore } from "@/stores/run";
import SkeletonBlock from "./SkeletonBlock.vue";

const props = defineProps<{ paragraphIndex: number }>();

const runStore = useRunStore();

const text = computed(() => runStore.paragraphAt(props.paragraphIndex));
const isRegenerating = computed(() =>
  runStore.isParagraphRegenerating(props.paragraphIndex),
);
</script>

<style scoped lang="scss">
.story-paragraph {
  margin-bottom: 1.1em;
}

.paragraph-text {
  margin: 0;
  font-family: var(--font-body);
  font-size: 1.05rem;
  line-height: 1.7;
  color: #2a2a2a;
}
</style>
