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
import { ref, onMounted, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import { cachedApiPost } from 'src/composables/useApiResponseCache'
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

const router = useRouter()
const { getPosterUrl: getMediaPosterUrl, formatYear } = useMediaHelpers()

const items = ref([])
const loading = ref(false)
const hasRenderedItems = computed(() =>
  Object.prototype.hasOwnProperty.call(props.section, 'rendered_items'),
)

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
  const params = new URLSearchParams()
  const f = filters.value
  if (f.media_type) params.set('media_type', f.media_type)
  if (f.genre_id) params.set('genre_id', f.genre_id)
  if (f.platform_id) params.set('platform_id', f.platform_id)
  if (f.genres && f.genres.length) params.set('genres', f.genres.join(','))
  if (f.year_from) params.set('year_from', f.year_from)
  if (f.year_to) params.set('year_to', f.year_to)
  if (f.sort_by) params.set('sort_by', f.sort_by)
  if (f.sort_order) params.set('sort_order', f.sort_order)
  if (f.query) params.set('q', f.query)
  if (f.availability) params.set('availability', f.availability)
  if (f.studio_name) params.set('studio_name', f.studio_name)
  if (f.container) params.set('container', f.container)
  if (f.content_rating) params.set('content_rating', f.content_rating)
  if (f.has_poster !== undefined && f.has_poster !== null) params.set('has_poster', f.has_poster)
  if (f.has_backdrop !== undefined && f.has_backdrop !== null)
    params.set('has_backdrop', f.has_backdrop)
  if (f.has_description !== undefined && f.has_description !== null)
    params.set('has_description', f.has_description)
  if (f.is_favorite !== undefined && f.is_favorite !== null)
    params.set('is_favorite', f.is_favorite)
  if (f.is_played !== undefined && f.is_played !== null) params.set('is_played', f.is_played)
  if (props.mediaType) params.set('media_type', props.mediaType)
  router.push(`/search?${params.toString()}`)
}

async function loadItems() {
  if (hasRenderedItems.value) {
    items.value = (props.section.rendered_items || []).filter((item) => getPosterUrl(item))
    loading.value = false
    return
  }

  loading.value = true
  try {
    const f = filters.value
    const perPage = props.section.config?.max_items || 10

    // Always use search API — it supports all filters including availability and has_poster
    const searchPayload = {
      per_page: perPage,
      page: 1,
      search_type: f.media_type ? f.media_type.toLowerCase() : 'all',
    }

    if (f.query) searchPayload.query = f.query
    if (f.media_type) searchPayload.media_type = f.media_type
    if (f.genre_id) searchPayload.genre_id = f.genre_id
    if (f.platform_id) searchPayload.platform_id = f.platform_id
    if (f.genres && f.genres.length) searchPayload.genres = f.genres
    if (f.year_from) searchPayload.year_from = f.year_from
    if (f.year_to) searchPayload.year_to = f.year_to
    if (f.sort_by) searchPayload.sort_by = f.sort_by
    if (f.sort_order) searchPayload.sort_order = f.sort_order
    if (f.availability) searchPayload.availability = f.availability
    if (f.studio_name) searchPayload.studio_name = f.studio_name
    if (f.container) searchPayload.container = f.container
    if (f.content_rating) searchPayload.content_rating = f.content_rating
    if (f.has_poster !== undefined && f.has_poster !== null) searchPayload.has_poster = f.has_poster
    if (f.has_backdrop !== undefined && f.has_backdrop !== null)
      searchPayload.has_backdrop = f.has_backdrop
    if (f.has_description !== undefined && f.has_description !== null)
      searchPayload.has_description = f.has_description
    if (f.is_favorite !== undefined && f.is_favorite !== null)
      searchPayload.is_favorite = f.is_favorite
    if (f.is_played !== undefined && f.is_played !== null) searchPayload.is_played = f.is_played

    // Apply page-level media type as fallback
    if (!searchPayload.media_type && props.mediaType) {
      searchPayload.media_type = props.mediaType
      searchPayload.search_type = props.mediaType.toLowerCase()
    }

    const response = await cachedApiPost(
      '/api/search/',
      searchPayload,
      {},
      { ttlMs: 2 * 60_000, staleTtlMs: 20 * 60_000 },
    )
    items.value = (response.data.hits || []).filter((item) => getPosterUrl(item))
  } catch (error) {
    logger.error('Error loading dynamic search items:', error)
    items.value = []
  } finally {
    loading.value = false
  }
}

onMounted(loadItems)
watch(() => [props.mediaType, props.section.config, props.section.rendered_items], loadItems, {
  deep: true,
})
</script>
