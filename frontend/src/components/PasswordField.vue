<template>
  <q-input
    v-bind="$attrs"
    :model-value="modelValue"
    :type="visible ? 'text' : 'password'"
    :outlined="outlined"
    :dark="dark"
    @update:model-value="$emit('update:modelValue', $event)"
  >
    <template v-slot:append>
      <q-icon
        :name="visible ? 'mdi-eye-off' : 'mdi-eye'"
        class="cursor-pointer"
        @click="visible = !visible"
      />
    </template>
  </q-input>
</template>

<script setup>
import { ref } from 'vue'

defineProps({
  modelValue: {
    type: String,
    default: '',
  },
  outlined: {
    type: Boolean,
    default: true,
  },
  dark: {
    type: Boolean,
    default: true,
  },
})

defineEmits(['update:modelValue'])

const visible = ref(false)
</script>
