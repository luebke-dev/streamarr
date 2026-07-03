<template>
  <div class="media-error-state flex flex-center q-pa-xl">
    <div class="text-center">
      <q-icon :name="icon" size="4em" color="negative" />
      <div class="text-h6 text-negative q-mt-md">{{ message }}</div>
      <q-btn color="primary" :label="backLabel" @click="handleBack" class="q-mt-md" />
    </div>
  </div>
</template>

<script setup>
import { useRouter } from 'vue-router'

const props = defineProps({
  /**
   * Error message to display
   */
  message: {
    type: String,
    default: 'An error occurred',
  },
  /**
   * Icon to display
   */
  icon: {
    type: String,
    default: 'mdi-alert-circle',
  },
  /**
   * Label for the back button
   */
  backLabel: {
    type: String,
    default: 'Go Back',
  },
  /**
   * Route to navigate to when clicking back button
   */
  backRoute: {
    type: String,
    default: null,
  },
})

const emit = defineEmits(['back'])
const router = useRouter()

function handleBack() {
  if (props.backRoute) {
    router.push(props.backRoute)
  } else {
    emit('back')
  }
}
</script>

<style lang="scss" scoped>
.media-error-state {
  min-height: 60vh;

  .q-icon {
    margin-bottom: 16px;
    opacity: 0.8;
  }
}
</style>
