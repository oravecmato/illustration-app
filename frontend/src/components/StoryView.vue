<template>
  <article class="story">
    <template v-for="(block, idx) in blocks" :key="idx">
      <p v-if="block.type === 'paragraph'" class="paragraph">
        {{ block.text }}
      </p>
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
  gap: 20px;
}

.paragraph {
  margin: 0;
  font-size: 1.05rem;
  line-height: 1.7;
  color: #1a1a1a;
}

.story-illustration {
  margin: 8px auto;
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
