/**
 * useSectionData — shared data layer for page-layout section components.
 *
 * Two responsibilities, both previously copy-pasted across ~7 *Section.vue
 * components:
 *
 *   1. The load/`rendered_items` short-circuit pattern: when the backend has
 *      pre-rendered a section's items they are used verbatim; otherwise a
 *      per-section `loader` fetches them. Loading state, error handling and the
 *      onMounted + deep watch wiring are handled here once.
 *
 *   2. A single filter -> payload / query-param mapping, so the search API
 *      payload and the "see all" `/search` URL are always derived from the same
 *      definition instead of two hand-maintained copies.
 */
import { computed, onMounted, ref, watch } from 'vue'
import { logger } from 'src/utils/logger'

const toGetter = (value) => (typeof value === 'function' ? value : () => value)
const isSet = (value) => value !== undefined && value !== null

/**
 * @param {Object}   opts
 * @param {Function|Object} opts.section      Section object or getter returning it.
 * @param {Function|string} [opts.mediaType]  Page-level media type or getter.
 * @param {Function}        opts.loader       async () => items[] (no-rendered path).
 * @param {Function}        [opts.mapRendered] (renderedItems[]) => items[].
 * @param {boolean}         [opts.clearOnError=true] Reset items to [] when loader throws.
 * @param {Function}        [opts.watchSources] Custom watch source getter.
 * @param {boolean}         [opts.immediate=true] Load on mount.
 */
export function useSectionData({
  section,
  mediaType,
  loader,
  mapRendered,
  clearOnError = true,
  watchSources,
  immediate = true,
} = {}) {
  const getSection = toGetter(section)
  const getMediaType = toGetter(mediaType ?? null)

  const items = ref([])
  const loading = ref(false)

  const hasRenderedItems = computed(() =>
    Object.prototype.hasOwnProperty.call(getSection() || {}, 'rendered_items'),
  )

  async function load() {
    const sec = getSection() || {}

    if (hasRenderedItems.value) {
      const rendered = sec.rendered_items || []
      items.value = mapRendered ? mapRendered(rendered) : rendered
      loading.value = false
      return
    }

    loading.value = true
    try {
      items.value = (await loader()) || []
    } catch (error) {
      logger.error('Error loading section items:', error)
      if (clearOnError) items.value = []
    } finally {
      loading.value = false
    }
  }

  const defaultWatch = () => {
    const sec = getSection() || {}
    return [getMediaType(), sec.config, sec.rendered_items]
  }

  if (immediate) onMounted(load)
  watch(watchSources || defaultWatch, load, { deep: true })

  return { items, loading, hasRenderedItems, load }
}

/**
 * Build the POST /api/search/ payload from a section's `filters` object.
 * Single definition shared with {@link buildSearchQueryParams} so the fetched
 * items and the "see all" link can never drift apart.
 *
 * @param {Object} filters               config.filters
 * @param {Object} [opts]
 * @param {string} [opts.mediaType]      Page-level media type fallback.
 * @param {number} [opts.perPage=10]
 * @param {number} [opts.page=1]
 */
export function buildSearchPayload(filters, { mediaType = null, perPage = 10, page = 1 } = {}) {
  const f = filters || {}
  const payload = {
    per_page: perPage,
    page,
    search_type: f.media_type ? f.media_type.toLowerCase() : 'all',
  }

  if (f.query) payload.query = f.query
  if (f.media_type) payload.media_type = f.media_type
  if (f.genre_id) payload.genre_id = f.genre_id
  if (f.platform_id) payload.platform_id = f.platform_id
  if (f.genres && f.genres.length) payload.genres = f.genres
  if (f.year_from) payload.year_from = f.year_from
  if (f.year_to) payload.year_to = f.year_to
  if (f.sort_by) payload.sort_by = f.sort_by
  if (f.sort_order) payload.sort_order = f.sort_order
  if (f.availability) payload.availability = f.availability
  if (f.studio_name) payload.studio_name = f.studio_name
  if (f.container) payload.container = f.container
  if (f.content_rating) payload.content_rating = f.content_rating
  if (isSet(f.has_poster)) payload.has_poster = f.has_poster
  if (isSet(f.has_backdrop)) payload.has_backdrop = f.has_backdrop
  if (isSet(f.has_description)) payload.has_description = f.has_description
  if (isSet(f.is_favorite)) payload.is_favorite = f.is_favorite
  if (isSet(f.is_played)) payload.is_played = f.is_played

  // Page-level media type as fallback when the filter doesn't pin one.
  if (!payload.media_type && mediaType) {
    payload.media_type = mediaType
    payload.search_type = mediaType.toLowerCase()
  }

  return payload
}

/**
 * Build the URLSearchParams for a "see all" /search link from the same filter
 * object as {@link buildSearchPayload}.
 *
 * @param {Object} filters          config.filters
 * @param {Object} [opts]
 * @param {string} [opts.mediaType] Page-level media type override.
 */
export function buildSearchQueryParams(filters, { mediaType = null } = {}) {
  const f = filters || {}
  const params = new URLSearchParams()

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
  if (isSet(f.has_poster)) params.set('has_poster', f.has_poster)
  if (isSet(f.has_backdrop)) params.set('has_backdrop', f.has_backdrop)
  if (isSet(f.has_description)) params.set('has_description', f.has_description)
  if (isSet(f.is_favorite)) params.set('is_favorite', f.is_favorite)
  if (isSet(f.is_played)) params.set('is_played', f.is_played)
  // Page-level media type wins when set (matches legacy behaviour).
  if (mediaType) params.set('media_type', mediaType)

  return params
}
