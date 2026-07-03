<template>
  <MediaRowSection
    :title="sectionTitle"
    :items="items"
    :loading="loading"
    :show-see-all="true"
    @see-all="viewAll"
    @item-click="$emit('navigate-to-item', $event)"
  />
</template>

<script setup>
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { cachedApiGet, cachedApiPost } from 'src/composables/useApiResponseCache'
import { useSectionData } from 'src/composables/useSectionData'
import { useMediaSection } from 'src/composables/useMediaSection'
import MediaRowSection from 'src/components/sections/MediaRowSection.vue'
import { logger } from 'src/utils/logger'

const props = defineProps({
  section: { type: Object, required: true },
  mediaType: { type: String, default: null },
})

defineEmits(['navigate-to-item'])

const router = useRouter()
const { getPosterUrl } = useMediaSection()

const genreName = ref('')

const genreId = computed(() => props.section.config?.genre_id)
const filters = computed(() => props.section.config?.filters || {})

const sectionTitle = computed(() => props.section.title || genreName.value || 'Genre')

function viewAll() {
  const params = new URLSearchParams()
  if (genreId.value) params.set('genre_id', genreId.value)
  if (props.mediaType) params.set('media_type', props.mediaType)
  const f = filters.value
  if (f.availability) params.set('availability', f.availability)
  if (f.has_poster !== undefined && f.has_poster !== null) params.set('has_poster', f.has_poster)
  if (f.has_description !== undefined && f.has_description !== null)
    params.set('has_description', f.has_description)
  if (f.platform_id) params.set('platform_id', f.platform_id)
  router.push(`/search?${params.toString()}`)
}

const { items, loading } = useSectionData({
  section: () => props.section,
  mediaType: () => props.mediaType,
  loader: async () => {
    if (!genreId.value) return []

    // Load genre name (cosmetic — keep the id-based fallback on failure)
    try {
      const genreResp = await cachedApiGet(
        `/api/genres/${genreId.value}`,
        {},
        { ttlMs: 10 * 60_000, staleTtlMs: 60 * 60_000 },
      )
      genreName.value = genreResp.data.name
    } catch (e) {
      logger.warn('Failed to load genre name', e)
    }

    // Use search API to support all filters
    const payload = {
      per_page: props.section.config?.max_items || 10,
      page: 1,
      genre_id: genreId.value,
      search_type: 'all',
    }
    if (props.mediaType) {
      payload.media_type = props.mediaType
      payload.search_type = props.mediaType.toLowerCase()
    }

    // Apply optional filters from config
    const f = filters.value
    if (f.availability) payload.availability = f.availability
    if (f.has_poster !== undefined && f.has_poster !== null) payload.has_poster = f.has_poster
    if (f.has_description !== undefined && f.has_description !== null)
      payload.has_description = f.has_description
    if (f.platform_id) payload.platform_id = f.platform_id

    const response = await cachedApiPost(
      '/api/search/',
      payload,
      {},
      { ttlMs: 2 * 60_000, staleTtlMs: 20 * 60_000 },
    )
    return (response.data.hits || []).filter((item) => getPosterUrl(item))
  },
})
</script>
