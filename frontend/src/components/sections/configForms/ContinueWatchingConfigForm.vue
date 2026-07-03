<template>
  <q-select
    v-model="config.content_type"
    :label="$t('pageLayouts.contentType')"
    :options="options.contentTypeOptions"
    emit-value
    map-options
    outlined
    dense
    clearable
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
