<template>
  <div class="q-gutter-md">
    <q-select
      v-if="showMediaType"
      v-model="filtersModel.media_type"
      :label="$t('pageLayouts.mediaType')"
      :options="options.mediaTypeOptions"
      emit-value
      map-options
      outlined
      dense
      clearable
    />
    <q-select
      v-if="showGenre"
      v-model="filtersModel.genre_id"
      :label="$t('pageLayouts.genre')"
      :options="genreOptions"
      emit-value
      map-options
      outlined
      dense
      clearable
    />
    <q-select
      v-if="showPlatform"
      v-model="filtersModel.platform_id"
      :label="$t('pageLayouts.platform')"
      :options="platformOptions"
      emit-value
      map-options
      outlined
      dense
      clearable
    />
    <div v-if="showAvailability || showPoster" class="row q-col-gutter-sm">
      <div v-if="showAvailability" class="col-6">
        <q-select
          v-model="filtersModel.availability"
          :label="$t('pageLayouts.availabilityLabel')"
          :options="options.availabilityOptions"
          emit-value
          map-options
          outlined
          dense
          clearable
        />
      </div>
      <div v-if="showPoster" class="col-6">
        <q-select
          v-model="filtersModel.has_poster"
          :label="$t('pageLayouts.hasPoster')"
          :options="options.booleanOptions"
          emit-value
          map-options
          outlined
          dense
          clearable
        />
      </div>
    </div>
    <div v-if="showBackdrop || showDescription" class="row q-col-gutter-sm">
      <div v-if="showBackdrop" class="col-6">
        <q-select
          v-model="filtersModel.has_backdrop"
          :label="options.labels.hasBackdrop"
          :options="options.booleanOptions"
          emit-value
          map-options
          outlined
          dense
          clearable
        />
      </div>
      <div v-if="showDescription" class="col-6">
        <q-select
          v-model="filtersModel.has_description"
          :label="$t('pageLayouts.hasDescription')"
          :options="options.booleanOptions"
          emit-value
          map-options
          outlined
          dense
          clearable
        />
      </div>
    </div>
    <div v-if="showUserStates" class="row q-col-gutter-sm">
      <div class="col-6">
        <q-select
          v-model="filtersModel.is_favorite"
          :label="options.labels.favoriteState"
          :options="options.favoriteStateOptions"
          emit-value
          map-options
          outlined
          dense
          clearable
        />
      </div>
      <div class="col-6">
        <q-select
          v-model="filtersModel.is_played"
          :label="options.labels.playedState"
          :options="options.playedStateOptions"
          emit-value
          map-options
          outlined
          dense
          clearable
        />
      </div>
    </div>
    <div v-if="showMetadata" class="row q-col-gutter-sm">
      <div class="col-4">
        <q-input
          v-model="filtersModel.studio_name"
          :label="options.labels.studio"
          outlined
          dense
          clearable
        />
      </div>
      <div class="col-4">
        <q-input
          v-model="filtersModel.container"
          :label="options.labels.container"
          outlined
          dense
          clearable
        />
      </div>
      <div class="col-4">
        <q-input
          v-model="filtersModel.content_rating"
          :label="options.labels.contentRating"
          outlined
          dense
          clearable
        />
      </div>
    </div>
    <div v-if="showYear" class="row q-col-gutter-sm">
      <div class="col-6">
        <q-input
          v-model.number="filtersModel.year_from"
          :label="$t('pageLayouts.yearFrom')"
          type="number"
          outlined
          dense
        />
      </div>
      <div class="col-6">
        <q-input
          v-model.number="filtersModel.year_to"
          :label="$t('pageLayouts.yearTo')"
          type="number"
          outlined
          dense
        />
      </div>
    </div>
    <div v-if="showSort" class="row q-col-gutter-sm">
      <div class="col-6">
        <q-select
          v-model="filtersModel.sort_by"
          :label="$t('pageLayouts.sortBy')"
          :options="options.sortByOptions"
          emit-value
          map-options
          outlined
          dense
          clearable
        />
      </div>
      <div class="col-6">
        <q-select
          v-model="filtersModel.sort_order"
          :label="$t('pageLayouts.sortOrder')"
          :options="options.sortOrderOptions"
          emit-value
          map-options
          outlined
          dense
        />
      </div>
    </div>
    <q-input
      v-if="showQuery"
      v-model="filtersModel.query"
      :label="$t('pageLayouts.searchQuery')"
      outlined
      dense
      clearable
    />
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'

const props = defineProps({
  filters: {
    type: Object,
    required: true,
  },
  options: {
    type: Object,
    required: true,
  },
  genreOptions: {
    type: Array,
    default: () => [],
  },
  platformOptions: {
    type: Array,
    default: () => [],
  },
  mode: {
    type: String,
    default: 'full',
  },
})

const emit = defineEmits(['update:filters'])
const filtersModel = ref({})

watch(
  () => props.filters,
  (filters) => {
    filtersModel.value = { ...(filters || {}) }
  },
  { immediate: true, deep: true },
)

watch(
  filtersModel,
  (filters) => {
    emit('update:filters', { ...filters })
  },
  { deep: true },
)

const modeConfig = computed(() => {
  const modes = {
    full: {
      showMediaType: true,
      showGenre: true,
      showPlatform: true,
      showAvailability: true,
      showPoster: true,
      showBackdrop: true,
      showDescription: true,
      showUserStates: true,
      showMetadata: true,
      showYear: true,
      showSort: true,
      showQuery: true,
    },
    search: {
      showMediaType: true,
      showGenre: true,
      showPlatform: true,
      showAvailability: true,
      showPoster: true,
      showDescription: true,
      showYear: true,
      showSort: true,
      showQuery: true,
    },
    availability: {
      showPlatform: true,
      showAvailability: true,
      showPoster: true,
      showDescription: true,
    },
  }
  return modes[props.mode] || modes.full
})

const showMediaType = computed(() => Boolean(modeConfig.value.showMediaType))
const showGenre = computed(() => Boolean(modeConfig.value.showGenre))
const showPlatform = computed(() => Boolean(modeConfig.value.showPlatform))
const showAvailability = computed(() => Boolean(modeConfig.value.showAvailability))
const showPoster = computed(() => Boolean(modeConfig.value.showPoster))
const showBackdrop = computed(() => Boolean(modeConfig.value.showBackdrop))
const showDescription = computed(() => Boolean(modeConfig.value.showDescription))
const showUserStates = computed(() => Boolean(modeConfig.value.showUserStates))
const showMetadata = computed(() => Boolean(modeConfig.value.showMetadata))
const showYear = computed(() => Boolean(modeConfig.value.showYear))
const showSort = computed(() => Boolean(modeConfig.value.showSort))
const showQuery = computed(() => Boolean(modeConfig.value.showQuery))
</script>
