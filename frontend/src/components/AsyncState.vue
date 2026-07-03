<template>
  <div v-if="loading">
    <slot name="loading">
      <div class="flex flex-center q-pa-xl">
        <q-spinner-dots :size="spinnerSize" :color="spinnerColor" />
      </div>
    </slot>
  </div>
  <div v-else-if="error">
    <slot name="error" :error="error" :retry="retry">
      <q-banner class="bg-negative text-white q-my-md" rounded>
        <template v-slot:avatar>
          <q-icon name="mdi-alert-circle" />
        </template>
        {{ errorMessage }}
        <template v-if="retry" v-slot:action>
          <q-btn flat :label="retryLabel" @click="retry" />
        </template>
      </q-banner>
    </slot>
  </div>
  <div v-else-if="empty">
    <slot name="empty">
      <div class="text-center text-grey-5 q-pa-xl">
        {{ emptyMessage }}
      </div>
    </slot>
  </div>
  <slot v-else />
</template>

<script setup>
/**
 * Unified async state wrapper. Shows loading/error/empty/content depending
 * on props. Intended to pair with `useAsyncResource`.
 *
 * Slots:
 *  - default: rendered when not loading, no error, not empty
 *  - loading: override default spinner
 *  - error:   override default error banner. Receives `{ error, retry }`.
 *  - empty:   override default empty state
 */
import { computed } from 'vue'

const props = defineProps({
  loading: { type: Boolean, default: false },
  error: { type: [Object, Error, String, null], default: null },
  empty: { type: Boolean, default: false },
  emptyMessage: { type: String, default: 'No data' },
  retry: { type: Function, default: null },
  retryLabel: { type: String, default: 'Retry' },
  spinnerSize: { type: String, default: '50px' },
  spinnerColor: { type: String, default: 'primary' },
  errorFallback: { type: String, default: 'An error occurred' },
})

const errorMessage = computed(() => {
  const e = props.error
  if (!e) return props.errorFallback
  if (typeof e === 'string') return e
  return e?.response?.data?.detail || e?.message || props.errorFallback
})
</script>
