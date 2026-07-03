<template>
  <div>
    <PasswordField
      :model-value="modelValue"
      :label="passwordLabel"
      :dark="dark"
      :dense="dense"
      :rules="passwordRules"
      @update:model-value="$emit('update:modelValue', $event)"
    />
    <PasswordField
      :model-value="confirm"
      :label="confirmLabel"
      :dark="dark"
      :dense="dense"
      :rules="confirmRules"
      @update:model-value="$emit('update:confirm', $event)"
    />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import PasswordField from './PasswordField.vue'

const props = defineProps({
  modelValue: { type: String, default: '' },
  confirm: { type: String, default: '' },
  passwordLabel: { type: String, required: true },
  confirmLabel: { type: String, required: true },
  minLength: { type: Number, default: 8 },
  requireComplexity: { type: Boolean, default: false },
  dark: { type: Boolean, default: true },
  dense: { type: Boolean, default: false },
  messages: {
    type: Object,
    required: true,
    // { required, minLength, complexity, confirmRequired, mismatch }
  },
})

defineEmits(['update:modelValue', 'update:confirm'])

const passwordRules = computed(() => {
  const rules = [
    (val) => !!val || props.messages.required,
    (val) => val.length >= props.minLength || props.messages.minLength,
  ]
  if (props.requireComplexity) {
    rules.push((val) => /(?=.*[a-z])(?=.*[A-Z])(?=.*\d)/.test(val) || props.messages.complexity)
  }
  return rules
})

const confirmRules = computed(() => [
  (val) => !!val || (props.messages.confirmRequired ?? props.messages.required),
  (val) => val === props.modelValue || props.messages.mismatch,
])
</script>
