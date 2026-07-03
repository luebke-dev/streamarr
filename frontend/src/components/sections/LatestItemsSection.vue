<template>
  <MediaRowSection
    :title="sectionTitle"
    :items="items"
    :loading="loading"
    :show-see-all="true"
    :empty-text="t('pageLayouts.noLatestItems')"
    empty-icon="mdi-clock-outline"
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
        class="genre-media-card"
        @click="$emit('navigate-to-item', item)"
      />
    </template>
  </MediaRowSection>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
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
const router = useRouter()
const { getPosterUrl: getMediaPosterUrl, formatYear } = useMediaHelpers()

const sectionTitle = computed(() => props.section.title || t('pageLayouts.latestItems'))
const effectiveMediaType = computed(
  () => props.section.config?.media_type || props.mediaType || null,
)
const maxItems = computed(() => props.section.config?.max_items || 20)

function getPosterUrl(item) {
  if (item.cover_url) return item.cover_url
  return getMediaPosterUrl(item)
}

function getItemSubtitle(item) {
  return formatYear(item.release_date || item.first_air_date)
}

function viewAll() {
  const params = new URLSearchParams()
  const mediaType = effectiveMediaType.value
  if (mediaType) params.set('media_type', mediaType)
  params.set('sort_by', 'created_at')
  params.set('sort_order', 'desc')
  router.push(`/search?${params.toString()}`)
}

const { items, loading } = useSectionData({
  section: () => props.section,
  mediaType: () => props.mediaType,
  mapRendered: (rendered) => rendered.filter((item) => getPosterUrl(item)),
  loader: async () => {
    const params = { limit: maxItems.value }
    if (effectiveMediaType.value) params.media_type = effectiveMediaType.value
    const response = await cachedApiGet(
      '/api/suggestions/latest',
      { params },
      { ttlMs: 2 * 60_000, staleTtlMs: 20 * 60_000 },
    )
    return (response.data.items || []).filter((item) => getPosterUrl(item))
  },
})
</script>
