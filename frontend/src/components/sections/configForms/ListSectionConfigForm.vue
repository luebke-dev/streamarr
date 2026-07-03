<template>
  <q-expansion-item
    :label="$t('pageLayouts.filters')"
    icon="mdi-filter"
    dense
    header-class="text-grey-4"
  >
    <MediaFiltersForm
      :filters="config.filters"
      :options="options"
      :platform-options="platformOptions"
      mode="availability"
      class="q-pa-sm"
      @update:filters="config.filters = $event"
    />
  </q-expansion-item>
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
  <q-input
    v-model="config.list_update_source_prefix"
    :label="options.labels.listUpdateSourcePrefix"
    outlined
    dense
    clearable
    :hint="options.labels.listUpdateSourcePrefixHint"
  />
  <q-input
    v-model.number="config.max_rows"
    :label="options.labels.maxRows"
    type="number"
    outlined
    dense
    :min="1"
    :max="10"
  />
  <q-input
    v-model.number="config.max_items"
    :label="$t('pageLayouts.maxItems')"
    type="number"
    outlined
    dense
    :min="1"
    :max="50"
  />
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
