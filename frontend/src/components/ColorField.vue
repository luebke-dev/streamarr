<template>
  <q-input
    outlined dark dense
    :model-value="modelValue || ''"
    :label="label"
    :hint="hint"
    :disable="disable"
    :clearable="clearable"
    @update:model-value="(v) => $emit('update:modelValue', v || null)"
  >
    <template v-slot:prepend>
      <div
        class="color-swatch"
        :style="{ background: modelValue || 'transparent' }"
      />
    </template>
    <template v-slot:append>
      <q-icon name="mdi-palette" class="cursor-pointer">
        <q-popup-proxy
          cover transition-show="scale" transition-hide="scale"
          @before-show="onOpen"
        >
          <q-color
            :model-value="pickerValue"
            format-model="hexa"
            no-header-tabs
            class="bg-dark"
            @update:model-value="(v) => $emit('update:modelValue', v)"
          />
        </q-popup-proxy>
      </q-icon>
    </template>
  </q-input>
</template>

<script setup>
import { ref } from 'vue'

const props = defineProps({
  modelValue: { type: [String, null], default: null },
  label: { type: String, default: '' },
  hint: { type: String, default: '' },
  disable: { type: Boolean, default: false },
  clearable: { type: Boolean, default: false },
})
defineEmits(['update:modelValue'])

// Pre-fill the q-color picker with a sensible default when no value is
// set yet, so the swatch grid isn't blank on first open.
const pickerValue = ref('#ffffffff')
function onOpen() {
  pickerValue.value = props.modelValue || '#ffffffff'
}
</script>

<style scoped>
.color-swatch {
  width: 20px; height: 20px;
  border-radius: 3px;
  border: 1px solid rgba(255,255,255,0.3);
}
</style>
