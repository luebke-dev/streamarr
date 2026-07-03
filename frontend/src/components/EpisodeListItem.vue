<template>
  <q-card flat class="episode-card bg-grey-9 cursor-pointer" @click="$emit('view-child', episode)">
    <div class="row no-wrap">
      <div class="episode-thumbnail">
        <q-img :src="getPosterUrl(episode)" :ratio="16 / 9" class="full-height">
          <template #error>
            <div class="absolute-full flex flex-center bg-grey-8">
              <q-icon name="mdi-television" size="48px" color="grey-6" />
            </div>
          </template>
          <div class="absolute-bottom episode-number-overlay">
            <div class="text-h6 text-bold">
              {{ episode.sequence_number ? `${episode.sequence_number}` : '?' }}
            </div>
          </div>
          <div class="absolute-full flex flex-center episode-play-overlay">
            <q-icon name="mdi-play-circle" size="64px" color="white" />
          </div>
        </q-img>
      </div>

      <div class="episode-info col">
        <q-card-section>
          <div class="row items-center justify-between">
            <div class="col">
              <div class="text-h6 text-white q-mb-xs">
                {{
                  episode.sequence_number
                    ? `${episode.sequence_number}. ${episode.title}`
                    : episode.title
                }}
              </div>
              <div class="text-caption text-grey-5 q-mb-sm">
                {{ formatFullDate(episode.release_date) }}
                <span v-if="episode.runtime"> • {{ formatRuntime(episode.runtime) }} </span>
              </div>
            </div>
            <q-btn
              v-if="episode.files && episode.files.length > 0"
              round
              color="primary"
              icon="mdi-play"
              size="md"
              class="q-ml-md"
              @click.stop="$emit('play-episode', episode)"
            />
          </div>
          <div class="text-body2 text-grey-3 episode-description">
            {{ episode.description || $t('common.noDescriptionAvailable') }}
          </div>
        </q-card-section>
      </div>
    </div>
  </q-card>
</template>

<script setup>
import { useMediaHelpers } from 'src/composables/useMediaHelpers'

defineProps({
  episode: { type: Object, required: true },
})

defineEmits(['view-child', 'play-episode'])

const { getPosterUrl, formatFullDate, formatRuntime } = useMediaHelpers()
</script>

<style lang="scss" scoped>
.episode-card {
  transition: all 0.3s ease;
  border-radius: 8px;
  overflow: hidden;

  &:hover {
    transform: translateY(-2px);
    box-shadow: 0 8px 16px rgba(0, 0, 0, 0.4);

    .episode-play-overlay {
      opacity: 1;
    }
  }
}

.episode-thumbnail {
  width: 280px;
  min-width: 280px;
  position: relative;
}

.episode-number-overlay {
  background: linear-gradient(to top, rgba(0, 0, 0, 0.8), transparent);
  padding: 8px 12px;
}

.episode-play-overlay {
  background: rgba(0, 0, 0, 0.6);
  opacity: 0;
  transition: opacity 0.3s ease;
  backdrop-filter: blur(2px);
}

.episode-info {
  display: flex;
  flex-direction: column;
}

.episode-description {
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  line-clamp: 3;
  -webkit-box-orient: vertical;
  line-height: 1.5;
}

@media (max-width: 1024px) {
  .episode-thumbnail {
    width: 200px;
    min-width: 200px;
  }
}

@media (max-width: 768px) {
  .episode-card .row {
    flex-direction: column;
  }

  .episode-thumbnail {
    width: 100%;
    min-width: 100%;
  }
}
</style>
