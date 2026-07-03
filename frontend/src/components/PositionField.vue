<template>
  <div class="position-field">
    <q-select
      outlined dark dense
      :model-value="modeOf(modelValue)"
      :options="modeOptions"
      emit-value map-options
      :label="label"
      :disable="disable"
      @update:model-value="onModeChange"
    />
    <q-input
      v-if="modeOf(modelValue) === 'pixels'"
      outlined dark dense type="number" class="q-mt-xs"
      :model-value="typeof modelValue === 'number' ? modelValue : 0"
      :label="$t('overlayElements.fields.pixelOffset')"
      :hint="$t('overlayElements.fields.pixelHint')"
      :disable="disable"
      @update:model-value="(v) => $emit('update:modelValue', toInt(v))"
    />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const props = defineProps({
  modelValue: { type: [String, Number, null], default: null },
  label: { type: String, default: '' },
  axis: { type: String, default: 'x' }, // "x" | "y"
  disable: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue'])

const { t } = useI18n()

const modeOptions = computed(() => {
  const isX = props.axis === 'x'
  return [
    {
      label: isX ? t('overlayElements.anchorLeft') : t('overlayElements.anchorTop'),
      value: isX ? 'left' : 'top',
    },
    { label: t('overlayElements.anchorCenter'), value: 'center' },
    {
      label: isX ? t('overlayElements.anchorRight') : t('overlayElements.anchorBottom'),
      value: isX ? 'right' : 'bottom',
    },
    { label: t('overlayElements.anchorPixels'), value: 'pixels' },
  ]
})

function modeOf(value) {
  if (typeof value === 'number') return 'pixels'
  if (typeof value === 'string' && value) return value
  // default: top-left
  return props.axis === 'x' ? 'left' : 'top'
}

function onModeChange(mode) {
  if (mode === 'pixels') {
    emit('update:modelValue', typeof props.modelValue === 'number' ? props.modelValue : 0)
  } else {
    emit('update:modelValue', mode)
  }
}

function toInt(v) {
  if (v === null || v === undefined || v === '') return 0
  const n = Number(v)
  return Number.isFinite(n) ? Math.trunc(n) : 0
}
</script>
