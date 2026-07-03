<template>
  <div class="continue-watching-section">
    <div v-if="showTitle" class="section-header">
      <h4 class="section-title">{{ sectionTitle }}</h4>
    </div>
    <div v-if="continueWatchingItems.length > 0" class="continue-watching-scroll">
      <div v-for="item in continueWatchingItems" :key="item.guid" class="continue-watching-item">
        <q-card class="continue-watching-card cursor-pointer" flat @click="navigateToDetail(item)">
          <q-img
            :src="getCardPosterUrl(item)"
            :alt="getTitle(item)"
            :ratio="isMusicItem(item) ? 1 : 16 / 9"
            class="rounded-borders"
          >
            <!-- Dark gradient overlay -->
            <div class="absolute-full overlay-gradient"></div>

            <!-- Play button in center -->
            <q-icon
              name="mdi-play-circle"
              size="48px"
              color="white"
              class="play-icon centered-icon"
              @click.stop="navigateToPlay(item)"
            />

            <!-- Bottom overlay with title and progress -->
            <div class="absolute-bottom content-overlay q-pa-sm">
              <div class="text-subtitle2 ellipsis-2-lines text-white">{{ getTitle(item) }}</div>
              <q-linear-progress
                :value="item.progress_percentage / 100"
                color="primary"
                track-color="grey-8"
                size="4px"
                class="q-mt-sm"
              />
            </div>
          </q-img>
        </q-card>
      </div>
    </div>
    <div v-else class="text-grey-6">{{ emptyPlaceholder }}</div>
  </div>
</template>

<script>
import { computed, defineComponent, ref, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api } from 'boot/axios'
import { useAuthStore } from 'stores/auth'
import { useI18n } from 'vue-i18n'
import { useViewingHistory } from 'src/composables/useViewingHistory'
import { getArtworkImageUrl } from 'src/composables/useMediaFormatters'
import { logger } from 'src/utils/logger'

export default defineComponent({
  name: 'ContinueWatching',
  props: {
    contentType: {
      type: String,
      default: null, // null = all, 'movie' = only movies, 'episode' = only episodes
      validator: (value) => [null, 'movie', 'episode', 'game', 'music', 'book'].includes(value),
    },
    showTitle: {
      type: Boolean,
      default: true,
    },
  },
  setup(props) {
    const { getPosterUrl, getTitle, navigateToPlay, removeItem } = useViewingHistory()
    const authStore = useAuthStore()
    const router = useRouter()
    const continueWatchingItems = ref([])
    const loading = ref(false)

    const { t } = useI18n()

    const sectionTitle = computed(() => {
      if (props.contentType === 'music') return t('viewingHistory.continueListening')
      if (props.contentType === 'game') return t('viewingHistory.continuePlaying')
      if (props.contentType === 'book') return t('viewingHistory.continueReading')
      return t('viewingHistory.continue')
    })

    const emptyPlaceholder = computed(() => {
      if (props.contentType === 'music') return t('viewingHistory.continueListeningPlaceholder')
      if (props.contentType === 'game') return t('viewingHistory.continuePlayingPlaceholder')
      if (props.contentType === 'book') return t('viewingHistory.continueReadingPlaceholder')
      return t('indexPage.continueWatchingPlaceholder')
    })

    const loadContinueWatching = async () => {
      if (!authStore.user) return

      loading.value = true
      try {
        const params = {}
        if (props.contentType) {
          params.content_type = props.contentType
        }
        const response = await api.get('/api/viewing-history/continue-watching', { params })
        // API returns paginated response with items array
        continueWatchingItems.value = response.data.items || response.data
      } catch (error) {
        logger.error('Failed to load continue watching items:', error)
      } finally {
        loading.value = false
      }
    }

    const removeFromContinueWatching = async (item) => {
      await removeItem(item, continueWatchingItems)
    }

    onMounted(() => {
      loadContinueWatching()
    })

    // Reload when contentType changes (e.g. after library is loaded asynchronously)
    watch(
      () => props.contentType,
      (newVal, oldVal) => {
        if (newVal !== oldVal) {
          loadContinueWatching()
        }
      },
    )

    function navigateToDetail(item) {
      // Navigate to the media item detail page (show for episodes, movie for movies)
      const guid = item.media_item?.guid || item.movie_guid || item.episode_guid
      if (guid) {
        // For episodes, navigate to the show (parent of parent)
        if (item.content_type === 'episode' && item.media_item?.parent_guid) {
          router.push(`/media/${item.media_item.parent_guid}`)
        } else {
          router.push(`/media/${guid}`)
        }
      }
    }

    function isMusicItem(item) {
      return item.content_type === 'music'
    }

    function getCardPosterUrl(item) {
      if (isMusicItem(item)) {
        // For music, prefer poster (album cover) over backdrop
        const mi = item.media_item
        if (mi?.poster_path) {
          return getArtworkImageUrl(mi.poster_path, { size: 'w300' })
        }
      }
      return getPosterUrl(item)
    }

    return {
      continueWatchingItems,
      loading,
      navigateToPlay,
      navigateToDetail,
      removeFromContinueWatching,
      getPosterUrl,
      getCardPosterUrl,
      getTitle,
      isMusicItem,
      sectionTitle,
      emptyPlaceholder,
    }
  },
})
</script>

<style scoped>
.continue-watching-section {
}

.continue-watching-scroll {
  display: flex;
  overflow-x: auto;
  gap: 16px;
  padding: 12px 12px 12px 12px;
  margin: -12px -12px -4px -12px;
  scrollbar-width: thin;
}

.continue-watching-scroll::-webkit-scrollbar {
  height: 6px;
}

.continue-watching-scroll::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.2);
  border-radius: 3px;
}

.continue-watching-item {
  flex: 0 0 calc(48% - 8px);
  min-width: 0;
}

@media (min-width: 600px) {
  .continue-watching-item {
    flex: 0 0 calc(32% - 11px);
  }
}

@media (min-width: 1024px) {
  .continue-watching-item {
    flex: 0 0 calc(24% - 12px);
  }
}

@media (min-width: 1440px) {
  .continue-watching-item {
    flex: 0 0 calc(16.5% - 14px);
  }
}

@media (min-width: 1920px) {
  .continue-watching-item {
    flex: 0 0 calc(14.5% - 14px);
  }
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1.5rem;
}

.section-title {
  font-size: 1.5rem;
  font-weight: 600;
  color: white;
  margin: 0;
}

.continue-watching-card {
  transition:
    transform 0.2s ease,
    box-shadow 0.2s ease;
  border-radius: 8px;
  overflow: hidden;
  position: relative;
}

.continue-watching-card:hover {
  transform: scale(1.05);
  box-shadow: 0 8px 25px rgba(0, 0, 0, 0.4);
}

.continue-watching-card:hover .play-icon {
  opacity: 1;
}

.continue-watching-card:hover .remove-btn {
  opacity: 1;
}

.poster-image {
  border-radius: 8px;
}

.overlay-gradient {
  background: linear-gradient(to bottom, transparent 0%, transparent 40%, rgba(0, 0, 0, 0.8) 100%);
}

.play-icon {
  opacity: 0;
  transition:
    opacity 0.2s ease,
    transform 0.2s ease;
  filter: drop-shadow(0 2px 8px rgba(0, 0, 0, 0.7));
}

.centered-icon {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
}

.continue-watching-card:hover .centered-icon {
  transform: translate(-50%, -50%) scale(1.1);
}

.remove-btn {
  opacity: 0;
  transition: opacity 0.2s ease;
  background: rgba(0, 0, 0, 0.5) !important;
}

.content-overlay {
  background: transparent;
}

.ellipsis-2-lines {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  text-overflow: ellipsis;
  line-height: 1.3;
}
</style>
