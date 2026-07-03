<template>
  <div ref="sectionRef" class="section-renderer">
    <!-- Normal mode: only render enabled sections -->
    <template v-if="!editMode">
      <component
        :is="sectionComponent"
        v-if="section.is_enabled && sectionComponent && isVisible"
        :section="section"
        :media-type="mediaType"
        @navigate-to-item="$emit('navigate-to-item', $event)"
        @play-item="$emit('play-item', $event)"
      />
      <div
        v-else-if="section.is_enabled && sectionComponent && !isVisible"
        class="section-placeholder"
      />
    </template>

    <!-- Edit mode: render enabled sections normally, disabled ones as placeholders -->
    <template v-else>
      <component
        :is="sectionComponent"
        v-if="section.is_enabled && sectionComponent && isVisible"
        :section="section"
        :media-type="mediaType"
        @navigate-to-item="$emit('navigate-to-item', $event)"
        @play-item="$emit('play-item', $event)"
      />
      <div v-else-if="!section.is_enabled" class="section-disabled-placeholder">
        <q-icon :name="sectionTypeIcon" size="2em" color="grey-7" />
        <span class="text-grey-6">{{ section.title || section.section_type }}</span>
      </div>
      <div v-else-if="sectionComponent && !isVisible" class="section-placeholder" />
    </template>
  </div>
</template>

<script setup>
import { computed, ref, onMounted, onBeforeUnmount } from 'vue'
import { getSectionComponent, getSectionIcon } from './sectionRegistry'

const props = defineProps({
  section: {
    type: Object,
    required: true,
  },
  mediaType: {
    type: String,
    default: null,
  },
  editMode: {
    type: Boolean,
    default: false,
  },
})

defineEmits(['navigate-to-item', 'play-item'])

const sectionComponent = computed(() => getSectionComponent(props.section.section_type))
const sectionTypeIcon = computed(() => getSectionIcon(props.section.section_type))

// Lazy loading: only render when section is near the viewport
const sectionRef = ref(null)
const isVisible = ref(false)
let observer = null

// Always show the first section (hero carousel) immediately
const isFirstSection = computed(() => props.section.order_index === 0)

onMounted(() => {
  if (isFirstSection.value) {
    isVisible.value = true
    return
  }

  observer = new IntersectionObserver(
    ([entry]) => {
      if (entry.isIntersecting) {
        isVisible.value = true
        observer.disconnect()
        observer = null
      }
    },
    { rootMargin: '200px' },
  )
  if (sectionRef.value) {
    observer.observe(sectionRef.value)
  }
})

onBeforeUnmount(() => {
  if (observer) {
    observer.disconnect()
  }
})
</script>

<style lang="scss" scoped>
.section-placeholder {
  min-height: 300px;
}

.section-disabled-placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  min-height: 120px;
  padding: 24px;
}
</style>
