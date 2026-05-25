<template>
  <article class="story">
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
          Ilustrácia ešte nie je pripravená…
        </div>
      </div>
    </template>
  </article>
</template>

<script setup lang="ts">
import IllustrationCard from "@/components/IllustrationCard.vue";
import StoryParagraph from "@/components/StoryParagraph.vue";
import type { Illustration, StoryBlock } from "@/types";

defineProps<{
  blocks: StoryBlock[];
  illustrationByScene: Map<number, Illustration>;
}>();
</script>

<style scoped lang="scss">
.story {
  display: flex;
  flex-direction: column;
  gap: 4px;
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
