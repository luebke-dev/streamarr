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
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { cachedApiGet } from 'src/composables/useApiResponseCache'
import { useSectionData } from 'src/composables/useSectionData'
import { useMediaHelpers } from 'src/composables/useMediaHelpers'
import { getItemType } from 'src/composables/useMediaFormatters'
import PosterCard from 'src/components/PosterCard.vue'
import MediaRowSection from 'src/components/sections/MediaRowSection.vue'

const props = defineProps({
  section: { type: Object, required: true },
  mediaType: { type: String, default: null },
})

defineEmits(['navigate-to-item'])

const { t } = useI18n()
const { getPosterUrl: getMediaPosterUrl, formatYear } = useMediaHelpers()

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


const { items, loading } = useSectionData({
  section: () => props.section,
  mediaType: () => props.mediaType,
  // Preserve legacy behaviour: keep the previously loaded favorites on error.
  clearOnError: false,
  mapRendered: (rendered) =>
    rendered.map(normalizeFavoriteItem).filter((item) => getPosterUrl(item)),
  loader: async () => {
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
      return allFavorites
        .map(normalizeFavoriteItem)
        .filter((item) => matchesFavoriteType(item, targetType) && getPosterUrl(item))
    }
    return allFavorites.map(normalizeFavoriteItem).filter((item) => getPosterUrl(item))
  },
})
</script>
