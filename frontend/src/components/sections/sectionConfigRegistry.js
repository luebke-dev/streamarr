// Section-type -> component/config-form/icon/label/defaults now live in a single
// source of truth (sectionRegistry). These exports are thin adapters kept for
// backwards compatibility with existing callers (SectionConfigDialog).
import {
  getSectionConfigComponents,
  getSectionDefaultConfig,
  getSectionTypeOptions,
} from 'src/components/sections/sectionRegistry'

export const SECTION_CONFIG_COMPONENTS = getSectionConfigComponents()

export function createSectionDefaultConfig(sectionType) {
  return getSectionDefaultConfig(sectionType)
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
    sectionTypeOptions: getSectionTypeOptions(t),
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
