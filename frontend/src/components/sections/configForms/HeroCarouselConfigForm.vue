<template>
  <q-select
    v-model="config.source_type"
    :label="$t('pageLayouts.sourceType')"
    :options="options.carouselSourceOptions"
    emit-value
    map-options
    outlined
    dense
  />
  <template v-if="config.source_type === 'list'">
    <q-select
      v-model="config.list_guid"
      :label="$t('pageLayouts.list')"
      :options="listOptions"
      emit-value
      map-options
      outlined
      dense
      clearable
    />
    <q-input
      v-model="config.list_update_source"
      :label="options.labels.listUpdateSource"
      outlined
      dense
      clearable
      :hint="options.labels.listUpdateSourceHint"
    />
  </template>
  <template v-if="config.source_type === 'dynamic_search'">
    <div class="text-subtitle2 q-mb-xs">{{ $t('pageLayouts.filters') }}</div>
    <MediaFiltersForm
      :filters="config.filters"
      :options="options"
      :genre-options="genreOptions"
      :platform-options="platformOptions"
      mode="search"
      @update:filters="config.filters = $event"
    />
  </template>
</template>

<script setup>
import { computed } from 'vue'
import MediaFiltersForm from './MediaFiltersForm.vue'

const props = defineProps({
  config: {
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
  listOptions: {
    type: Array,
    default: () => [],
  },
  platformOptions: {
    type: Array,
    default: () => [],
  },
})

const config = computed(() => props.config)
</script>
