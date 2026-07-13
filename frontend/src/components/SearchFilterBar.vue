<template>
  <div class="search-filter-bar">
    <div v-if="activeFilterChips.length" class="active-filter-strip">
      <q-chip
        v-for="chip in activeFilterChips"
        :key="chip.id"
        removable
        dense
        square
        color="primary"
        text-color="white"
        @remove="removeFilterChip(chip)"
      >
        {{ chip.label }}
      </q-chip>
      <q-btn
        flat
        dense
        round
        class="active-filter-clear"
        icon="mdi-filter-remove"
        @click="clearFilters"
      >
        <q-tooltip>{{ $t('searchResultsPage.clearAll') }}</q-tooltip>
      </q-btn>
    </div>

    <q-slide-transition>
      <div v-show="expanded" class="filter-panel">
        <div class="filter-grid">
          <q-select
            class="filter-control filter-control--wide"
            :model-value="listValue('genre_ids', 'genre_id')"
            :options="genreOptions"
            :label="$t('searchResultsPage.filterGenres')"
            emit-value
            map-options
            multiple
            use-chips
            dense
            outlined
            clearable
            use-input
            input-debounce="200"
            @filter="onGenreFilter"
            @update:model-value="(v) => emitListField('genre_ids', v, 'genre_id')"
          >
            <template v-slot:no-option>
              <q-item>
                <q-item-section class="text-grey">{{
                  $t('searchResultsPage.noGenresFound')
                }}</q-item-section>
              </q-item>
            </template>
          </q-select>
          <q-select
            class="filter-control"
            :model-value="listValue('platform_ids', 'platform_id')"
            :options="platformOptions"
            :label="$t('searchResultsPage.filterPlatforms')"
            emit-value
            map-options
            multiple
            use-chips
            dense
            outlined
            clearable
            @update:model-value="(v) => emitListField('platform_ids', v, 'platform_id')"
          />
          <q-select
            class="filter-control"
            :model-value="modelValue.availability"
            :options="availabilityOptions"
            :label="$t('searchResultsPage.filterAvailability')"
            emit-value
            map-options
            dense
            outlined
            clearable
            @update:model-value="(v) => emitField('availability', v)"
          />
          <div class="filter-range">
            <q-input
              :model-value="modelValue.year_from"
              :label="$t('searchResultsPage.yearFrom')"
              type="number"
              dense
              outlined
              debounce="500"
              @update:model-value="(v) => emitField('year_from', v)"
            />
            <q-input
              :model-value="modelValue.year_to"
              :label="$t('searchResultsPage.yearTo')"
              type="number"
              dense
              outlined
              debounce="500"
              @update:model-value="(v) => emitField('year_to', v)"
            />
          </div>
        </div>

        <q-expansion-item
          v-model="detailsOpen"
          dense
          expand-separator
          icon="mdi-filter-plus"
          :label="$t('searchResultsPage.advancedFilters')"
          class="advanced-filters q-mt-sm"
        >
          <div class="filter-grid q-pt-sm">
            <q-select
              class="filter-control"
              :model-value="modelValue.studio_name"
              :options="studioOptions"
              :label="$t('searchResultsPage.filterStudio')"
              emit-value
              map-options
              dense
              outlined
              clearable
              use-input
              input-debounce="200"
              @filter="onStudioFilter"
              @update:model-value="(v) => emitField('studio_name', v)"
            >
              <template v-slot:no-option>
                <q-item>
                  <q-item-section class="text-grey">{{
                    $t('searchResultsPage.noStudiosFound')
                  }}</q-item-section>
                </q-item>
              </template>
            </q-select>
            <q-select
              class="filter-control"
              :model-value="modelValue.person_guid"
              :options="personOptions"
              :label="$t('searchResultsPage.filterPerson')"
              emit-value
              map-options
              dense
              outlined
              clearable
              use-input
              input-debounce="200"
              @filter="onPersonFilter"
              @update:model-value="(v) => emitField('person_guid', v)"
            >
              <template v-slot:no-option>
                <q-item>
                  <q-item-section class="text-grey">{{
                    $t('searchResultsPage.noPersonsFound')
                  }}</q-item-section>
                </q-item>
              </template>
            </q-select>
            <q-select
              class="filter-control"
              :model-value="modelValue.container"
              :options="containerOptions"
              :label="$t('searchResultsPage.filterContainer')"
              emit-value
              map-options
              dense
              outlined
              clearable
              @update:model-value="(v) => emitField('container', v)"
            />
            <q-select
              class="filter-control"
              :model-value="modelValue.content_rating"
              :options="contentRatingOptions"
              :label="$t('searchResultsPage.filterRating')"
              emit-value
              map-options
              dense
              outlined
              clearable
              @update:model-value="(v) => emitField('content_rating', v)"
            >
              <template v-slot:no-option>
                <q-item>
                  <q-item-section class="text-grey">{{
                    $t('searchResultsPage.noRatingsFound')
                  }}</q-item-section>
                </q-item>
              </template>
            </q-select>
            <q-select
              class="filter-control"
              :model-value="modelValue.has_poster"
              :options="posterOptions"
              :label="$t('searchResultsPage.filterPoster')"
              emit-value
              map-options
              dense
              outlined
              clearable
              @update:model-value="(v) => emitField('has_poster', v)"
            />
            <q-select
              class="filter-control"
              :model-value="modelValue.has_backdrop"
              :options="backdropOptions"
              :label="$t('searchResultsPage.filterBackdrop')"
              emit-value
              map-options
              dense
              outlined
              clearable
              @update:model-value="(v) => emitField('has_backdrop', v)"
            />
            <q-select
              class="filter-control"
              :model-value="modelValue.has_description"
              :options="descriptionOptions"
              :label="$t('searchResultsPage.filterDescription')"
              emit-value
              map-options
              dense
              outlined
              clearable
              @update:model-value="(v) => emitField('has_description', v)"
            />
            <q-select
              class="filter-control"
              :model-value="modelValue.is_favorite"
              :options="favoriteOptions"
              :label="$t('searchResultsPage.filterFavorite')"
              emit-value
              map-options
              dense
              outlined
              clearable
              @update:model-value="(v) => emitField('is_favorite', v)"
            />
            <q-select
              class="filter-control"
              :model-value="modelValue.is_played"
              :options="playedOptions"
              :label="$t('searchResultsPage.filterPlayed')"
              emit-value
              map-options
              dense
              outlined
              clearable
              @update:model-value="(v) => emitField('is_played', v)"
            />
            <q-select
              class="filter-control filter-control--wide"
              :model-value="modelValue.years"
              :options="yearOptions"
              :label="$t('searchResultsPage.filterYears')"
              emit-value
              map-options
              multiple
              use-chips
              dense
              outlined
              clearable
              @update:model-value="(v) => emitListField('years', v)"
            />
          </div>
        </q-expansion-item>

        <q-expansion-item
          v-model="exclusionsOpen"
          dense
          expand-separator
          icon="mdi-filter-minus"
          :label="$t('searchResultsPage.excludeFilters')"
          class="advanced-filters q-mt-sm"
        >
          <div class="filter-grid q-pt-sm">
            <q-select
              class="filter-control filter-control--wide"
              :model-value="modelValue.exclude_genre_ids"
              :options="genreOptions"
              :label="$t('searchResultsPage.filterExcludeGenres')"
              emit-value
              map-options
              multiple
              use-chips
              dense
              outlined
              clearable
              use-input
              input-debounce="200"
              @filter="onGenreFilter"
              @update:model-value="(v) => emitListField('exclude_genre_ids', v)"
            >
              <template v-slot:no-option>
                <q-item>
                  <q-item-section class="text-grey">{{
                    $t('searchResultsPage.noGenresFound')
                  }}</q-item-section>
                </q-item>
              </template>
            </q-select>
            <q-select
              class="filter-control filter-control--wide"
              :model-value="modelValue.exclude_platform_ids"
              :options="platformOptions"
              :label="$t('searchResultsPage.filterExcludePlatforms')"
              emit-value
              map-options
              multiple
              use-chips
              dense
              outlined
              clearable
              @update:model-value="(v) => emitListField('exclude_platform_ids', v)"
            />
            <q-select
              class="filter-control"
              :model-value="modelValue.exclude_person_guid"
              :options="personOptions"
              :label="$t('searchResultsPage.filterExcludePerson')"
              emit-value
              map-options
              dense
              outlined
              clearable
              use-input
              input-debounce="200"
              @filter="onPersonFilter"
              @update:model-value="(v) => emitField('exclude_person_guid', v)"
            >
              <template v-slot:no-option>
                <q-item>
                  <q-item-section class="text-grey">{{
                    $t('searchResultsPage.noPersonsFound')
                  }}</q-item-section>
                </q-item>
              </template>
            </q-select>
            <q-select
              class="filter-control"
              :model-value="modelValue.exclude_containers"
              :options="containerOptions"
              :label="$t('searchResultsPage.filterExcludeContainers')"
              emit-value
              map-options
              multiple
              use-chips
              dense
              outlined
              clearable
              @update:model-value="(v) => emitListField('exclude_containers', v)"
            />
            <q-select
              class="filter-control"
              :model-value="modelValue.exclude_content_ratings"
              :options="contentRatingOptions"
              :label="$t('searchResultsPage.filterExcludeRatings')"
              emit-value
              map-options
              multiple
              use-chips
              dense
              outlined
              clearable
              @update:model-value="(v) => emitListField('exclude_content_ratings', v)"
            >
              <template v-slot:no-option>
                <q-item>
                  <q-item-section class="text-grey">{{
                    $t('searchResultsPage.noRatingsFound')
                  }}</q-item-section>
                </q-item>
              </template>
            </q-select>
            <q-select
              class="filter-control"
              :model-value="modelValue.exclude_years"
              :options="yearOptions"
              :label="$t('searchResultsPage.filterExcludeYears')"
              emit-value
              map-options
              multiple
              use-chips
              dense
              outlined
              clearable
              @update:model-value="(v) => emitListField('exclude_years', v)"
            />
          </div>
        </q-expansion-item>
      </div>
    </q-slide-transition>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  buildAvailabilityOptions,
  buildPosterOptions,
  buildBackdropOptions,
  buildDescriptionOptions,
  buildFavoriteOptions,
  buildPlayedOptions,
  PANEL_FILTER_KEYS,
} from 'src/utils/searchOptions'

const props = defineProps({
  /**
   * Object with current filter values. Keys are defined by FILTER_KEYS in
   * src/utils/searchOptions.js.
   */
  modelValue: {
    type: Object,
    required: true,
  },
  /** Whether the filter panel is open. The active-filter chips stay visible either way. */
  expanded: { type: Boolean, default: false },
  genreOptions: { type: Array, default: () => [] },
  platformOptions: { type: Array, default: () => [] },
  personOptions: { type: Array, default: () => [] },
  yearOptions: { type: Array, default: () => [] },
  studioOptions: { type: Array, default: () => [] },
  containerOptions: { type: Array, default: () => [] },
  contentRatingOptions: { type: Array, default: () => [] },
})

const emit = defineEmits(['update:modelValue', 'genre-filter', 'person-filter', 'studio-filter'])

const { t } = useI18n()
const availabilityOptions = buildAvailabilityOptions(t)
const posterOptions = buildPosterOptions(t)
const backdropOptions = buildBackdropOptions(t)
const descriptionOptions = buildDescriptionOptions(t)
const favoriteOptions = buildFavoriteOptions(t)
const playedOptions = buildPlayedOptions(t)
const detailsOpen = ref(false)
const exclusionsOpen = ref(false)

const ARRAY_FILTER_KEYS = new Set([
  'genre_ids',
  'exclude_genre_ids',
  'platform_ids',
  'exclude_platform_ids',
  'years',
  'exclude_years',
  'genres',
  'exclude_genres',
  'exclude_containers',
  'exclude_content_ratings',
])

const activeFilterChips = computed(() => {
  const chips = []
  for (const key of PANEL_FILTER_KEYS) {
    const value = props.modelValue[key]
    if (isEmptyValue(value)) continue
    const values = Array.isArray(value) ? value : [value]
    for (const item of values) {
      chips.push({
        id: `${key}:${item}`,
        key,
        value: item,
        label: `${filterLabel(key)}: ${valueLabel(key, item)}`,
      })
    }
  }
  return chips
})

function emitField(key, value) {
  emit('update:modelValue', { ...props.modelValue, [key]: value })
}

function listValue(key, fallbackKey) {
  const value = props.modelValue[key]
  if (Array.isArray(value) && value.length > 0) return value
  if (value != null && value !== '') return [value]
  const fallback = props.modelValue[fallbackKey]
  return fallback != null && fallback !== '' ? [fallback] : []
}

function emitListField(key, value, fallbackKey) {
  const values = Array.isArray(value) ? value : value == null ? [] : [value]
  const next = { ...props.modelValue, [key]: values }
  if (fallbackKey) next[fallbackKey] = null
  emit('update:modelValue', next)
}

function isEmptyValue(value) {
  return value == null || value === '' || (Array.isArray(value) && value.length === 0)
}

function optionLabel(options, value) {
  const match = options.find((option) => String(option.value) === String(value))
  return match?.label || String(value)
}

function optionsForKey(key) {
  const map = {
    genre_id: props.genreOptions,
    genre_ids: props.genreOptions,
    exclude_genre_ids: props.genreOptions,
    platform_id: props.platformOptions,
    platform_ids: props.platformOptions,
    exclude_platform_ids: props.platformOptions,
    availability: availabilityOptions,
    person_guid: props.personOptions,
    exclude_person_guid: props.personOptions,
    studio_name: props.studioOptions,
    container: props.containerOptions,
    exclude_containers: props.containerOptions,
    content_rating: props.contentRatingOptions,
    exclude_content_ratings: props.contentRatingOptions,
    years: props.yearOptions,
    exclude_years: props.yearOptions,
    has_poster: posterOptions,
    has_backdrop: backdropOptions,
    has_description: descriptionOptions,
    is_favorite: favoriteOptions,
    is_played: playedOptions,
  }
  return map[key] || []
}

function filterLabel(key) {
  const map = {
    genre_id: t('searchResultsPage.filterGenre'),
    genre_ids: t('searchResultsPage.filterGenres'),
    exclude_genre_ids: t('searchResultsPage.filterExcludeGenres'),
    platform_id: t('searchResultsPage.filterPlatform'),
    platform_ids: t('searchResultsPage.filterPlatforms'),
    exclude_platform_ids: t('searchResultsPage.filterExcludePlatforms'),
    availability: t('searchResultsPage.filterAvailability'),
    has_poster: t('searchResultsPage.filterPoster'),
    has_backdrop: t('searchResultsPage.filterBackdrop'),
    has_description: t('searchResultsPage.filterDescription'),
    is_favorite: t('searchResultsPage.filterFavorite'),
    is_played: t('searchResultsPage.filterPlayed'),
    person_guid: t('searchResultsPage.filterPerson'),
    exclude_person_guid: t('searchResultsPage.filterExcludePerson'),
    studio_name: t('searchResultsPage.filterStudio'),
    container: t('searchResultsPage.filterContainer'),
    exclude_containers: t('searchResultsPage.filterExcludeContainers'),
    content_rating: t('searchResultsPage.filterRating'),
    exclude_content_ratings: t('searchResultsPage.filterExcludeRatings'),
    years: t('searchResultsPage.filterYears'),
    exclude_years: t('searchResultsPage.filterExcludeYears'),
    year_from: t('searchResultsPage.yearFrom'),
    year_to: t('searchResultsPage.yearTo'),
  }
  return map[key] || key
}

function valueLabel(key, value) {
  return optionLabel(optionsForKey(key), value)
}

function removeFilterChip(chip) {
  const current = props.modelValue[chip.key]
  if (Array.isArray(current)) {
    emitField(
      chip.key,
      current.filter((item) => String(item) !== String(chip.value)),
    )
    return
  }
  emitField(chip.key, null)
}

function clearFilters() {
  const next = { ...props.modelValue }
  for (const key of PANEL_FILTER_KEYS) next[key] = ARRAY_FILTER_KEYS.has(key) ? [] : null
  emit('update:modelValue', next)
}

function onGenreFilter(val, update) {
  emit('genre-filter', val, update)
}

function onPersonFilter(val, update) {
  emit('person-filter', val, update)
}

function onStudioFilter(val, update) {
  emit('studio-filter', val, update)
}
</script>

<style lang="scss" scoped>
.search-filter-bar {
  min-width: 0;
}

.active-filter-strip {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}

.active-filter-clear {
  flex: 0 0 auto;
}

.filter-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(172px, 1fr));
  gap: 10px 12px;
  min-width: 0;
}

.filter-control {
  min-width: 0;
}

.filter-control--wide,
.filter-range {
  grid-column: span 2;
}

.filter-range {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.advanced-filters {
  margin-top: 10px;
  border-top: 1px solid rgba(255, 255, 255, 0.08);

  :deep(.q-item) {
    min-height: 42px;
    padding-left: 0;
    padding-right: 0;
    color: rgba(255, 255, 255, 0.78);
  }
}

:deep(.q-field__control) {
  background: rgba(255, 255, 255, 0.04);
}

:deep(.q-chip) {
  max-width: 100%;
}

:deep(.q-chip__content) {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (max-width: 760px) {
  .filter-control--wide,
  .filter-range {
    grid-column: 1 / -1;
  }
}

@media (max-width: 480px) {
  .filter-grid,
  .filter-range {
    grid-template-columns: 1fr;
  }
}
</style>
