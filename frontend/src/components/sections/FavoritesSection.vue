<template>
  <MediaRowSection
    :title="sectionTitle"
    :items="items"
    :loading="loading"
    :empty-text="t('common.noFavorites', 'No favorites yet')"
    empty-icon="mdi-heart-outline"
  >
    <template #item="{ item }">
      <PosterCard
        :type="getItemType(item)"
        :title="item.title"
        :image-url="getPosterUrl(item)"
        :subtitle="getItemSubtitle(item)"
        :rating="item.rating"
        :platforms="item.platforms"
        :content-rating="item.content_rating"
        :min-age="item.min_age"
        @click="$emit('navigate-to-item', item)"
        class="genre-media-card"
      />
    </template>
  </MediaRowSection>
</template>

<script setup>
import { ref, onMounted, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { cachedApiGet } from 'src/composables/useApiResponseCache'
import { useMediaHelpers } from 'src/composables/useMediaHelpers'
import { getItemType } from 'src/composables/useMediaFormatters'
import PosterCard from 'src/components/PosterCard.vue'
import MediaRowSection from 'src/components/sections/MediaRowSection.vue'
import { logger } from 'src/utils/logger'

const props = defineProps({
  section: { type: Object, required: true },
  mediaType: { type: String, default: null },
})

defineEmits(['navigate-to-item'])

const { t } = useI18n()
const { getPosterUrl: getMediaPosterUrl, formatYear } = useMediaHelpers()

const items = ref([])
const loading = ref(false)
const hasRenderedItems = computed(() =>
  Object.prototype.hasOwnProperty.call(props.section, 'rendered_items'),
)

const sectionTitle = computed(() => props.section.title || t('common.myFavorites'))

function getPosterUrl(item) {
  if (item.cover_url) return item.cover_url
  return getMediaPosterUrl(item)
}

function getItemSubtitle(item) {
  return formatYear(item.release_date || item.first_air_date)
}

function normalizeFavoriteItem(item) {
  return {
    ...item,
    guid: item.media_item_guid || item.guid,
    poster_path: item.poster_path || item.poster_url,
  }
}

function matchesFavoriteType(item, targetType) {
  return item.item_type === targetType || getItemType(item) === targetType
}


async function loadFavorites() {
  if (hasRenderedItems.value) {
    items.value = (props.section.rendered_items || [])
      .map(normalizeFavoriteItem)
      .filter((item) => getPosterUrl(item))
    loading.value = false
    return
  }

  loading.value = true
  try {
    // No trailing slash — FastAPI's redirect_slashes turns "/favorites/" into a
    // 307 that some browser/axios combos handle poorly (auth header or query
    // params drop in transit), and the section silently shows "no favorites".
    const response = await cachedApiGet(
      '/api/favorites',
      { params: { per_page: 20 } },
      { ttlMs: 60_000, staleTtlMs: 10 * 60_000 },
    )
    const allFavorites = response.data.items || []

    if (props.mediaType) {
      const mt = props.mediaType.toUpperCase()
      const typeMap = {
        MOVIES: 'movie',
        SHOWS: 'show',
        GAMES: 'game',
        MUSIC: 'music',
        BOOKS: 'book',
      }
      const targetType = typeMap[mt]
      items.value = allFavorites
        .map(normalizeFavoriteItem)
        .filter((item) => matchesFavoriteType(item, targetType) && getPosterUrl(item))
    } else {
      items.value = allFavorites.map(normalizeFavoriteItem).filter((item) => getPosterUrl(item))
    }
  } catch (error) {
    logger.error('Error loading favorites:', error)
  } finally {
    loading.value = false
  }
}

onMounted(loadFavorites)
watch(() => [props.mediaType, props.section.config, props.section.rendered_items], loadFavorites, {
  deep: true,
})
</script>
