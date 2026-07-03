import { ref, computed, watch } from 'vue'
import { FILTER_KEYS } from 'src/utils/searchOptions'

/**
 * Filter keys whose URL value should be parsed as Number when set.
 */
const NUMERIC_KEYS = new Set(['genre_id', 'platform_id'])
const NUMERIC_ARRAY_KEYS = new Set([
  'genre_ids',
  'exclude_genre_ids',
  'platform_ids',
  'exclude_platform_ids',
  'years',
  'exclude_years',
])
const STRING_ARRAY_KEYS = new Set([
  'genres',
  'exclude_genres',
  'exclude_containers',
  'exclude_content_ratings',
])

function queryArray(raw) {
  if (raw == null || raw === '') return []
  const values = Array.isArray(raw) ? raw : String(raw).split(',')
  return values.map((value) => String(value).trim()).filter(Boolean)
}

function parseNumericArray(raw) {
  return queryArray(raw)
    .map((value) => Number(value))
    .filter((value) => Number.isFinite(value))
}

function isEmptyFilterValue(value) {
  return value == null || value === '' || (Array.isArray(value) && value.length === 0)
}

/**
 * Read filter values from a route.query object, normalising numeric keys.
 */
function readFiltersFromQuery(query) {
  const out = {}
  for (const key of FILTER_KEYS) {
    const raw = query[key]
    if (raw == null || raw === '') {
      out[key] = NUMERIC_ARRAY_KEYS.has(key) || STRING_ARRAY_KEYS.has(key) ? [] : null
    } else if (NUMERIC_ARRAY_KEYS.has(key)) {
      out[key] = parseNumericArray(raw)
    } else if (STRING_ARRAY_KEYS.has(key)) {
      out[key] = queryArray(raw)
    } else if (NUMERIC_KEYS.has(key)) {
      out[key] = Number(raw)
    } else {
      out[key] = raw
    }
  }
  return out
}

/**
 * Composable that owns search filter state (incl. text query) and keeps it
 * synchronised with the URL query string.
 *
 * - `filters` is a computed object suitable as `v-model` for SearchFilterBar.
 * - `searchQuery` mirrors the `q` URL param (text input).
 * - `isBrowseMode` is true when no text query but at least one filter is set.
 * - `applyFilters()` writes the current filters back to the URL.
 * - `onQueryChange(cb)` registers a callback that fires whenever the URL
 *   query (text + filters) changes. The callback receives `(query, filters)`.
 */
export function useSearchFilters(route, router) {
  const searchQuery = ref(route.query.q || '')

  // Per-key refs (so individual <q-select v-model>-like reactivity still works
  // and so we can compose the `filters` object without deep watchers).
  const initial = readFiltersFromQuery(route.query)
  const refs = {}
  for (const key of FILTER_KEYS) {
    refs[key] = ref(initial[key])
  }

  const filters = computed({
    get: () => {
      const out = {}
      for (const key of FILTER_KEYS) out[key] = refs[key].value
      return out
    },
    set: (v) => {
      for (const key of FILTER_KEYS) refs[key].value = v[key] ?? null
      applyFilters()
    },
  })

  const isBrowseMode = computed(
    () => !route.query.q && FILTER_KEYS.some((k) => !isEmptyFilterValue(route.query[k])),
  )

  function applyFilters() {
    const query = { ...route.query }
    for (const key of FILTER_KEYS) {
      const value = refs[key].value
      if (isEmptyFilterValue(value)) {
        delete query[key]
      } else if (Array.isArray(value)) {
        query[key] = value.map(String)
      } else {
        query[key] = value
      }
    }
    router.replace({ query })
  }

  // Reactive key for the route watcher: stringify text + filter values so
  // we only fire when something actually changed (no deep compare).
  const _searchKey = computed(() => {
    const q = route.query
    return JSON.stringify([q.q, ...FILTER_KEYS.map((k) => q[k] ?? null)])
  })

  function onQueryChange(callback, { immediate = true } = {}) {
    return watch(
      _searchKey,
      () => {
        const newQuery = route.query
        const q = newQuery.q || ''
        // Sync local state with the URL.
        searchQuery.value = q
        const next = readFiltersFromQuery(newQuery)
        for (const key of FILTER_KEYS) refs[key].value = next[key]
        // Build the filters payload from normalized state so API callers get
        // typed arrays for multi-select filters.
        const activeFilters = {}
        for (const key of FILTER_KEYS) {
          if (!isEmptyFilterValue(refs[key].value)) activeFilters[key] = refs[key].value
        }
        callback(q, activeFilters)
      },
      { immediate },
    )
  }

  return {
    searchQuery,
    filters,
    isBrowseMode,
    applyFilters,
    onQueryChange,
  }
}
