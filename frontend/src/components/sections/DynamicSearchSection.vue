<template>
  <MediaRowSection
    :title="sectionTitle"
    :items="items"
    :loading="loading"
    :show-see-all="true"
    @see-all="viewAll"
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
import { useRouter } from 'vue-router'
import { cachedApiPost } from 'src/composables/useApiResponseCache'
import {
  useSectionData,
  buildSearchPayload,
  buildSearchQueryParams,
} from 'src/composables/useSectionData'
import { useMediaHelpers } from 'src/composables/useMediaHelpers'
import { getItemType } from 'src/composables/useMediaFormatters'
import PosterCard from 'src/components/PosterCard.vue'
import MediaRowSection from 'src/components/sections/MediaRowSection.vue'

const props = defineProps({
  section: { type: Object, required: true },
  mediaType: { type: String, default: null },
})

defineEmits(['navigate-to-item'])

const router = useRouter()
const { getPosterUrl: getMediaPosterUrl, formatYear } = useMediaHelpers()

const filters = computed(() => props.section.config?.filters || {})
const sectionTitle = computed(() => props.section.title || 'Collection')

function getPosterUrl(item) {
  if (item.cover_url) return item.cover_url
  return getMediaPosterUrl(item)
}

function getItemSubtitle(item) {
  return formatYear(item.release_date || item.first_air_date)
}

function viewAll() {
  const params = buildSearchQueryParams(filters.value, { mediaType: props.mediaType })
  router.push(`/search?${params.toString()}`)
}

const { items, loading } = useSectionData({
  section: () => props.section,
  mediaType: () => props.mediaType,
  mapRendered: (rendered) => rendered.filter((item) => getPosterUrl(item)),
  loader: async () => {
    // Always use search API — it supports all filters including availability and has_poster
    const searchPayload = buildSearchPayload(filters.value, {
      mediaType: props.mediaType,
      perPage: props.section.config?.max_items || 10,
    })
    const response = await cachedApiPost(
      '/api/search/',
      searchPayload,
      {},
      { ttlMs: 2 * 60_000, staleTtlMs: 20 * 60_000 },
    )
    return (response.data.hits || []).filter((item) => getPosterUrl(item))
  },
})
</script>
