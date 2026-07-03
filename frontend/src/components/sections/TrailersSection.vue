<template>
  <MediaRowSection
    :title="sectionTitle"
    :items="items"
    :loading="loading"
    :empty-text="t('trailersPage.empty')"
    empty-icon="mdi-movie-open-outline"
  >
    <template #item="{ item: entry }">
      <PosterCard
        :type="getItemType(entry.media_item)"
        :title="entry.media_item.title"
        :image-url="getPosterUrl(entry.media_item)"
        :subtitle="trailerSubtitle(entry)"
        :content-rating="entry.media_item.content_rating"
        :min-age="entry.media_item.min_age"
        class="genre-media-card"
        @click="$emit('navigate-to-item', entry.media_item)"
      />
    </template>
  </MediaRowSection>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { cachedApiGet } from 'src/composables/useApiResponseCache'
import { useSectionData } from 'src/composables/useSectionData'
import PosterCard from 'src/components/PosterCard.vue'
import MediaRowSection from 'src/components/sections/MediaRowSection.vue'
import { useMediaHelpers } from 'src/composables/useMediaHelpers'
import { getItemType } from 'src/composables/useMediaFormatters'

const props = defineProps({
  section: { type: Object, required: true },
  mediaType: { type: String, default: null },
})

defineEmits(['navigate-to-item'])

const { t } = useI18n()
const { getPosterUrl, formatYear } = useMediaHelpers()

const sectionTitle = computed(() => props.section.title || t('trailersPage.title'))
const effectiveMediaType = computed(
  () => props.section.config?.media_type || props.mediaType || null,
)
const maxItems = computed(() => props.section.config?.max_items || 20)
const searchTerm = computed(() => props.section.config?.search_term?.trim() || '')

function trailerSubtitle(entry) {
  const year = formatYear(entry.media_item.release_date)
  const count = t('trailersPage.trailerCount', entry.trailer_count)
  return year ? `${year} · ${count}` : count
}

function normalizeTrailerEntry(entry) {
  return {
    ...entry,
    guid: entry.media_item?.guid || entry.guid,
  }
}

const { items, loading } = useSectionData({
  section: () => props.section,
  mediaType: () => props.mediaType,
  mapRendered: (rendered) => rendered.map(normalizeTrailerEntry),
  loader: async () => {
    const params = { limit: maxItems.value }
    if (effectiveMediaType.value) params.media_type = effectiveMediaType.value
    if (searchTerm.value) params.search_term = searchTerm.value

    const response = await cachedApiGet(
      '/api/trailers',
      { params },
      { ttlMs: 2 * 60_000, staleTtlMs: 20 * 60_000 },
    )
    return (response.data.items || []).map(normalizeTrailerEntry)
  },
})
</script>
