<template>
  <transition name="skip-fade">
    <div
      v-if="visible"
      class="skip-overlay"
      @mouseenter="hovered = true"
      @mouseleave="hovered = false"
    >
      <q-btn
        :label="label"
        outline
        color="white"
        no-caps
        size="md"
        class="skip-btn"
        icon-right="mdi-skip-next"
        @click="$emit('skip')"
      />
    </div>
  </transition>
</template>

<script setup>
import { ref, watch, onBeforeUnmount } from 'vue'

const props = defineProps({
  visible: { type: Boolean, default: false },
  label: { type: String, default: 'Skip' },
  autoHideSeconds: { type: Number, default: 8 },
})

defineEmits(['skip'])

const hovered = ref(false)
let hideTimer = null

const resetHideTimer = () => {
  if (hideTimer) clearTimeout(hideTimer)
  if (!hovered.value && props.autoHideSeconds > 0) {
    hideTimer = setTimeout(() => {
      // Component stays visible via prop, but we could emit a hide event
      // For now the parent controls visibility via timeupdate
    }, props.autoHideSeconds * 1000)
  }
}

watch(
  () => props.visible,
  (val) => {
    if (val) resetHideTimer()
  },
)

onBeforeUnmount(() => {
  if (hideTimer) clearTimeout(hideTimer)
})
</script>

<style lang="scss" scoped>
.skip-overlay {
  position: absolute;
  bottom: 100px;
  right: 24px;
  z-index: 100;
}

.skip-btn {
  backdrop-filter: blur(8px);
  background: rgba(255, 255, 255, 0.1) !important;
  border: 1px solid rgba(255, 255, 255, 0.5);
}

.skip-fade-enter-active,
.skip-fade-leave-active {
  transition:
    opacity 0.3s ease,
    transform 0.3s ease;
}

.skip-fade-enter-from {
  opacity: 0;
  transform: translateX(20px);
}

.skip-fade-leave-to {
  opacity: 0;
  transform: translateX(20px);
}
</style>
