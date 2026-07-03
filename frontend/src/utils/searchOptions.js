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

export function buildSortByOptions(t) {
  return [
    { label: t('searchResultsPage.sortRelevance'), value: '_score' },
    { label: t('searchResultsPage.sortTitle'), value: 'title.keyword' },
    { label: t('searchResultsPage.sortReleaseDate'), value: 'release_date' },
    { label: t('searchResultsPage.sortCreated'), value: 'created_at' },
    { label: t('searchResultsPage.sortUpdated'), value: 'updated_at' },
  ]
}

export function buildSortOrderOptions(t) {
  return [
    { label: t('searchResultsPage.sortDescending'), value: 'desc' },
    { label: t('searchResultsPage.sortAscending'), value: 'asc' },
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
