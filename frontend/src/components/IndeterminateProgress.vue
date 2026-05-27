<template>
  <div class="progress-counter" role="status" aria-busy="true">
    <span class="label">{{ $t('story.building_progress_label') }}</span>
    <div class="progress-bar">
      <div class="progress-accent" />
    </div>
  </div>
</template>

<script setup lang="ts"></script>

<style scoped lang="scss">
// Wrapper, label, and rail dimensions are intentionally identical to
// ProgressCounter.vue so the loading variant occupies the same space as
// the determinate counter. If you change one, change the other.
.progress-counter {
  margin-bottom: 16px;
}

.label {
  font-size: 0.95em;
  color: #444;
  display: block;
  margin-bottom: 6px;
}

.progress-bar {
  height: 6px;
  background: #e0e0e0;
  border-radius: 3px;
  overflow: hidden;
  position: relative;
}

.progress-accent {
  position: absolute;
  top: 0;
  left: 0;
  height: 100%;
  width: 30%;
  background: #4caf50;
  border-radius: 3px;
  animation: indeterminate-slide 1.4s linear infinite;
}

@keyframes indeterminate-slide {
  0% {
    transform: translateX(-100%);
  }
  100% {
    transform: translateX(333%);
  }
}
</style>
