<template>
  <template v-if="sectionType === 'genre'">
    <q-select
      v-model="config.genre_id"
      :label="$t('pageLayouts.genre')"
      :options="genreOptions"
      emit-value
      map-options
      outlined
      dense
      :rules="[(val) => !!val || $t('validation.required')]"
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
  <q-input
    v-else
    v-model.number="config.max_items_per_genre"
    :label="$t('pageLayouts.maxItemsPerGenre')"
    type="number"
    outlined
    dense
    :min="1"
    :max="50"
  />
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
</template>

<script setup>
import { computed } from 'vue'
import MediaFiltersForm from './MediaFiltersForm.vue'

const props = defineProps({
  sectionType: {
    type: String,
    required: true,
  },
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
  platformOptions: {
    type: Array,
    default: () => [],
  },
})

const config = computed(() => props.config)
</script>
