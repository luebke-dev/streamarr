<template>
  <q-tooltip
    anchor="top middle"
    self="bottom middle"
    :offset="[0, 12]"
    max-width="240px"
    class="episode-tooltip bg-dark"
  >
    <div v-if="episode" class="episode-tooltip-content">
      <div v-if="hasEpisodeNumber" class="text-caption text-grey-4 q-mb-xs">
        S{{ episode.season_number }}E{{ episode.sequence_number }}
      </div>
      <img
        v-if="episode.poster_path"
        :src="getTmdbImageUrl(episode.poster_path, 'w300')"
        class="episode-tooltip-still"
      />
      <div class="text-body2 text-white q-mt-xs">{{ episode.title }}</div>
    </div>
    <span v-else>{{ fallbackLabel }}</span>
  </q-tooltip>
</template>

<script setup>
import { computed } from 'vue'
import { getTmdbImageUrl } from 'src/composables/useMediaFormatters'

const props = defineProps({
  episode: { type: Object, default: null },
  fallbackLabel: { type: String, required: true },
})

const hasEpisodeNumber = computed(
  () => props.episode?.season_number != null && props.episode?.sequence_number != null,
)
</script>

<style lang="scss" scoped>
.episode-tooltip-content {
  padding: 4px;
  text-align: center;
}

.episode-tooltip-still {
  width: 100%;
  aspect-ratio: 16 / 9;
  object-fit: cover;
  border-radius: 4px;
}
</style>
