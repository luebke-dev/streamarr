<template>
  <div>
    <q-select
      :model-value="modelValue"
      :options="options"
      :label="label"
      option-value="value"
      option-label="label"
      emit-value
      map-options
      multiple
      :outlined="outlined"
      :dense="dense"
      :loading="loading"
      @update:model-value="onUpdate"
    >
      <template v-if="prependIcon" #prepend>
        <q-icon :name="prependIcon" />
      </template>
      <template #selected-item="scope">
        <q-chip dense removable @remove="removeItem(scope.opt.value)" class="q-ma-xs">
          {{ scope.opt.flag }} {{ scope.opt.label }}
        </q-chip>
      </template>
      <template #option="scope">
        <q-item v-bind="scope.itemProps">
          <q-item-section avatar>
            <span class="text-h6">{{ scope.opt.flag }}</span>
          </q-item-section>
          <q-item-section>
            <q-item-label>{{ scope.opt.label }}</q-item-label>
          </q-item-section>
        </q-item>
      </template>
    </q-select>

    <div v-if="hint" class="text-caption text-grey q-mt-xs">{{ hint }}</div>

    <!-- Priority reorder list -->
    <q-list v-if="modelValue && modelValue.length > 1" dense class="q-mt-sm">
      <q-item v-for="(lang, index) in modelValue" :key="lang" dense class="q-pa-none">
        <q-item-section avatar style="min-width: 28px">
          <q-badge color="primary" :label="index + 1" />
        </q-item-section>
        <q-item-section>{{ getLabel(lang) }}</q-item-section>
        <q-item-section side>
          <div class="row no-wrap">
            <q-btn
              flat
              dense
              round
              icon="mdi-arrow-up"
              size="sm"
              :disable="index === 0"
              @click="move(index, -1)"
            />
            <q-btn
              flat
              dense
              round
              icon="mdi-arrow-down"
              size="sm"
              :disable="index === modelValue.length - 1"
              @click="move(index, 1)"
            />
          </div>
        </q-item-section>
      </q-item>
    </q-list>
  </div>
</template>

<script setup>
import { MEDIA_LANGUAGES, getMediaLanguageLabel } from 'src/utils/mediaLanguages'

const props = defineProps({
  modelValue: { type: Array, default: () => [] },
  options: { type: Array, default: () => MEDIA_LANGUAGES },
  label: { type: String, default: '' },
  hint: { type: String, default: '' },
  prependIcon: { type: String, default: '' },
  loading: { type: Boolean, default: false },
  dense: { type: Boolean, default: true },
  outlined: { type: Boolean, default: true },
})

const emit = defineEmits(['update:modelValue', 'change'])

function emitUpdate(value) {
  emit('update:modelValue', value)
  emit('change', value)
}

function onUpdate(value) {
  emitUpdate(value)
}

function removeItem(code) {
  emitUpdate(props.modelValue.filter((l) => l !== code))
}

function move(index, direction) {
  const arr = [...props.modelValue]
  const newIndex = index + direction
  if (newIndex < 0 || newIndex >= arr.length) return
  ;[arr[index], arr[newIndex]] = [arr[newIndex], arr[index]]
  emitUpdate(arr)
}

function getLabel(code) {
  const opt = props.options.find((o) => o.value === code)
  return opt ? `${opt.flag} ${opt.label}` : getMediaLanguageLabel(code)
}
</script>
