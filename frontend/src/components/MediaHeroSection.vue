<template>
  <div class="media-hero">
    <q-img :src="backdropUrl" class="media-backdrop" :style="{ height: height }">
      <div class="absolute-full bg-gradient-overlay"></div>

      <!-- Back button slot (top-left) -->
      <div class="absolute-top-left q-pa-md">
        <slot name="back-button"></slot>
      </div>

      <!-- Previous navigation (left center) -->
      <div class="absolute-left-center">
        <slot name="prev-navigation"></slot>
      </div>

      <!-- Next navigation (right center) -->
      <div class="absolute-right-center">
        <slot name="next-navigation"></slot>
      </div>

      <div class="absolute-bottom q-pa-xl">
        <div class="row items-end">
          <!-- Poster/Still Image -->
          <div class="col-auto q-mr-xl">
            <q-img :src="posterUrl" class="media-poster-large" :style="posterStyle">
              <template v-slot:error>
                <div class="absolute-full flex flex-center media-placeholder bg-grey-8">
                  <div class="text-center text-white">
                    <q-icon :name="placeholderIcon" size="4em" color="grey-4" />
                    <div class="text-subtitle2 q-mt-sm">{{ title }}</div>
                    <div class="text-caption text-grey-5">{{ placeholderText }}</div>
                  </div>
                </div>
              </template>
            </q-img>
          </div>

          <!-- Info Section -->
          <div class="col">
            <div class="media-info-hero">
              <!-- Pre-title slot (e.g., show title for season/episode) -->
              <slot name="pre-title"></slot>

              <!-- Main Title -->
              <h1 class="text-white text-h5 q-mb-sm">{{ title }}</h1>

              <!-- Original Title -->
              <div
                class="text-grey-3 text-h6 q-mb-sm"
                v-if="originalTitle && originalTitle !== title"
              >
                {{ originalTitle }}
              </div>

              <!-- Tagline -->
              <div class="text-grey-3 text-caption q-mb-md" v-if="tagline">{{ tagline }}</div>

              <!-- Meta Chips Slot -->
              <div class="media-meta q-mb-md">
                <slot name="meta-chips"></slot>
              </div>

              <!-- Action Buttons Slot -->
              <div class="media-actions q-gutter-sm">
                <slot name="actions"></slot>
              </div>
            </div>
          </div>
        </div>
      </div>
    </q-img>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  /**
   * URL for the backdrop image
   */
  backdropUrl: {
    type: String,
    default: null,
  },
  /**
   * URL for the poster image
   */
  posterUrl: {
    type: String,
    default: null,
  },
  /**
   * Main title to display
   */
  title: {
    type: String,
    required: true,
  },
  /**
   * Original title (shown if different from title)
   */
  originalTitle: {
    type: String,
    default: null,
  },
  /**
   * Tagline to display
   */
  tagline: {
    type: String,
    default: null,
  },
  /**
   * Height of the hero section
   */
  height: {
    type: String,
    default: '65vh',
  },
  /**
   * Width of the poster image
   */
  posterWidth: {
    type: String,
    default: '150px',
  },
  /**
   * Height of the poster image
   */
  posterHeight: {
    type: String,
    default: '225px',
  },
  /**
   * Icon for placeholder when poster fails to load
   */
  placeholderIcon: {
    type: String,
    default: 'mdi-movie',
  },
  /**
   * Text for placeholder when poster fails to load
   */
  placeholderText: {
    type: String,
    default: 'No Image Available',
  },
})

const posterStyle = computed(() => ({
  width: props.posterWidth,
  height: props.posterHeight,
}))
</script>

<style lang="scss" scoped>
.media-hero {
  position: relative;
  min-height: 50vh;
  max-width: 1800px;
  margin: 0 auto;
  overflow: hidden;
}

.media-backdrop {
  width: 100%;
  object-fit: cover;
}

.bg-gradient-overlay {
  background:
    linear-gradient(
      to right,
      rgba(0, 0, 0, 0.8) 0%,
      rgba(0, 0, 0, 0.6) 50%,
      rgba(0, 0, 0, 0.4) 100%
    ),
    linear-gradient(to bottom, rgba(0, 0, 0, 0.2) 0%, rgba(0, 0, 0, 0.8) 100%);
}

.media-poster-large {
  border-radius: 16px;
  overflow: hidden;
  box-shadow: 0 20px 40px rgba(0, 0, 0, 0.5);

  :deep(.q-img__image) {
    background: linear-gradient(135deg, #2a2a2a 0%, #1a1a1a 100%);
  }
}

.media-placeholder {
  border-radius: 16px;
}

.media-info-hero {
  h1 {
    text-shadow: 2px 2px 4px rgba(0, 0, 0, 0.8);
  }
}

// Back button styling
.absolute-top-left {
  z-index: 10;
  background: transparent !important;
  pointer-events: none;

  :deep(.q-btn) {
    pointer-events: auto;
  }

  :deep(.no-background) {
    background: transparent !important;

    &::before {
      display: none !important;
    }

    &:hover {
      background: rgba(255, 255, 255, 0.1) !important;
    }
  }
}

// Navigation buttons (left/right)
.absolute-left-center,
.absolute-right-center {
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
  z-index: 10;
  background: transparent !important;
  pointer-events: none;

  :deep(.q-btn) {
    pointer-events: auto;
    background: transparent !important;

    &::before {
      display: none !important;
    }

    &:hover {
      background: rgba(255, 255, 255, 0.1) !important;
    }
  }
}

.absolute-left-center {
  left: 16px;
}

.absolute-right-center {
  right: 16px;
}

// Action buttons styling
.media-actions {
  :deep(.q-btn) {
    text-transform: none;
    font-weight: 600;

    &.q-btn--outline {
      border-width: 2px;
    }
  }
}

// Chip styling for meta section
.media-meta {
  :deep(.q-chip) {
    font-weight: 600;
    background: rgba(255, 255, 255, 0.1);
    color: white;
    border: 1px solid rgba(255, 255, 255, 0.2);
  }
}

// Responsive design
@media (max-width: 1024px) {
  .media-hero {
    min-height: 50vh;
  }
}

@media (max-width: 768px) {
  .media-hero .absolute-bottom {
    padding: 20px !important;
  }

  .media-poster-large {
    width: 120px !important;
    height: 180px !important;
  }

  .media-info-hero h1 {
    font-size: 2rem !important;
  }
}

@media (max-width: 480px) {
  .media-hero .row {
    flex-direction: column;
    align-items: center;
    text-align: center;
    gap: 20px;
  }

  .media-poster-large {
    width: 100px !important;
    height: 150px !important;
  }

  .media-info-hero h1 {
    font-size: 1.5rem !important;
  }
}
</style>
