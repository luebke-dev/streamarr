<template>
  <q-page class="search-results-page q-pa-md">
    <div class="search-results-container">
      <div class="search-page-header">
        <div class="search-page-header__title">
          <q-icon name="mdi-magnify" size="1.6rem" color="primary" />
          <div class="search-page-header__copy">
            <h1 class="text-h5 text-weight-bold q-ma-none">
              {{ $t('searchResultsPage.searchResults') }}
            </h1>
            <div v-if="searchQuery" class="search-page-header__subtitle">
              {{ $t('searchResultsPage.forQuery', { query: searchQuery }) }}
            </div>
          </div>
        </div>

        <div class="search-page-header__meta">
          <q-chip
            v-if="hasSearchContext"
            dense
            square
            color="primary"
            text-color="white"
            icon="mdi-counter"
          >
            {{ resultSummary }}
          </q-chip>
          <q-chip
            v-if="activeFilterCount"
            dense
            square
            color="blue-grey-7"
            text-color="white"
            icon="mdi-filter-variant"
          >
            {{ activeFilterCount }}
          </q-chip>
          <q-chip
            v-if="searchSource"
            dense
            square
            color="teal-7"
            text-color="white"
            icon="mdi-database-search"
          >
            {{ searchSource }}
          </q-chip>
        </div>
      </div>

      <SearchFilterBar
        v-model="filters"
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
        <div v-if="loading" class="search-state">
          <q-spinner color="primary" size="3em" />
          <p class="text-h6 q-mt-md">{{ $t('searchResultsPage.searching') }}</p>
        </div>

        <div v-else-if="!hasSearchContext" class="search-state search-state--empty">
          <q-icon name="mdi-text-search" size="4em" color="grey-5" />
          <h2>{{ $t('searchResultsPage.newSearch') }}</h2>
        </div>

        <div v-else-if="hasNoResults" class="search-state">
          <q-icon name="mdi-magnify-close" size="4em" color="grey-5" />
          <h2>{{ $t('searchResultsPage.noResults') }}</h2>
          <p class="text-body1 text-grey-6">{{ $t('searchResultsPage.noResultsHint') }}</p>
          <q-btn
            color="primary"
            :label="$t('searchResultsPage.backToHome')"
            icon="mdi-home"
            @click="$router.push('/')"
            class="q-mt-md"
          />
        </div>

        <template v-else>
          <div class="results-overview">
            <div>
              <div class="text-caption text-grey-5">{{ resultSummary }}</div>
              <div class="text-h6 text-weight-bold">{{ resultsHeading }}</div>
            </div>
            <div class="results-overview__counts">
              <q-badge color="primary" :label="mediaResultCount" />
              <span>{{ $t('searchResultsPage.suggestionMedia') }}</span>
              <q-badge v-if="listResultCount" color="teal" :label="listResultCount" />
              <span v-if="listResultCount">{{ $t('searchResultsPage.sectionLists') }}</span>
            </div>
          </div>

          <SearchResultsSection
            v-for="section in resultSections"
            :key="section.type"
            :icon="section.icon"
            :color="section.color"
            :label="section.label"
            :items="section.items"
            @select="navigateToResult"
          />

          <SearchResultsSection
            v-if="listResults.length > 0"
            icon="mdi-format-list-bulleted"
            color="teal"
            :label="$t('searchResultsPage.sectionLists')"
            :items="listResults"
            :key-fn="(list) => list.guid"
          >
            <template #item="{ item }">
              <ListResultCard :list="item" @click="$router.push(`/lists/${item.guid}`)" />
            </template>
          </SearchResultsSection>
        </template>
      </main>
    </div>
  </q-page>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import SearchFilterBar from 'components/SearchFilterBar.vue'
import SearchResultsSection from 'components/SearchResultsSection.vue'
import ListResultCard from 'components/ListResultCard.vue'
import { useMediaTypeMapping } from 'src/composables/useMediaTypeMapping'
import { useSearchFilters } from 'src/composables/useSearchFilters'
import { useSearchAPI } from 'src/composables/useSearchAPI'
import { buildSectionConfig, SECTION_ORDER, FILTER_KEYS } from 'src/utils/searchOptions'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const { getMediaType } = useMediaTypeMapping()

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
  searchSource,
  loading,
  genreOptions,
  platformOptions,
  personOptions,
  yearOptions,
  studioOptions,
  containerOptions,
  contentRatingOptions,
  performSearch,
  navigateToResult,
  filterGenreOptions,
  filterPersonOptions,
  filterStudioOptions,
} = useSearchAPI(router)

// Trigger a search whenever the URL query changes (initial fire on mount).
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
  () => FILTER_KEYS.filter((key) => isActiveFilterValue(filters.value[key])).length,
)

const mediaResultCount = computed(() => searchResults.value.length)
const listResultCount = computed(() => listResults.value.length)
const visibleResultCount = computed(() => (totalResults.value || mediaResultCount.value) + listResultCount.value)
const resultSummary = computed(() =>
  t('searchResultsPage.resultsFound', { count: visibleResultCount.value }),
)
const hasSearchContext = computed(() => Boolean(searchQuery.value || isBrowseMode.value))
const hasNoResults = computed(
  () => hasSearchContext.value && mediaResultCount.value === 0 && listResultCount.value === 0,
)
const resultsHeading = computed(() =>
  searchQuery.value
    ? t('searchResultsPage.forQuery', { query: searchQuery.value })
    : t('searchResultsPage.searchResults'),
)

// Group results by type into UI sections.
const sectionConfig = buildSectionConfig(t)
const resultSections = computed(() => {
  const groups = {}
  for (const result of searchResults.value) {
    const type = getMediaType(result)
    if (!groups[type]) groups[type] = []
    groups[type].push(result)
  }
  return SECTION_ORDER.filter((type) => groups[type]?.length > 0).map((type) => {
    const cfg = sectionConfig[type] || { icon: 'mdi-help', color: 'grey', label: type }
    return {
      type,
      icon: cfg.icon,
      color: cfg.color,
      label: cfg.label,
      items: groups[type],
    }
  })
})
</script>

<style lang="scss" scoped>
.search-results-page {
  min-height: 100%;
}

.search-results-container {
  max-width: 1440px;
  margin: 0 auto;
}

.search-page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  margin-bottom: 14px;
}

.search-page-header__title {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.search-page-header__copy {
  min-width: 0;
}

.search-page-header__subtitle {
  margin-top: 4px;
  color: rgba(255, 255, 255, 0.66);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.search-page-header__meta,
.results-overview__counts {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.search-content {
  min-width: 0;
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

.results-overview {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
  padding: 12px 2px;
}

@media (max-width: 720px) {
  .search-results-page {
    padding: 12px;
  }

  .search-page-header,
  .results-overview {
    align-items: flex-start;
    flex-direction: column;
  }

  .search-page-header__meta,
  .results-overview,
  .results-overview__counts {
    justify-content: flex-start;
  }
}
</style>
