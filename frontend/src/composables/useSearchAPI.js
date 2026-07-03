import { ref, onMounted, onUnmounted } from 'vue'
import { api } from 'boot/axios'
import { useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import { logger } from 'src/utils/logger'
import { useWebSocket } from 'src/composables/useWebSocket'
import { useMediaTypeMapping } from 'src/composables/useMediaTypeMapping'

function numericList(value) {
  return (Array.isArray(value) ? value : value == null ? [] : [value])
    .map((item) => Number(item))
    .filter((item) => Number.isFinite(item))
}

function stringList(value) {
  return (Array.isArray(value) ? value : value == null ? [] : [value])
    .map((item) => String(item).trim())
    .filter(Boolean)
}

export function buildSearchPayload(query, filters = {}) {
  const payload = { search_type: 'all', per_page: 50, page: 1 }

  if (query?.trim()) payload.query = query.trim()
  if (filters.genre_id) payload.genre_id = Number(filters.genre_id)
  const genreIds = numericList(filters.genre_ids)
  if (genreIds.length) payload.genre_ids = genreIds
  const excludeGenreIds = numericList(filters.exclude_genre_ids)
  if (excludeGenreIds.length) payload.exclude_genre_ids = excludeGenreIds
  if (filters.platform_id) payload.platform_id = Number(filters.platform_id)
  const platformIds = numericList(filters.platform_ids)
  if (platformIds.length) payload.platform_ids = platformIds
  const excludePlatformIds = numericList(filters.exclude_platform_ids)
  if (excludePlatformIds.length) payload.exclude_platform_ids = excludePlatformIds
  if (filters.media_type) payload.media_type = filters.media_type
  if (filters.availability) payload.availability = filters.availability
  if (filters.has_poster != null) payload.has_poster = filters.has_poster === 'true'
  if (filters.has_backdrop != null) payload.has_backdrop = filters.has_backdrop === 'true'
  if (filters.has_description != null) {
    payload.has_description = filters.has_description === 'true'
  }
  if (filters.is_favorite != null) payload.is_favorite = filters.is_favorite === 'true'
  if (filters.is_played != null) payload.is_played = filters.is_played === 'true'
  if (filters.person_guid) payload.person_guid = filters.person_guid
  if (filters.exclude_person_guid) payload.exclude_person_guid = filters.exclude_person_guid
  if (filters.studio_name) payload.studio_name = filters.studio_name
  if (filters.container) payload.container = filters.container
  const excludeContainers = stringList(filters.exclude_containers)
  if (excludeContainers.length) payload.exclude_containers = excludeContainers
  if (filters.content_rating) payload.content_rating = filters.content_rating
  const excludeContentRatings = stringList(filters.exclude_content_ratings)
  if (excludeContentRatings.length) {
    payload.exclude_content_ratings = excludeContentRatings
  }
  const years = numericList(filters.years)
  if (years.length) payload.years = years
  const excludeYears = numericList(filters.exclude_years)
  if (excludeYears.length) payload.exclude_years = excludeYears
  if (filters.year_from) payload.year_from = Number(filters.year_from)
  if (filters.year_to) payload.year_to = Number(filters.year_to)
  if (filters.sort_by) payload.sort_by = filters.sort_by
  if (filters.sort_order) payload.sort_order = filters.sort_order

  return payload
}

/**
 * Composable that owns the search-results data layer:
 *
 * - reactive results / list-results / loading / source state
 * - performSearch(query, filters) with AbortController-based cancellation
 * - navigateToResult(result) (handles in-library, get-or-import, push)
 * - loadFilterOptions() with option lists + name lookup state
 * - WebSocket subscription for live `media_imported` events
 *
 * Lifecycle (subscription, abort) is wired up automatically via
 * onMounted / onUnmounted.
 */
export function useSearchAPI(router) {
  const $q = useQuasar()
  const { t } = useI18n()
  const { getImportMediaType } = useMediaTypeMapping()
  const { subscribe, unsubscribe } = useWebSocket()

  // Search results state
  const searchResults = ref([])
  const listResults = ref([])
  const totalResults = ref(0)
  const searchSource = ref(null)
  const loading = ref(false)

  // Lookup tables / option lists
  const genreNames = ref({})
  const allGenreOptions = ref([])
  const genreOptions = ref([])
  const platformOptions = ref([])
  const personOptions = ref([])
  const allPersonOptions = ref([])
  const yearOptions = ref([])
  const allStudioOptions = ref([])
  const studioOptions = ref([])
  const containerOptions = ref([])
  const contentRatingOptions = ref([])

  let searchAbortController = null
  let wsHandler = null

  function notifyError(messageKey, error) {
    logger.error(`[Search] ${messageKey}:`, error)
    $q.notify({
      type: 'negative',
      message: t(messageKey),
      timeout: 4000,
    })
  }

  async function performSearch(query, filters = {}) {
    if (searchAbortController) searchAbortController.abort()
    searchAbortController = new AbortController()
    const signal = searchAbortController.signal

    loading.value = true
    try {
      const payload = buildSearchPayload(query, filters)

      const response = await api.post('/api/search/', payload, { signal })
      if (response.data?.hits) {
        searchResults.value = response.data.hits
        totalResults.value = response.data.total || response.data.hits.length
        searchSource.value = response.data.source || null
      } else {
        searchResults.value = []
        totalResults.value = 0
      }
      listResults.value = response.data?.list_hits || []

      // Lazy-load genre names if we filter by an unknown genre id.
      if (filters.genre_id && !genreNames.value[filters.genre_id]) {
        try {
          const filtersRes = await api.get('/api/filters', { signal })
          for (const g of filtersRes.data?.genres || []) genreNames.value[g.id] = g.name
        } catch (err) {
          if (err.code !== 'ERR_CANCELED' && err.name !== 'CanceledError') {
            logger.warn('[Search] Genre lookup failed:', err)
          }
        }
      }
    } catch (error) {
      if (error.code === 'ERR_CANCELED' || error.name === 'CanceledError') {
        return
      }
      notifyError('searchResultsPage.searchFailed', error)
      searchResults.value = []
      totalResults.value = 0
    } finally {
      if (searchAbortController?.signal === signal) {
        loading.value = false
      }
    }
  }

  async function navigateToResult(result) {
    if (result.in_library && result.id) {
      router.push(`/media/${result.id}`)
      return
    }

    if (!result.tmdb_id && !result.igdb_id && !result.spotify_id) {
      return
    }

    const mediaTypeStr = getImportMediaType(result)

    try {
      const importPayload = { media_type: mediaTypeStr }
      if (result.igdb_id) importPayload.igdb_id = result.igdb_id
      else if (result.spotify_id) importPayload.spotify_id = result.spotify_id
      else importPayload.tmdb_id = result.tmdb_id

      const response = await api.post('/api/search/get-or-import', importPayload)
      const { guid } = response.data
      router.push(`/media/${guid}`)
    } catch (error) {
      notifyError('searchResultsPage.importFailed', error)
    }
  }

  async function loadFilterOptions() {
    try {
      const res = await api.get('/api/filters')
      const filters = res.data || {}
      const opts = (filters.genres || []).map((g) => ({ label: g.name, value: g.id }))
      allGenreOptions.value = opts
      genreOptions.value = opts
      for (const g of filters.genres || []) genreNames.value[g.id] = g.name
      platformOptions.value = (filters.platforms || []).map((p) => ({
        label: p.name,
        value: p.id,
      }))
      const persons = (filters.persons || []).map((person) => ({
        label: person.name,
        value: person.id,
      }))
      allPersonOptions.value = persons
      personOptions.value = persons
      yearOptions.value = (filters.years || []).map((year) => ({
        label: String(year),
        value: Number(year),
      }))
      const studios = (filters.studios || []).map((name) => ({ label: name, value: name }))
      allStudioOptions.value = studios
      studioOptions.value = studios
      containerOptions.value = (filters.containers || []).map((name) => ({
        label: name,
        value: name,
      }))
      contentRatingOptions.value = (filters.content_ratings || []).map((name) => ({
        label: name,
        value: name,
      }))
    } catch (err) {
      logger.warn('[Search] Filter option load failed:', err)
    }
  }

  /**
   * Local typeahead filter for the genre <q-select use-input>.
   */
  function filterGenreOptions(val, update) {
    update(() => {
      if (!val) {
        genreOptions.value = allGenreOptions.value
      } else {
        const needle = val.toLowerCase()
        genreOptions.value = allGenreOptions.value.filter((g) =>
          g.label.toLowerCase().includes(needle),
        )
      }
    })
  }

  function filterStudioOptions(val, update) {
    update(() => {
      if (!val) {
        studioOptions.value = allStudioOptions.value
      } else {
        const needle = val.toLowerCase()
        studioOptions.value = allStudioOptions.value.filter((studio) =>
          studio.label.toLowerCase().includes(needle),
        )
      }
    })
  }

  function filterPersonOptions(val, update) {
    update(() => {
      if (!val) {
        personOptions.value = allPersonOptions.value
      } else {
        const needle = val.toLowerCase()
        personOptions.value = allPersonOptions.value.filter((person) =>
          person.label.toLowerCase().includes(needle),
        )
      }
    })
  }

  function setupImportListener() {
    wsHandler = (event, data) => {
      if (event === 'media_imported' && data) {
        for (const result of searchResults.value) {
          const matches =
            (data.tmdb_id && result.tmdb_id === data.tmdb_id) ||
            (data.igdb_id && result.igdb_id === data.igdb_id)
          if (matches) {
            result.in_library = true
            result.id = data.guid
            logger.debug('[Search] Media imported via WebSocket:', data.title)
            break
          }
        }
      }
    }
    subscribe('search', 'imports', wsHandler)
  }

  onMounted(() => {
    loadFilterOptions()
    setupImportListener()
  })

  onUnmounted(() => {
    if (wsHandler) {
      unsubscribe('search', 'imports', wsHandler)
      wsHandler = null
    }
    if (searchAbortController) {
      searchAbortController.abort()
      searchAbortController = null
    }
  })

  return {
    // state
    searchResults,
    listResults,
    totalResults,
    searchSource,
    loading,
    genreOptions,
    platformOptions,
    personOptions,
    yearOptions,
    studioOptions,
    containerOptions,
    contentRatingOptions,
    genreNames,
    // actions
    performSearch,
    navigateToResult,
    filterGenreOptions,
    filterPersonOptions,
    filterStudioOptions,
  }
}
