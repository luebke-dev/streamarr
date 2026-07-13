/**
 * Shared builder for the POST /api/search/ request body.
 *
 * Previously two divergent copies existed — one in useSearchAPI.js (search
 * page, URL-derived string/array filters) and one in useSectionData.js (page
 * sections, config-derived typed filters). They are unified here so both call
 * sites derive their payload from a single definition.
 *
 * The coercion helpers are deliberately input-type aware so the same code
 * reproduces both call sites byte-for-byte:
 *   - URL filters arrive as strings ('true'/'false', '2020', …) and are coerced.
 *   - Section-config filters arrive already typed (booleans, numbers) and pass
 *     through unchanged.
 *
 * Options gate the parts that genuinely differ between the two callers:
 *   - `deriveSearchType`  section derives search_type from media_type; the
 *                         search page always keeps search_type = 'all'.
 *   - `extendedFilters`   the search page emits the *_ids / exclude_* / years /
 *                         person_guid family; sections never do.
 *   - `genresFilter`      sections emit the `genres` array; the search page
 *                         does not (it uses genre_ids).
 */

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

const isSet = (value) => value !== undefined && value !== null
const coerceNum = (value) => (typeof value === 'string' ? Number(value) : value)
const coerceBool = (value) => (typeof value === 'string' ? value === 'true' : value)

/**
 * @param {Object} filters                   Filter values (URL- or config-derived).
 * @param {Object} [options]
 * @param {string} [options.mediaType]        Page-level media type fallback.
 * @param {number} [options.perPage=50]
 * @param {number} [options.page=1]
 * @param {boolean} [options.deriveSearchType=false]  Derive search_type from media_type.
 * @param {boolean} [options.extendedFilters=true]    Emit the search-page-only filter family.
 * @param {boolean} [options.genresFilter=false]      Emit the section-only `genres` array.
 * @param {boolean} [options.withFacets=false]        Request media-type facet counts
 *                                                    (the search page's type tabs need them;
 *                                                    page sections would only pay for them).
 */
export function buildSearchPayload(filters = {}, options = {}) {
  const {
    mediaType = null,
    perPage = 50,
    page = 1,
    deriveSearchType = false,
    extendedFilters = true,
    genresFilter = false,
    withFacets = false,
  } = options
  const f = filters || {}

  const payload = { search_type: 'all', per_page: perPage, page }
  if (withFacets) payload.with_facets = true
  if (deriveSearchType && f.media_type) payload.search_type = f.media_type.toLowerCase()

  if (f.query) payload.query = f.query

  if (f.genre_id) payload.genre_id = coerceNum(f.genre_id)
  if (f.platform_id) payload.platform_id = coerceNum(f.platform_id)

  if (extendedFilters) {
    const genreIds = numericList(f.genre_ids)
    if (genreIds.length) payload.genre_ids = genreIds
    const excludeGenreIds = numericList(f.exclude_genre_ids)
    if (excludeGenreIds.length) payload.exclude_genre_ids = excludeGenreIds
    const platformIds = numericList(f.platform_ids)
    if (platformIds.length) payload.platform_ids = platformIds
    const excludePlatformIds = numericList(f.exclude_platform_ids)
    if (excludePlatformIds.length) payload.exclude_platform_ids = excludePlatformIds
  }

  if (genresFilter && f.genres && f.genres.length) payload.genres = f.genres

  if (f.media_type) payload.media_type = f.media_type
  if (f.availability) payload.availability = f.availability

  if (isSet(f.has_poster)) payload.has_poster = coerceBool(f.has_poster)
  if (isSet(f.has_backdrop)) payload.has_backdrop = coerceBool(f.has_backdrop)
  if (isSet(f.has_description)) payload.has_description = coerceBool(f.has_description)
  if (isSet(f.is_favorite)) payload.is_favorite = coerceBool(f.is_favorite)
  if (isSet(f.is_played)) payload.is_played = coerceBool(f.is_played)

  if (extendedFilters) {
    if (f.person_guid) payload.person_guid = f.person_guid
    if (f.exclude_person_guid) payload.exclude_person_guid = f.exclude_person_guid
  }

  if (f.studio_name) payload.studio_name = f.studio_name
  if (f.container) payload.container = f.container
  if (f.content_rating) payload.content_rating = f.content_rating

  if (extendedFilters) {
    const excludeContainers = stringList(f.exclude_containers)
    if (excludeContainers.length) payload.exclude_containers = excludeContainers
    const excludeContentRatings = stringList(f.exclude_content_ratings)
    if (excludeContentRatings.length) payload.exclude_content_ratings = excludeContentRatings
    const years = numericList(f.years)
    if (years.length) payload.years = years
    const excludeYears = numericList(f.exclude_years)
    if (excludeYears.length) payload.exclude_years = excludeYears
  }

  if (f.year_from) payload.year_from = coerceNum(f.year_from)
  if (f.year_to) payload.year_to = coerceNum(f.year_to)
  if (f.sort_by) payload.sort_by = f.sort_by
  if (f.sort_order) payload.sort_order = f.sort_order

  // Page-level media type as fallback when the filter doesn't pin one.
  if (!payload.media_type && mediaType) {
    payload.media_type = mediaType
    if (deriveSearchType) payload.search_type = mediaType.toLowerCase()
  }

  return payload
}
