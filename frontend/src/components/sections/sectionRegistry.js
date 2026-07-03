/**
 * Central Section Registry — single source of truth for section types.
 *
 * Every place that needs to map a `section_type` string to a runtime component,
 * config form, icon, human label, or default config derives it from here.
 * Adding a new section type = one entry here (+ its component / config form),
 * not a literal edited in 7 files.
 *
 * Components and config forms are wrapped in `defineAsyncComponent` so that
 * modules which only need icons/labels (e.g. SectionEditOverlay,
 * EditPageLayoutPage) do not eagerly pull every section chunk into their bundle,
 * and so the registry never creates a circular import.
 */
import { defineAsyncComponent } from 'vue'

const asyncSection = (loader) => defineAsyncComponent(loader)

export const sectionRegistry = {
  hero_carousel: {
    component: asyncSection(() => import('src/components/sections/HeroCarouselSection.vue')),
    configForm: asyncSection(
      () => import('src/components/sections/configForms/HeroCarouselConfigForm.vue'),
    ),
    icon: 'mdi-image-multiple',
    label: 'Hero Carousel',
    labelKey: 'pageLayouts.sectionTypes.heroCarousel',
    defaultConfig: { source_type: 'trending', filters: {} },
  },
  genre: {
    component: asyncSection(() => import('src/components/sections/GenreSection.vue')),
    configForm: asyncSection(
      () => import('src/components/sections/configForms/GenreSectionConfigForm.vue'),
    ),
    icon: 'mdi-tag',
    label: 'Specific Genre',
    labelKey: 'pageLayouts.sectionTypes.genre',
    defaultConfig: { filters: {}, max_items: 20 },
  },
  all_genres: {
    component: asyncSection(() => import('src/components/sections/AllGenresSection.vue')),
    configForm: asyncSection(
      () => import('src/components/sections/configForms/GenreSectionConfigForm.vue'),
    ),
    icon: 'mdi-tag-multiple',
    label: 'All Genres',
    labelKey: 'pageLayouts.sectionTypes.allGenres',
    defaultConfig: { filters: {}, max_items_per_genre: 20 },
  },
  list: {
    component: asyncSection(() => import('src/components/sections/ListSection.vue')),
    configForm: asyncSection(
      () => import('src/components/sections/configForms/ListSectionConfigForm.vue'),
    ),
    icon: 'mdi-format-list-bulleted',
    label: 'List',
    labelKey: 'pageLayouts.sectionTypes.list',
    defaultConfig: { filters: {}, max_items: 20, max_rows: 5 },
  },
  dynamic_search: {
    component: asyncSection(() => import('src/components/sections/DynamicSearchSection.vue')),
    configForm: asyncSection(
      () => import('src/components/sections/configForms/DynamicSearchConfigForm.vue'),
    ),
    icon: 'mdi-magnify',
    label: 'Dynamic Search',
    labelKey: 'pageLayouts.sectionTypes.dynamicSearch',
    defaultConfig: { filters: { sort_order: 'desc' }, max_items: 20 },
  },
  latest_items: {
    component: asyncSection(() => import('src/components/sections/LatestItemsSection.vue')),
    configForm: asyncSection(
      () => import('src/components/sections/configForms/LatestItemsConfigForm.vue'),
    ),
    icon: 'mdi-clock-outline',
    label: 'Latest Items',
    labelKey: 'pageLayouts.sectionTypes.latestItems',
    defaultConfig: { max_items: 20 },
  },
  continue_watching: {
    component: asyncSection(() => import('src/components/sections/ContinueWatchingSection.vue')),
    configForm: asyncSection(
      () => import('src/components/sections/configForms/ContinueWatchingConfigForm.vue'),
    ),
    icon: 'mdi-play-circle',
    label: 'Continue Watching',
    labelKey: 'pageLayouts.sectionTypes.continueWatching',
    defaultConfig: {},
  },
  favorites: {
    component: asyncSection(() => import('src/components/sections/FavoritesSection.vue')),
    configForm: null,
    icon: 'mdi-heart',
    label: 'Favorites',
    labelKey: 'pageLayouts.sectionTypes.favorites',
    defaultConfig: {},
  },
  platforms: {
    component: asyncSection(() => import('src/components/sections/PlatformsSection.vue')),
    configForm: null,
    icon: 'mdi-gamepad-variant',
    label: 'Platforms',
    labelKey: 'pageLayouts.sectionTypes.platforms',
    defaultConfig: {},
  },
  trailers: {
    component: asyncSection(() => import('src/components/sections/TrailersSection.vue')),
    configForm: asyncSection(
      () => import('src/components/sections/configForms/TrailersConfigForm.vue'),
    ),
    icon: 'mdi-movie-open-play',
    label: 'Trailers',
    labelKey: 'pageLayouts.sectionTypes.trailers',
    defaultConfig: { max_items: 20 },
  },
}

const DEFAULT_ICON = 'mdi-view-dashboard'

/** Ordered list of section types (drives dropdowns / option lists). */
export const sectionTypes = Object.keys(sectionRegistry)

/** Runtime section component for a type, or null if unknown. */
export function getSectionComponent(type) {
  return sectionRegistry[type]?.component || null
}

/** Config form component for a type (null when the type has no config form). */
export function getSectionConfigForm(type) {
  return sectionRegistry[type]?.configForm || null
}

/** Icon name for a type, falling back to a generic dashboard icon. */
export function getSectionIcon(type) {
  return sectionRegistry[type]?.icon || DEFAULT_ICON
}

/**
 * Human label for a type. Pass a vue-i18n `t` to get the translated label
 * (falls back to the built-in English label); omit it for the raw fallback.
 */
export function getSectionLabel(type, t) {
  const entry = sectionRegistry[type]
  if (!entry) return type
  return t ? t(entry.labelKey, entry.label) : entry.label
}

/** Deep-cloned default config for a type. */
export function getSectionDefaultConfig(type) {
  const entry = sectionRegistry[type]
  return JSON.parse(JSON.stringify(entry?.defaultConfig ?? { filters: {} }))
}

/**
 * Build the `{ value, label }` options for a section-type <q-select>.
 * @param {Function} [t] vue-i18n translate function.
 */
export function getSectionTypeOptions(t) {
  return sectionTypes.map((type) => ({ value: type, label: getSectionLabel(type, t) }))
}

/** Map of type -> config form component, for types that have one. */
export function getSectionConfigComponents() {
  const map = {}
  for (const type of sectionTypes) {
    const form = getSectionConfigForm(type)
    if (form) map[type] = form
  }
  return map
}
