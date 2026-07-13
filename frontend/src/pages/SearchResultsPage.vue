<template>
  <q-page class="search-results-page q-pa-md">
    <div class="search-results-container">
      <header class="search-header">
        <div class="search-header__title">
          <q-icon name="mdi-magnify" size="1.5rem" color="primary" />
          <h1 class="text-h6 text-weight-bold q-ma-none ellipsis">
            {{ resultsHeading }}
          </h1>
          <span v-if="hasSearchContext && !loading" class="search-header__count">
            {{ resultSummary }}
          </span>
        </div>

        <q-btn
          outline
          no-caps
          icon="mdi-tune-variant"
          :label="$t('searchResultsPage.filters')"
          :color="filtersOpen ? 'primary' : undefined"
          @click="filtersOpen = !filtersOpen"
        >
          <q-badge v-if="activeFilterCount" floating color="primary">
            {{ activeFilterCount }}
          </q-badge>
        </q-btn>
      </header>

      <SearchFilterBar
        v-model="filters"
        :expanded="filtersOpen"
        class="q-mb-md"
        :genre-options="genreOptions"
        :platform-options="platformOptions"
        :person-options="personOptions"
        :year-options="yearOptions"
        :studio-options="studioOptions"
        :container-options="containerOptions"
        :content-rating-options="contentRatingOptions"
        @genre-filter="filterGenreOptions"
        @person-filter="filterPersonOptions"
        @studio-filter="filterStudioOptions"
      />

      <main class="search-content">
        <div v-if="!hasSearchContext" class="search-state">
          <q-icon name="mdi-text-search" size="4em" color="grey-5" />
          <h2>{{ $t('searchResultsPage.newSearch') }}</h2>
        </div>

        <template v-else>
          <div v-if="typeTabs.length > 1 || loading" class="results-toolbar">
            <q-tabs
              :model-value="activeTab"
              dense
              no-caps
              inline-label
              active-color="primary"
              indicator-color="primary"
              class="results-tabs"
              @update:model-value="selectTab"
            >
              <q-tab name="all" :label="$t('searchResultsPage.tabAll')">
                <q-badge v-if="allCount" class="q-ml-sm" color="grey-7" :label="allCount" />
              </q-tab>
              <q-tab v-for="tab in typeTabs" :key="tab.type" :name="tab.type" :icon="tab.icon">
                <span class="q-ml-xs">{{ tab.label }}</span>
                <q-badge v-if="tab.count" class="q-ml-sm" :color="tab.color" :label="tab.count" />
              </q-tab>
            </q-tabs>

            <q-select
              v-model="sortValue"
              :options="sortOptions"
              :label="$t('searchResultsPage.sortBy')"
              emit-value
              map-options
              dense
              outlined
              options-dense
              class="results-sort"
            />
          </div>

          <!-- Skeletons keep the grid in place instead of collapsing to a spinner. -->
          <div v-if="loading" class="results-grid">
            <div v-for="n in 12" :key="n" class="skeleton-card">
              <q-skeleton square class="skeleton-card__poster" />
              <q-skeleton type="text" width="80%" />
              <q-skeleton type="text" width="50%" />
            </div>
          </div>

          <div v-else-if="hasNoResults" class="search-state">
            <q-icon name="mdi-magnify-close" size="4em" color="grey-5" />
            <h2>{{ $t('searchResultsPage.noResults') }}</h2>
            <p class="text-body1 text-grey-6">{{ $t('searchResultsPage.noResultsHint') }}</p>
            <q-btn
              v-if="activeFilterCount"
              flat
              color="primary"
              icon="mdi-filter-remove"
              :label="$t('searchResultsPage.clearAll')"
              class="q-mt-md"
              @click="clearAllFilters"
            />
            <q-btn
              v-else
              color="primary"
              icon="mdi-home"
              :label="$t('searchResultsPage.backToHome')"
              class="q-mt-md"
              @click="$router.push('/')"
            />
          </div>

          <template v-else>
            <div class="results-grid">
              <PosterCard
                v-for="(item, idx) in searchResults"
                :key="resultKey(item, idx)"
                :type="getCardType(item)"
                :title="item.title"
                :image-url="getPosterUrl(item)"
                :subtitle="getSubtitle(item)"
                :rating="item.rating"
                :platforms="item.platforms"
                @click="navigateToResult(item)"
              />
            </div>

            <!-- The button auto-loads the next page once it scrolls into view, and
                 stays clickable for keyboard and screen-reader users. (QIntersection
                 is the wrong tool here: it only *renders* its content once visible,
                 so its zero-height placeholder never reliably triggers.) -->
            <div v-if="hasMore" v-intersection="onSentinel" class="results-more">
              <q-btn
                flat
                no-caps
                color="primary"
                :loading="loadingMore"
                :label="$t('searchResultsPage.loadMore')"
                @click="loadMore"
              />
            </div>

            <section v-if="listResults.length" class="lists-section">
              <div class="lists-section__header">
                <q-icon name="mdi-format-list-bulleted" color="teal" size="1.3rem" />
                <span>{{ $t('searchResultsPage.sectionLists') }}</span>
                <q-badge color="teal" :label="listResults.length" />
              </div>
              <div class="results-grid">
                <ListResultCard
                  v-for="list in listResults"
                  :key="list.guid"
                  :list="list"
                  @click="$router.push(`/lists/${list.guid}`)"
                />
              </div>
            </section>
          </template>
        </template>
      </main>
    </div>
  </q-page>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import SearchFilterBar from 'components/SearchFilterBar.vue'
import PosterCard from 'components/PosterCard.vue'
import ListResultCard from 'components/ListResultCard.vue'
import { useMediaTypeMapping } from 'src/composables/useMediaTypeMapping'
import { useSearchFilters } from 'src/composables/useSearchFilters'
import { useSearchAPI } from 'src/composables/useSearchAPI'
import {
  buildSectionConfig,
  buildSortOptions,
  SECTION_ORDER,
  TYPE_TO_MEDIA_TYPE,
  FILTER_ONLY_KEYS,
  PANEL_FILTER_KEYS,
} from 'src/utils/searchOptions'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const { getCardType, getPosterUrl, getResultKey, getSubtitle } = useMediaTypeMapping()

const filtersOpen = ref(false)

// Filter state synced with URL query.
const {
  searchQuery: urlSearchQuery,
  filters,
  isBrowseMode,
  onQueryChange,
} = useSearchFilters(route, router)

// Data layer (results, loading, options, WebSocket, navigation).
const {
  searchResults,
  listResults,
  totalResults,
  typeCounts,
  loading,
  loadingMore,
  hasMore,
  genreOptions,
  platformOptions,
  personOptions,
  yearOptions,
  studioOptions,
  containerOptions,
  contentRatingOptions,
  performSearch,
  loadMore,
  navigateToResult,
  filterGenreOptions,
  filterPersonOptions,
  filterStudioOptions,
} = useSearchAPI(router)

onQueryChange((q, activeFilters) => {
  if (q || Object.keys(activeFilters).length > 0) {
    performSearch(q || null, activeFilters)
  }
})

const searchQuery = computed(() => urlSearchQuery.value)

function isActiveFilterValue(value) {
  return value != null && value !== '' && (!Array.isArray(value) || value.length > 0)
}

const activeFilterCount = computed(
  () => PANEL_FILTER_KEYS.filter((key) => isActiveFilterValue(filters.value[key])).length,
)

const hasSearchContext = computed(() => Boolean(searchQuery.value || isBrowseMode.value))
const hasNoResults = computed(
  () =>
    hasSearchContext.value && searchResults.value.length === 0 && listResults.value.length === 0,
)
const resultSummary = computed(() =>
  t('searchResultsPage.resultsFound', { count: totalResults.value }),
)
const resultsHeading = computed(() =>
  searchQuery.value
    ? t('searchResultsPage.forQuery', { query: searchQuery.value })
    : t('searchResultsPage.searchResults'),
)

function resultKey(item, idx) {
  return getResultKey(item) ?? idx
}

// --- Type tabs -------------------------------------------------------------
// Counts come from the API's facets, which are counted across *all* types
// regardless of the active one — so switching tabs never blanks the others.
const sectionConfig = buildSectionConfig(t)

const typeTabs = computed(() =>
  SECTION_ORDER.filter((type) => typeCounts.value[type]).map((type) => {
    const cfg = sectionConfig[type] || {}
    return {
      type,
      icon: cfg.icon,
      color: cfg.color,
      label: cfg.label ?? type,
      count: typeCounts.value[type],
    }
  }),
)

const allCount = computed(() =>
  Object.values(typeCounts.value).reduce((sum, count) => sum + count, 0),
)

const activeTab = computed(() => {
  const mediaType = filters.value.media_type
  if (!mediaType) return 'all'
  const match = Object.entries(TYPE_TO_MEDIA_TYPE).find(([, value]) => value === mediaType)
  return match ? match[0] : 'all'
})

function selectTab(tab) {
  filters.value = {
    ...filters.value,
    media_type: tab === 'all' ? null : TYPE_TO_MEDIA_TYPE[tab],
  }
}

// --- Sorting ---------------------------------------------------------------
// "Recently added" is a library notion. A text search is answered by the
// metadata providers, whose hits were never added to anything — so the option
// is dropped rather than offered as a no-op.
const sortOptions = computed(() => {
  const options = buildSortOptions(t)
  if (!searchQuery.value) return options
  return options.filter((option) => !option.value.startsWith('created_at'))
})

const sortValue = computed({
  get: () => `${filters.value.sort_by || '_score'}:${filters.value.sort_order || 'desc'}`,
  set: (value) => {
    const [sortBy, sortOrder] = value.split(':')
    filters.value = { ...filters.value, sort_by: sortBy, sort_order: sortOrder }
  },
})

function clearAllFilters() {
  const cleared = { ...filters.value }
  for (const key of FILTER_ONLY_KEYS) cleared[key] = null
  filters.value = cleared
}

function onSentinel(entry) {
  if (entry.isIntersecting) loadMore()
}
</script>

<style lang="scss" scoped>
.search-results-page {
  min-height: 100%;
}

.search-results-container {
  max-width: 1440px;
  margin: 0 auto;
}

.search-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 12px;
}

.search-header__title {
  display: flex;
  align-items: baseline;
  gap: 10px;
  min-width: 0;
}

.search-header__count {
  flex-shrink: 0;
  font-size: 0.85rem;
  opacity: 0.65;
}

.results-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
  border-bottom: 1px solid rgba(128, 128, 128, 0.2);
}

.results-tabs {
  min-width: 0;
  flex: 1;
}

.results-sort {
  width: 200px;
  flex-shrink: 0;
  padding-bottom: 6px;
}

.results-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(148px, 1fr));
  gap: 16px;
  align-items: start;
}

.skeleton-card__poster {
  width: 100%;
  aspect-ratio: 2 / 3;
  margin-bottom: 8px;
}

.results-more {
  display: flex;
  justify-content: center;
  padding: 24px 0;
}

.lists-section {
  margin-top: 32px;
  padding-top: 20px;
  border-top: 1px solid rgba(128, 128, 128, 0.2);
}

.lists-section__header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  font-size: 1.05rem;
  font-weight: 700;
}

.search-state {
  display: flex;
  min-height: 360px;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 32px 16px;

  h2 {
    margin: 16px 0 8px;
    font-size: 1.35rem;
    font-weight: 700;
  }
}

@media (max-width: 768px) {
  .results-grid {
    gap: 12px;
    grid-template-columns: repeat(auto-fill, minmax(136px, 1fr));
  }

  .results-toolbar {
    align-items: stretch;
    flex-direction: column;
    gap: 8px;
  }

  .results-sort {
    width: 100%;
  }
}

@media (max-width: 480px) {
  .search-results-page {
    padding: 12px;
  }

  .results-grid {
    gap: 10px;
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
