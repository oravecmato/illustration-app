<template>
  <article class="story">
    <template v-if="loading">
      <!-- Loading variant: 5 paragraph+illustration pairs of skeletons
           that match the real layout exactly (same wrappers, gaps,
           max-width). Per-card chrome (header, excerpt, border) is
           intentionally omitted — only the slot shape is reserved. -->
      <template v-for="i in 5" :key="`skeleton-${i}`">
        <div class="story-paragraph">
          <SkeletonBlock shape="text" :lines="4" />
        </div>
        <div class="story-illustration">
          <SkeletonBlock shape="rect" aspect-ratio="1 / 1" />
        </div>
      </template>
    </template>
    <template v-else>
      <template v-for="(block, idx) in blocks" :key="idx">
        <StoryParagraph
          v-if="block.type === 'paragraph'"
          :paragraph-index="idx"
        />
        <div v-else class="story-illustration">
          <IllustrationCard
            v-if="illustrationByScene.get(block.scene_index)"
            :illustration="illustrationByScene.get(block.scene_index)!"
          />
          <div v-else class="illustration-missing">
            {{ $t('story.illustration_not_ready') }}
          </div>
        </div>
      </template>
    </template>
  </article>
</template>

<script setup lang="ts">
import IllustrationCard from "@/components/IllustrationCard.vue";
import StoryParagraph from "@/components/StoryParagraph.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import type { Illustration, StoryBlock } from "@/types";

withDefaults(
  defineProps<{
    blocks?: StoryBlock[];
    illustrationByScene?: Map<number, Illustration>;
    loading?: boolean;
  }>(),
  {
    blocks: () => [],
    illustrationByScene: () => new Map(),
    loading: false,
  },
);
</script>

<style scoped lang="scss">
.story {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

// Mirrors StoryParagraph.vue's outer wrapper margins so skeleton
// paragraphs occupy the same vertical rhythm as real ones.
.story-paragraph {
  margin-bottom: 1.1em;
}

.story-illustration {
  margin: 12px auto;
  width: 100%;
  max-width: 560px;
}

.illustration-missing {
  padding: 24px;
  border: 1px dashed #ccc;
  border-radius: 8px;
  text-align: center;
  color: #888;
  font-style: italic;
}
</style>
