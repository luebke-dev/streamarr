<template>
  <div class="media-loading-state flex flex-center q-pa-xl">
    <q-spinner-dots :size="size" :color="color" />
  </div>
</template>

<script setup>
defineProps({
  /**
   * Size of the spinner
   */
  size: {
    type: String,
    default: '50px',
  },
  /**
   * Color of the spinner
   */
  color: {
    type: String,
    default: 'primary',
  },
})
</script>

<style lang="scss" scoped>
.media-loading-state {
  min-height: 60vh;

  .q-spinner-dots {
    filter: drop-shadow(0 0 10px rgba(66, 165, 245, 0.5));
  }
}
</style>
