<template>
  <div class="media-meta-chips">
    <!-- Year/Release Date Chip -->
    <q-chip
      v-if="year"
      :label="year"
      color="primary"
      text-color="white"
      :size="chipSize"
      class="q-mr-sm"
    />

    <!-- Runtime Chip -->
    <q-chip
      v-if="runtime"
      :label="runtime"
      color="info"
      text-color="white"
      :size="chipSize"
      class="q-mr-sm"
    />

    <!-- Rating Chip -->
    <q-chip
      v-if="rating"
      :label="rating"
      :color="ratingColor"
      text-color="white"
      :size="chipSize"
      class="q-mr-sm"
    />

    <!-- Age-Rating Chip (parental control certification) -->
    <q-chip
      v-if="contentRating || minAge != null"
      :label="contentRating || `${minAge}+`"
      :color="ageBadgeColor"
      text-color="white"
      :size="chipSize"
      class="q-mr-sm"
    />

    <!-- Status Chip -->
    <q-chip
      v-if="status"
      :label="statusLabel"
      :color="statusColor"
      text-color="white"
      :size="chipSize"
      class="q-mr-sm"
    />

    <!-- Episode Count Chip (for shows/seasons) -->
    <q-chip
      v-if="episodeCount"
      :label="episodeCount"
      color="accent"
      text-color="white"
      :size="chipSize"
      class="q-mr-sm"
    />

    <!-- Custom Chips Slot -->
    <slot name="custom-chips"></slot>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  /**
   * Year to display (from formatYear)
   */
  year: {
    type: String,
    default: null,
  },

  /**
   * Runtime formatted string (from formatRuntime)
   */
  runtime: {
    type: String,
    default: null,
  },

  /**
   * Rating formatted string (from formatRating)
   */
  rating: {
    type: String,
    default: null,
  },

  /**
   * Rating color (from getRatingColor)
   */
  ratingColor: {
    type: String,
    default: 'grey',
  },

  /**
   * Status string (e.g., 'released', 'upcoming', 'Ended', 'Returning Series')
   */
  status: {
    type: String,
    default: null,
  },

  /**
   * Custom status label (if provided, overrides automatic translation)
   */
  statusLabel: {
    type: String,
    default: null,
  },

  /**
   * Status color
   */
  statusColor: {
    type: String,
    default: 'grey',
  },

  /**
   * Episode count string (e.g., "10 Episodes")
   */
  episodeCount: {
    type: String,
    default: null,
  },

  /**
   * Chip size: 'sm', 'md', 'lg'
   */
  chipSize: {
    type: String,
    default: 'md',
    validator: (value) => ['sm', 'md', 'lg'].includes(value),
  },

  /**
   * Raw content-rating certification (e.g. "FSK 16", "PG-13")
   */
  contentRating: {
    type: String,
    default: null,
  },

  /**
   * Normalized minimum viewer age in years
   */
  minAge: {
    type: Number,
    default: null,
  },
})

const ageBadgeColor = computed(() => {
  const age = props.minAge
  if (age == null) return 'grey-8'
  if (age >= 18) return 'red-9'
  if (age >= 16) return 'deep-orange-8'
  if (age >= 12) return 'amber-8'
  if (age >= 6) return 'teal-7'
  return 'green-8'
})
</script>

<style lang="scss" scoped>
.media-meta-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;

  :deep(.q-chip) {
    font-weight: 600;
  }
}
</style>
