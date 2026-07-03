<template>
  <div :class="wrapperClass">
    <q-banner :class="bannerClass" rounded>
      <template v-if="resolvedIcon" #avatar>
        <q-icon :name="resolvedIcon" />
      </template>
      <slot>{{ message }}</slot>
      <template v-if="$slots.action" #action>
        <slot name="action" />
      </template>
    </q-banner>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  type: {
    type: String,
    default: 'error',
    validator: (v) => ['error', 'success', 'info', 'warning'].includes(v),
  },
  message: { type: String, default: '' },
  icon: { type: String, default: null },
  dense: { type: Boolean, default: false },
  noMargin: { type: Boolean, default: false },
})

const typeMap = {
  error: { bg: 'bg-negative text-white', icon: 'mdi-alert-circle' },
  success: { bg: 'bg-positive text-white', icon: 'mdi-check-circle' },
  info: { bg: 'bg-info text-white', icon: 'mdi-information' },
  warning: { bg: 'bg-warning text-dark', icon: 'mdi-alert' },
}

const bannerClass = computed(() => typeMap[props.type].bg)
const resolvedIcon = computed(() =>
  props.icon === '' ? null : props.icon || typeMap[props.type].icon,
)
const wrapperClass = computed(() => (props.noMargin ? '' : props.dense ? 'q-mb-sm' : 'q-mb-md'))
</script>
