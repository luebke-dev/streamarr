<template>
  <div>
    <HeroCarousel
      :items="items"
      :loading="loading"
      :item-type="itemType"
      :trending-label="$t('common.trendingNow', 'Trending Now')"
      :primary-button-label="$t('common.watch')"
      :primary-button-label-fn="getPlayButtonLabel"
      :subtitle-fn="getResumeSubtitle"
      :secondary-button-label="$t('common.moreInfo')"
      :empty-icon="emptyIcon"
      :empty-message="$t('common.noTrending', 'No trending items')"
      @primary-action="$emit('play-item', $event)"
      @secondary-action="$emit('navigate-to-item', $event)"
    />
  </div>
</template>

<script setup>
import { ref, onMounted, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from 'boot/axios'
import { cachedApiGet, cachedApiPost } from 'src/composables/useApiResponseCache'
import { useMediaHelpers } from 'src/composables/useMediaHelpers'
import HeroCarousel from 'src/components/HeroCarousel.vue'
import { logger } from 'src/utils/logger'

const props = defineProps({
  section: { type: Object, required: true },
  mediaType: { type: String, default: null },
})

defineEmits(['navigate-to-item', 'play-item'])

const { t } = useI18n()
const { getPosterUrl: getMediaPosterUrl } = useMediaHelpers()

const items = ref([])
const loading = ref(false)
const showResumeInfo = ref({})
const hasRenderedItems = computed(() =>
  Object.prototype.hasOwnProperty.call(props.section, 'rendered_items'),
)

const itemType = computed(() => {
  if (!props.mediaType) return 'mixed'
  const t = props.mediaType.toUpperCase()
  if (t === 'MOVIES') return 'movie'
  if (t === 'SHOWS') return 'show'
  if (t === 'GAMES') return 'game'
  if (t === 'MUSIC') return 'music'
  return 'mixed'
})

const emptyIcon = computed(() => {
  if (itemType.value === 'movie') return 'mdi-movie'
  if (itemType.value === 'show') return 'mdi-television'
  if (itemType.value === 'game') return 'mdi-gamepad-variant'
  if (itemType.value === 'music') return 'mdi-music'
  return 'mdi-movie'
})

function getItemTypeSingular(item) {
  if (!item) return 'movie'
  const type = (item.media_type || item.type || '').toUpperCase()
  if (type === 'MOVIES' || type === 'MOVIE') return 'movie'
  if (type === 'SHOWS' || type === 'SHOW') return 'show'
  if (type === 'GAMES' || type === 'GAME') return 'game'
  return 'movie'
}

function getPlayButtonLabel(item) {
  if (!item) return t('common.play')
  const type = getItemTypeSingular(item)
  if (type === 'game') return t('common.playGame')
  if (type === 'book') return t('common.read')
  if (type === 'music') return t('common.listen')
  if (type === 'show') {
    const info = showResumeInfo.value[item.guid] || { season: 1, episode: 1 }
    return `S${info.season}:E${info.episode} ${t('common.watch')}`
  }
  return t('common.watch')
}

function getResumeSubtitle(item) {
  if (!item) return null
  const type = getItemTypeSingular(item)
  if (type === 'show' && showResumeInfo.value[item.guid]) {
    const info = showResumeInfo.value[item.guid]
    return `S${String(info.season).padStart(2, '0')}E${String(info.episode).padStart(2, '0')}`
  }
  return null
}

function getPosterUrl(item) {
  if (!item) return null
  if (item.cover_url) return item.cover_url
  return getMediaPosterUrl(item)
}

async function fetchShowResumeInfo() {
  const shows = items.value.filter((item) => getItemTypeSingular(item) === 'show')
  for (const show of shows) {
    if (showResumeInfo.value[show.guid]) continue
    try {
      const res = await api.get(`/api/media/shows/${show.guid}/resume`)
      showResumeInfo.value[show.guid] = {
        season: res.data?.season_number || 1,
        episode: res.data?.episode_number || 1,
      }
    } catch (e) {
      // Resume position unavailable; fall back to S01E01
      logger.debug('Failed to load resume info, defaulting to S01E01', e)
      showResumeInfo.value[show.guid] = { season: 1, episode: 1 }
    }
  }
}

async function loadFromList(listGuid) {
  const response = await cachedApiGet(
    `/api/lists/${listGuid}/items`,
    {
      params: { per_page: 20 },
    },
    { ttlMs: 2 * 60_000, staleTtlMs: 30 * 60_000 },
  )
  return (response.data.items || [])
    .filter((item) => item.item_data)
    .map((item) => ({
      ...item.item_data,
      guid: item.item_data.guid || item.guid,
    }))
    .filter((item) => getPosterUrl(item))
}

async function resolveListByUpdateSource(updateSource) {
  try {
    const resp = await cachedApiGet(
      '/api/lists',
      {
        params: { owner: 'me', update_source: updateSource, per_page: 1 },
      },
      { ttlMs: 5 * 60_000, staleTtlMs: 30 * 60_000 },
    )
    const list = (resp.data.items || [])[0]
    return list ? list.guid : null
  } catch (error) {
    logger.error('Error resolving list by update_source:', error)
    return null
  }
}

async function loadFromDynamicSearch(filters) {
  const searchPayload = {
    per_page: 20,
    page: 1,
    search_type: filters.media_type ? filters.media_type.toLowerCase() : 'all',
  }

  if (filters.query) searchPayload.query = filters.query
  if (filters.media_type) searchPayload.media_type = filters.media_type
  if (filters.genre_id) searchPayload.genre_id = filters.genre_id
  if (filters.genres && filters.genres.length) searchPayload.genres = filters.genres
  if (filters.year_from) searchPayload.year_from = filters.year_from
  if (filters.year_to) searchPayload.year_to = filters.year_to
  if (filters.sort_by) searchPayload.sort_by = filters.sort_by
  if (filters.sort_order) searchPayload.sort_order = filters.sort_order
  if (filters.availability) searchPayload.availability = filters.availability
  if (filters.has_poster !== undefined && filters.has_poster !== null)
    searchPayload.has_poster = filters.has_poster
  if (filters.has_description !== undefined && filters.has_description !== null)
    searchPayload.has_description = filters.has_description

  if (!searchPayload.media_type && props.mediaType) {
    searchPayload.media_type = props.mediaType
    searchPayload.search_type = props.mediaType.toLowerCase()
  }

  const response = await cachedApiPost(
    '/api/search/',
    searchPayload,
    {},
    { ttlMs: 2 * 60_000, staleTtlMs: 30 * 60_000 },
  )
  return (response.data.hits || []).filter((item) => getPosterUrl(item))
}

async function loadFromTrending() {
  const listsResponse = await cachedApiGet(
    '/api/lists',
    { params: { per_page: 100 } },
    { ttlMs: 5 * 60_000, staleTtlMs: 30 * 60_000 },
  )
  const lists = listsResponse.data.items || []

  let sources = ['trending_movies', 'trending_shows', 'trending_games', 'trending_music']
  if (props.mediaType) {
    const typeUpper = props.mediaType.toUpperCase()
    if (typeUpper === 'MOVIES') sources = ['trending_movies']
    else if (typeUpper === 'SHOWS') sources = ['trending_shows']
    else if (typeUpper === 'GAMES') sources = ['trending_games']
    else if (typeUpper === 'MUSIC') sources = ['trending_music']
    else sources = []
  }

  const mixedContent = []
  for (const source of sources) {
    const list = lists.find((l) => l.update_source === source)
    if (!list) continue
    try {
      const resp = await cachedApiGet(
        `/api/lists/${list.guid}/items`,
        { params: { per_page: 10 } },
        { ttlMs: 2 * 60_000, staleTtlMs: 30 * 60_000 },
      )
      const typeMap = {
        trending_movies: 'movie',
        trending_shows: 'show',
        trending_games: 'game',
        trending_music: 'music',
      }
      const mapped = (resp.data.items || [])
        .filter((item) => item.item_data)
        .map((item) => ({
          ...item.item_data,
          type: typeMap[source],
          guid: item.item_data.guid || item.guid,
        }))
      mixedContent.push(...mapped)
    } catch (e) {
      logger.error(`Error loading trending ${source}:`, e)
    }
  }

  return mixedContent
    .filter((item) => getPosterUrl(item))
    .sort(() => Math.random() - 0.5)
    .slice(0, 20)
}

async function loadItems() {
  if (hasRenderedItems.value) {
    items.value = (props.section.rendered_items || []).filter((item) => getPosterUrl(item))
    loading.value = false
    fetchShowResumeInfo()
    return
  }

  loading.value = true
  try {
    const config = props.section.config || {}
    const hasListSource = config.list_guid || config.list_update_source
    const sourceType = config.source_type || (hasListSource ? 'list' : 'trending')

    if (sourceType === 'list') {
      let guid = config.list_guid
      if (!guid && config.list_update_source) {
        guid = await resolveListByUpdateSource(config.list_update_source)
      }
      if (guid) {
        items.value = await loadFromList(guid)
      } else {
        // Graceful fallback to trending when the per-user list isn't ready yet
        items.value = await loadFromTrending()
      }
    } else if (sourceType === 'dynamic_search') {
      items.value = await loadFromDynamicSearch(config.filters || {})
    } else {
      items.value = await loadFromTrending()
    }
  } catch (error) {
    logger.error('Error loading hero carousel items:', error)
  } finally {
    loading.value = false
    fetchShowResumeInfo()
  }
}

onMounted(loadItems)
watch(() => [props.mediaType, props.section.config, props.section.rendered_items], loadItems, {
  deep: true,
})
</script>
