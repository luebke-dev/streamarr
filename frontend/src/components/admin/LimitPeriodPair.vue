<template>
  <div :class="['row q-col-gutter-md', rowClass]">
    <div class="col-8">
      <q-input
        :model-value="limit"
        :label="limitLabel"
        outlined
        dense
        type="number"
        min="0"
        clearable
        :hint="hint"
        @update:model-value="
          (v) => $emit('update:limit', v === null || v === '' ? null : Number(v))
        "
      />
    </div>
    <div class="col-4">
      <q-select
        :model-value="period"
        :options="periodOptions"
        :label="periodLabel"
        outlined
        dense
        emit-value
        map-options
        clearable
        @update:model-value="(v) => $emit('update:period', v)"
      />
    </div>
  </div>
</template>

<script setup>
defineProps({
  limit: { type: [Number, null], default: null },
  period: { type: [Number, null], default: null },
  limitLabel: { type: String, required: true },
  periodLabel: { type: String, required: true },
  hint: { type: String, default: '' },
  periodOptions: { type: Array, required: true },
  rowClass: { type: String, default: 'q-mt-sm' },
})

defineEmits(['update:limit', 'update:period'])
</script>
