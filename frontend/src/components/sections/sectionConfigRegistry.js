import ContinueWatchingConfigForm from 'src/components/sections/configForms/ContinueWatchingConfigForm.vue'
import DynamicSearchConfigForm from 'src/components/sections/configForms/DynamicSearchConfigForm.vue'
import GenreSectionConfigForm from 'src/components/sections/configForms/GenreSectionConfigForm.vue'
import HeroCarouselConfigForm from 'src/components/sections/configForms/HeroCarouselConfigForm.vue'
import LatestItemsConfigForm from 'src/components/sections/configForms/LatestItemsConfigForm.vue'
import ListSectionConfigForm from 'src/components/sections/configForms/ListSectionConfigForm.vue'
import TrailersConfigForm from 'src/components/sections/configForms/TrailersConfigForm.vue'

export const SECTION_CONFIG_COMPONENTS = {
  hero_carousel: HeroCarouselConfigForm,
  genre: GenreSectionConfigForm,
  all_genres: GenreSectionConfigForm,
  list: ListSectionConfigForm,
  dynamic_search: DynamicSearchConfigForm,
  latest_items: LatestItemsConfigForm,
  continue_watching: ContinueWatchingConfigForm,
  trailers: TrailersConfigForm,
}

export function createSectionDefaultConfig(sectionType) {
  const defaults = {
    hero_carousel: { source_type: 'trending', filters: {} },
    genre: { filters: {}, max_items: 20 },
    all_genres: { filters: {}, max_items_per_genre: 20 },
    list: { filters: {}, max_items: 20, max_rows: 5 },
    dynamic_search: { filters: { sort_order: 'desc' }, max_items: 20 },
    latest_items: { max_items: 20 },
    continue_watching: {},
    favorites: {},
    platforms: {},
    trailers: { max_items: 20 },
  }
  return JSON.parse(JSON.stringify(defaults[sectionType] || { filters: {} }))
}

export function createSectionConfigOptions(t) {
  const label = (key, fallback) => t(`pageLayouts.${key}`, fallback)

  return {
    labels: {
      listUpdateSource: label(
        'listUpdateSource',
        'Per-user list (update_source, e.g. rec:for_you:movies)',
      ),
      listUpdateSourceHint: label(
        'listUpdateSourceHint',
        'Overrides list_guid when set. Resolved per logged-in user.',
      ),
      listUpdateSourcePrefix: label(
        'listUpdateSourcePrefix',
        'Multi-row prefix (e.g. rec:because:)',
      ),
      listUpdateSourcePrefixHint: label(
        'listUpdateSourcePrefixHint',
        'When set, renders up to max_rows carousels, one per matched list.',
      ),
      maxRows: label('maxRows', 'Max rows (prefix mode)'),
      studio: label('studio', 'Studio'),
      container: label('container', 'Container'),
      contentRating: label('contentRating', 'Content rating'),
      favoriteState: label('favoriteState', 'Favorite state'),
      playedState: label('playedState', 'Played state'),
      hasBackdrop: label('hasBackdrop', 'Has backdrop'),
    },
    sectionTypeOptions: [
      { value: 'hero_carousel', label: label('sectionTypes.heroCarousel', 'Hero Carousel') },
      { value: 'genre', label: label('sectionTypes.genre', 'Specific Genre') },
      { value: 'all_genres', label: label('sectionTypes.allGenres', 'All Genres') },
      { value: 'list', label: label('sectionTypes.list', 'List') },
      { value: 'dynamic_search', label: label('sectionTypes.dynamicSearch', 'Dynamic Search') },
      { value: 'latest_items', label: label('sectionTypes.latestItems', 'Latest Items') },
      {
        value: 'continue_watching',
        label: label('sectionTypes.continueWatching', 'Continue Watching'),
      },
      { value: 'favorites', label: label('sectionTypes.favorites', 'Favorites') },
      { value: 'platforms', label: label('sectionTypes.platforms', 'Platforms') },
      { value: 'trailers', label: label('sectionTypes.trailers', 'Trailers') },
    ],
    carouselSourceOptions: [
      { value: 'trending', label: label('sourceTypes.trending', 'Trending (default)') },
      { value: 'list', label: label('sourceTypes.list', 'Specific list') },
      { value: 'dynamic_search', label: label('sourceTypes.dynamicSearch', 'Dynamic search') },
    ],
    contentTypeOptions: [
      { value: 'movie', label: label('contentTypes.movies', 'Movies') },
      { value: 'episode', label: label('contentTypes.episodes', 'Shows (Episodes)') },
      { value: 'game', label: label('contentTypes.games', 'Games') },
      { value: 'music', label: label('contentTypes.music', 'Music') },
      { value: 'book', label: label('contentTypes.books', 'Books') },
    ],
    mediaTypeOptions: [
      { value: 'MOVIES', label: label('mediaTypes.movies', 'Movies') },
      { value: 'SHOWS', label: label('mediaTypes.shows', 'Shows') },
      { value: 'GAMES', label: label('mediaTypes.games', 'Games') },
      { value: 'MUSIC', label: label('mediaTypes.music', 'Music') },
      { value: 'BOOKS', label: label('mediaTypes.books', 'Books') },
    ],
    sortByOptions: [
      { value: 'title.keyword', label: label('sortFields.title', 'Title') },
      { value: 'release_date', label: label('sortFields.releaseDate', 'Release Date') },
      { value: 'created_at', label: label('sortFields.createdAt', 'Date Added') },
      { value: 'updated_at', label: label('sortFields.updatedAt', 'Date Updated') },
    ],
    sortOrderOptions: [
      { value: 'asc', label: label('sortOrders.asc', 'Ascending') },
      { value: 'desc', label: label('sortOrders.desc', 'Descending') },
    ],
    availabilityOptions: [
      { value: 'local', label: label('availability.local', 'Local (has files)') },
      { value: 'releases', label: label('availability.releases', 'Has releases') },
      { value: 'none', label: label('availability.none', 'No files or releases') },
    ],
    booleanOptions: [
      { value: true, label: label('boolean.yes', 'Yes') },
      { value: false, label: label('boolean.no', 'No') },
    ],
    favoriteStateOptions: [
      { value: true, label: label('favoriteStates.only', 'Favorites only') },
      { value: false, label: label('favoriteStates.not', 'Not favorites') },
    ],
    playedStateOptions: [
      { value: true, label: label('playedStates.only', 'Played only') },
      { value: false, label: label('playedStates.not', 'Unplayed only') },
    ],
  }
}
