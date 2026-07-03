<template>
  <div class="text-subtitle2 q-mb-xs">{{ $t('pageLayouts.filters') }}</div>
  <MediaFiltersForm
    :filters="config.filters"
    :options="options"
    :genre-options="genreOptions"
    :platform-options="platformOptions"
    mode="full"
    @update:filters="config.filters = $event"
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
