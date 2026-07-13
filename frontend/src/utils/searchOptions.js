/**
 * Shared option lists and configuration for SearchResultsPage filters
 * and result sections.
 *
 * Static lists are exported as constants. Lists that depend on i18n
 * translations are exported as factory functions taking the `t` function
 * from `useI18n()` and returning a fresh array.
 *
 * Used by:
 *  - src/pages/SearchResultsPage.vue
 */

export function buildMediaTypeOptions(t) {
  return [
    { label: t('searchResultsPage.sectionMovies'), value: 'MOVIES' },
    { label: t('searchResultsPage.sectionShows'), value: 'SHOWS' },
    { label: t('searchResultsPage.sectionGames'), value: 'GAMES' },
    { label: t('searchResultsPage.sectionArtists'), value: 'MUSIC' },
  ]
}

export function buildAvailabilityOptions(t) {
  return [
    { label: t('searchResultsPage.availLocal'), value: 'local' },
    { label: t('searchResultsPage.availReleases'), value: 'releases' },
    { label: t('searchResultsPage.availNone'), value: 'none' },
  ]
}

export function buildPosterOptions(t) {
  return [
    { label: t('searchResultsPage.hasPoster'), value: 'true' },
    { label: t('searchResultsPage.noPoster'), value: 'false' },
  ]
}

export function buildBackdropOptions(t) {
  return [
    { label: t('searchResultsPage.hasBackdrop'), value: 'true' },
    { label: t('searchResultsPage.noBackdrop'), value: 'false' },
  ]
}

export function buildDescriptionOptions(t) {
  return [
    { label: t('searchResultsPage.hasDescription'), value: 'true' },
    { label: t('searchResultsPage.noDescription'), value: 'false' },
  ]
}

export function buildFavoriteOptions(t) {
  return [
    { label: t('searchResultsPage.favoritesOnly'), value: 'true' },
    { label: t('searchResultsPage.notFavorites'), value: 'false' },
  ]
}

export function buildPlayedOptions(t) {
  return [
    { label: t('searchResultsPage.playedOnly'), value: 'true' },
    { label: t('searchResultsPage.unplayedOnly'), value: 'false' },
  ]
}

/**
 * Per-media-type section configuration (icon, color, i18n label key).
 * Use buildSectionConfig(t) to materialize translated labels.
 */
export function buildSectionConfig(t) {
  return {
    movies: { icon: 'mdi-movie', color: 'red', label: t('searchResultsPage.sectionMovies') },
    shows: { icon: 'mdi-television', color: 'blue', label: t('searchResultsPage.sectionShows') },
    music: {
      icon: 'mdi-account-music',
      color: 'purple',
      label: t('searchResultsPage.sectionArtists'),
    },
    games: {
      icon: 'mdi-gamepad-variant',
      color: 'green',
      label: t('searchResultsPage.sectionGames'),
    },
    books: { icon: 'mdi-book', color: 'orange', label: t('searchResultsPage.sectionBooks') },
  }
}

/** Display order for media-type sections in the result list. */
export const SECTION_ORDER = ['movies', 'shows', 'music', 'games', 'books']

/**
 * Media type each result-type tab filters on. The keys are the `type` values
 * search hits carry (and the facet keys the API returns); the values are what
 * the `media_type` filter expects.
 */
export const TYPE_TO_MEDIA_TYPE = {
  movies: 'MOVIES',
  shows: 'SHOWS',
  music: 'MUSIC',
  games: 'GAMES',
  books: 'BOOKS',
}

/**
 * Sort options for the results toolbar.
 *
 * `value` is the `sort_by:sort_order` pair the API expects, kept as one string
 * so a single q-select can drive both URL params.
 */
export function buildSortOptions(t) {
  return [
    { label: t('searchResultsPage.sortRelevance'), value: '_score:desc' },
    { label: t('searchResultsPage.sortTitleAsc'), value: 'title.keyword:asc' },
    { label: t('searchResultsPage.sortNewest'), value: 'release_date:desc' },
    { label: t('searchResultsPage.sortOldest'), value: 'release_date:asc' },
    { label: t('searchResultsPage.sortAdded'), value: 'created_at:desc' },
  ]
}

/** URL query keys recognized as filter parameters. */
export const FILTER_KEYS = [
  'genre_id',
  'genre_ids',
  'exclude_genre_ids',
  'platform_id',
  'platform_ids',
  'exclude_platform_ids',
  'media_type',
  'availability',
  'has_poster',
  'has_backdrop',
  'has_description',
  'is_favorite',
  'is_played',
  'person_guid',
  'exclude_person_guid',
  'studio_name',
  'container',
  'exclude_containers',
  'content_rating',
  'exclude_content_ratings',
  'years',
  'exclude_years',
  'year_from',
  'year_to',
  'sort_by',
  'sort_order',
  'genres',
]

/**
 * Keys that express sort order rather than a filter. They live in the URL
 * alongside the filters, but the UI treats them separately: sorting is a
 * toolbar control, not a removable filter chip, and it must not count towards
 * "how many filters are active".
 */
export const SORT_KEYS = ['sort_by', 'sort_order']

/** Filter keys proper — everything the user can narrow results with. */
export const FILTER_ONLY_KEYS = FILTER_KEYS.filter((key) => !SORT_KEYS.includes(key))

/**
 * The type tabs drive the `media_type` filter, so it is shown as a tab rather
 * than duplicated as a chip and a select inside the filter panel.
 */
export const PANEL_FILTER_KEYS = FILTER_ONLY_KEYS.filter((key) => key !== 'media_type')
