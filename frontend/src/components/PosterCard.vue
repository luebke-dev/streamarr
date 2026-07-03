<template>
  <q-card :class="cardClass" @click="handleClick">
    <q-img :src="imageUrl" :alt="title" :class="imageClass" spinner spinner-color="primary">
      <template v-slot:error>
        <div class="absolute-full flex flex-center poster-placeholder bg-grey-8">
          <div class="text-center text-white">
            <q-icon :name="placeholderIcon" size="3em" color="grey-4" />
            <div class="text-subtitle2 q-mt-sm">{{ title }}</div>
            <div class="text-caption text-grey-5">{{ $t('player.noImageAvailable') }}</div>
          </div>
        </div>
      </template>

      <!-- Parental-control badge (top-right) -->
      <q-badge v-if="ageBadge" :color="ageBadgeColor" text-color="white" floating class="age-badge">
        {{ ageBadge }}
      </q-badge>

      <div class="absolute-bottom poster-overlay">
        <div class="text-subtitle2 text-weight-bold">{{ title }}</div>
        <div class="text-caption">{{ subtitle }}</div>

        <!-- Optional additional content slot -->
        <slot name="overlay-content" />

        <!-- Status chip for shows -->
        <div v-if="status" class="text-caption">
          <q-chip
            :label="status"
            :color="getStatusColor(status)"
            text-color="white"
            size="sm"
            class="q-mt-xs"
          />
        </div>

        <!-- Platforms for games -->
        <div v-if="platforms && platforms.length" class="text-caption q-mt-xs">
          <q-icon name="mdi-gamepad-variant" size="xs" class="q-mr-xs" />
          {{ platforms.map((p) => p.name).join(', ') }}
        </div>

        <!-- Rating for games -->
        <div v-if="rating" class="text-caption">
          <q-icon name="mdi-star" size="xs" color="yellow" />
          {{ Math.round(rating) }}/100
        </div>

        <!-- Friends-watching attribution -->
        <div
          v-if="friendWatchers && friendWatchers.length"
          class="text-caption q-mt-xs friend-watchers"
        >
          <q-icon name="mdi-account-group" size="xs" class="q-mr-xs" />
          {{ friendWatchersLabel }}
        </div>
      </div>
    </q-img>
  </q-card>
</template>

<script>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

export default {
  name: 'PosterCard',
  props: {
    // Required props
    title: {
      type: String,
      required: true,
    },
    imageUrl: {
      type: String,
      default: null,
    },

    // Content type - affects styling and placeholder icon
    type: {
      type: String,
      required: true,
      validator: (value) =>
        ['movie', 'show', 'game', 'music', 'artist', 'album', 'song', 'book'].includes(value),
    },

    // Optional props
    subtitle: {
      type: String,
      default: '',
    },
    status: {
      type: String,
      default: null,
    },
    rating: {
      type: Number,
      default: null,
    },
    platforms: {
      type: Array,
      default: null,
    },
    friendWatchers: {
      type: Array,
      default: null,
    },

    // Parental-control certification fields from the backend (both optional)
    contentRating: {
      type: String,
      default: null,
    },
    minAge: {
      type: Number,
      default: null,
    },

    // Styling variants
    variant: {
      type: String,
      default: 'default',
      validator: (value) => ['default', 'compact'].includes(value),
    },

    // Click handler
    clickable: {
      type: Boolean,
      default: true,
    },
  },

  emits: ['click'],

  setup(props, { emit }) {
    const { t } = useI18n()

    // Computed properties for dynamic styling
    const isMusic = computed(() => ['music', 'artist', 'album', 'song'].includes(props.type))

    const ageBadge = computed(() => {
      if (props.contentRating) return props.contentRating
      if (props.minAge != null) return `${props.minAge}+`
      return null
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

    const friendWatchersLabel = computed(() => {
      const watchers = props.friendWatchers
      if (!watchers || !watchers.length) return ''
      const first = watchers[0]?.display_name || 'Friend'
      if (watchers.length === 1) {
        return t('recs.friends_watched_by', { names: first })
      }
      return t('recs.friends_and_n_more', {
        name: first,
        count: watchers.length - 1,
      })
    })

    const cardClass = computed(() => {
      const baseClass = 'poster-card'
      const typeClass = `${props.type}-card`
      const variantClass = props.variant === 'compact' ? 'poster-card--compact' : ''
      const clickableClass = props.clickable ? 'cursor-pointer' : ''
      const squareClass = isMusic.value ? 'poster-card--square' : ''

      return [baseClass, typeClass, variantClass, clickableClass, squareClass, 'q-mb-md']
    })

    const imageClass = computed(() => {
      const baseClass = 'poster-image'
      const typeClass = `${props.type}-${props.type === 'show' ? 'poster' : props.type === 'game' ? 'cover' : 'poster'}`

      return [baseClass, typeClass]
    })

    const placeholderIcon = computed(() => {
      switch (props.type) {
        case 'movie':
          return 'mdi-movie'
        case 'show':
          return 'mdi-television'
        case 'game':
          return 'mdi-gamepad-variant'
        case 'music':
        case 'song':
          return 'mdi-music'
        case 'artist':
          return 'mdi-account-music'
        case 'album':
          return 'mdi-album'
        case 'book':
          return 'mdi-book'
        default:
          return 'mdi-image'
      }
    })

    // Get status color for shows
    function getStatusColor(status) {
      switch (status?.toLowerCase()) {
        case 'returning series':
        case 'in production':
          return 'positive'
        case 'ended':
        case 'canceled':
          return 'negative'
        case 'pilot':
          return 'warning'
        default:
          return 'info'
      }
    }

    // Handle click events
    function handleClick() {
      if (props.clickable) {
        emit('click')
      }
    }

    return {
      cardClass,
      imageClass,
      placeholderIcon,
      getStatusColor,
      handleClick,
      friendWatchersLabel,
      ageBadge,
      ageBadgeColor,
    }
  },
}
</script>

<style lang="scss" scoped>
.age-badge {
  top: 8px;
  right: 8px;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.5px;
}

.poster-card {
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 12px;
  overflow: hidden;
  transition: all 0.3s cubic-bezier(0.25, 0.46, 0.45, 0.94);
  position: relative;
  aspect-ratio: 2 / 3;
  width: 100%;

  &:hover {
    transform: scale(1.05);
    z-index: 10;
    box-shadow: 0 25px 50px rgba(0, 0, 0, 0.9);
    background: rgba(255, 255, 255, 0);

    .poster-overlay {
      opacity: 1;
    }
  }
}

// Square aspect ratio for music types (album covers are square)
.poster-card--square {
  aspect-ratio: 1 / 1;
}

// Default styling for movies, shows, and games
.movie-card,
.show-card,
.game-card {
  .poster-overlay {
    padding: 16px;
  }
}

// Music cards — square with cover art styling
.music-card,
.artist-card,
.album-card,
.song-card {
  .poster-overlay {
    padding: 12px;
  }
}

.poster-image {
  border-radius: 8px;
  overflow: hidden;
  position: relative;
  background: linear-gradient(135deg, #1a1a1a 0%, #333 100%);
  height: 100%;

  // Ensure consistent aspect ratio
  .q-img__container {
    background: inherit;
  }

  // Style for loading/error states
  .q-img__loading,
  .q-img__error {
    background: inherit;
    color: rgba(255, 255, 255, 0.6);
  }
}

// Game covers have different aspect ratio
.game-cover {
  height: 100%;
  width: 100%;

  // Ensure images fill the card completely
  :deep(.q-img__image) {
    object-fit: cover !important;
  }

  :deep(.q-img__container) {
    background: #1a1a1a;
  }
}

// Movie and show posters
.movie-poster,
.show-poster {
  height: 100%;
  width: 100%;

  // Ensure images fill the card completely
  :deep(.q-img__image) {
    object-fit: cover !important;
  }

  :deep(.q-img__container) {
    background: #1a1a1a;
  }
}

.poster-placeholder {
  background: linear-gradient(135deg, #2a2a2a 0%, #1a1a1a 100%);
  border: 2px dashed rgba(255, 255, 255, 0.2);
  border-radius: 8px;
  height: 100%;

  .q-icon {
    margin-bottom: 8px;
  }
}

.poster-overlay {
  background: linear-gradient(
    0deg,
    rgba(0, 0, 0, 0.95) 0%,
    rgba(0, 0, 0, 0.7) 50%,
    rgba(0, 0, 0, 0.2) 80%,
    transparent 100%
  );
  opacity: 0;
  transition: opacity 0.3s ease;
}

// Compact variant
.poster-card--compact {
  .poster-overlay {
    padding: 8px;

    .text-subtitle2 {
      font-size: 0.8rem;
    }

    .text-caption {
      font-size: 0.7rem;
    }
  }
}

// Responsive adjustments
@media (max-width: 768px) {
  .poster-card:hover {
    transform: scale(1.02);
  }
}
</style>
