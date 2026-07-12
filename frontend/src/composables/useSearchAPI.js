import { ref, onMounted, onUnmounted } from 'vue'
import { api } from 'boot/axios'
import { useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import { logger } from 'src/utils/logger'
import { useWebSocket } from 'src/composables/useWebSocket'
import { useMediaTypeMapping } from 'src/composables/useMediaTypeMapping'
import { buildSearchPayload } from 'src/utils/searchPayload'

// Re-exported for backward compatibility with existing importers.
export { buildSearchPayload }

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
      // The search page keeps the URL-derived contract: string/array filters,
      // per_page 50, search_type always 'all', and the trimmed text query.
      const payload = buildSearchPayload({ ...filters, query: query?.trim() })

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
