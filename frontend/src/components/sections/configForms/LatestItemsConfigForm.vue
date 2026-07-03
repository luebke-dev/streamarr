<template>
  <q-select
    v-model="config.media_type"
    :label="$t('pageLayouts.mediaType')"
    :options="options.mediaTypeOptions"
    emit-value
    map-options
    outlined
    dense
    clearable
  />
  <q-input
    v-model.number="config.max_items"
    :label="$t('pageLayouts.maxItems')"
    type="number"
    outlined
    dense
    :min="1"
    :max="100"
  />
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  config: {
    type: Object,
    required: true,
  },
  options: {
    type: Object,
    required: true,
  },
})

const config = computed(() => props.config)
</script>
