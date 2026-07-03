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
import HeroCarouselSection from './HeroCarouselSection.vue'
import GenreSection from './GenreSection.vue'
import AllGenresSection from './AllGenresSection.vue'
import ListSection from './ListSection.vue'
import DynamicSearchSection from './DynamicSearchSection.vue'
import LatestItemsSection from './LatestItemsSection.vue'
import ContinueWatchingSection from './ContinueWatchingSection.vue'
import FavoritesSection from './FavoritesSection.vue'
import PlatformsSection from './PlatformsSection.vue'
import TrailersSection from './TrailersSection.vue'

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

const sectionComponentMap = {
  hero_carousel: HeroCarouselSection,
  genre: GenreSection,
  all_genres: AllGenresSection,
  list: ListSection,
  dynamic_search: DynamicSearchSection,
  latest_items: LatestItemsSection,
  continue_watching: ContinueWatchingSection,
  favorites: FavoritesSection,
  platforms: PlatformsSection,
  trailers: TrailersSection,
}

const sectionIconMap = {
  hero_carousel: 'mdi-image-multiple',
  genre: 'mdi-tag',
  all_genres: 'mdi-tag-multiple',
  list: 'mdi-format-list-bulleted',
  dynamic_search: 'mdi-magnify',
  latest_items: 'mdi-clock-outline',
  continue_watching: 'mdi-play-circle',
  favorites: 'mdi-heart',
  platforms: 'mdi-gamepad-variant',
  trailers: 'mdi-movie-open-play',
}

const sectionComponent = computed(() => sectionComponentMap[props.section.section_type] || null)
const sectionTypeIcon = computed(
  () => sectionIconMap[props.section.section_type] || 'mdi-view-dashboard',
)

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
