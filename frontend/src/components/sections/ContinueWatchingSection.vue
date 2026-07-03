<template>
  <div class="section-container">
    <ContinueWatching :content-type="contentType" />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import ContinueWatching from 'src/components/ContinueWatching.vue'

const props = defineProps({
  section: { type: Object, required: true },
  mediaType: { type: String, default: null },
})

const contentType = computed(() => {
  const config = props.section.config || {}
  if (config.content_type) return config.content_type
  if (!props.mediaType) return null
  const t = props.mediaType.toUpperCase()
  if (t === 'MOVIES') return 'movie'
  if (t === 'SHOWS') return 'episode'
  if (t === 'GAMES') return 'game'
  if (t === 'MUSIC') return 'music'
  if (t === 'BOOKS') return 'book'
  return null
})
</script>
