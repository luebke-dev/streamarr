<template>
  <div
    class="q-pb-md hero-carousel-wrapper"
    @mouseenter="pauseAutoplay"
    @mouseleave="resumeAutoplay"
  >
    <q-carousel
      v-if="!loading && items.length > 0"
      swipeable
      animated
      v-model="slide"
      :autoplay="autoplay"
      ref="carousel"
      infinite
      :height="carouselHeight"
      class="hero-carousel"
    >
      <q-carousel-slide
        v-for="(item, index) in items"
        :key="item.guid"
        :name="index + 1"
        :img-src="getSlideBackgroundImage(item)"
        class="hero-slide"
      >
        <div class="carousel-overlay">
          <div class="trending-badge-corner">
            <q-chip
              icon="mdi-trending-up"
              color="warning"
              text-color="white"
              class="trending-chip"
              :label="trendingLabel"
            />
          </div>
          <div class="carousel-content">
            <div class="carousel-text">
              <h1 class="carousel-title" :style="getTitleStyle(getItemTitle(item))">
                {{ getItemTitle(item) }}
              </h1>
              <div v-if="subtitleFn && subtitleFn(item)" class="carousel-subtitle">
                {{ subtitleFn(item) }}
              </div>
              <p v-if="getItemDescription(item) && !isMobile" class="carousel-description">
                {{ truncateDescription(getItemDescription(item), descriptionLength) }}
              </p>
              <div class="carousel-meta">
                <span v-if="getItemReleaseDate(item)" class="release-year">
                  {{ formatReleaseYear(getItemReleaseDate(item)) }}
                </span>
                <span v-if="getItemRating(item)" class="rating">
                  <q-icon name="mdi-star" color="yellow" size="sm" />
                  {{ getItemRating(item).toFixed(1) }}
                </span>
              </div>
              <div class="carousel-actions">
                <q-btn
                  color="white"
                  :size="isMobile ? 'md' : 'lg'"
                  outline
                  :round="isMobile"
                  icon="mdi-play-circle"
                  :label="
                    isMobile
                      ? undefined
                      : primaryButtonLabelFn
                        ? primaryButtonLabelFn(item)
                        : primaryButtonLabel
                  "
                  @click="$emit('primaryAction', item)"
                  class="hero-btn-primary"
                />
                <q-btn
                  color="white"
                  text-color="primary"
                  :size="isMobile ? 'md' : 'lg'"
                  :round="isMobile"
                  icon="mdi-information-outline"
                  :label="isMobile ? undefined : secondaryButtonLabel"
                  @click="$emit('secondaryAction', item)"
                  class="hero-btn-secondary"
                />
              </div>
            </div>
            <div class="carousel-poster" v-if="isDesktop">
              <img :src="getItemPoster(item)" :alt="getItemTitle(item)" class="poster-image" />
            </div>
          </div>
        </div>
      </q-carousel-slide>

      <template v-slot:control>
        <q-carousel-control
          v-if="!isMobile"
          position="bottom-right"
          :offset="[24, 24]"
          class="hero-carousel-controls q-gutter-xs"
        >
          <q-btn
            push
            round
            dense
            color="primary"
            text-color="black"
            icon="mdi-arrow-left"
            style="z-index: 15"
            @click="$refs.carousel.previous()"
          />
          <q-btn
            push
            round
            dense
            color="primary"
            text-color="black"
            icon="mdi-arrow-right"
            style="z-index: 15"
            @click="$refs.carousel.next()"
          />
        </q-carousel-control>
      </template>
    </q-carousel>

    <div
      v-else-if="loading"
      :style="{ height: carouselHeight }"
      class="hero-carousel-skeleton overflow-hidden"
    >
      <q-skeleton
        type="rect"
        width="100%"
        height="100%"
        animation="wave"
        class="hero-skeleton-bg"
      />
    </div>

    <div v-else class="flex flex-center q-pa-xl">
      <div class="text-center">
        <q-icon :name="emptyIcon" size="4em" color="grey-5" />
        <div class="text-grey-5 q-mt-md">{{ emptyMessage }}</div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, computed, watch } from 'vue'
import { useQuasar } from 'quasar'
import { getTmdbImageUrl } from 'src/composables/useMediaFormatters'
import { overlayServeUrl } from 'src/utils/posters'

export default {
  name: 'HeroCarousel',
  emits: ['primaryAction', 'secondaryAction'],
  props: {
    items: {
      type: Array,
      default: () => [],
    },
    loading: {
      type: Boolean,
      default: false,
    },
    itemType: {
      type: String,
      default: 'movie', // 'movie', 'show', 'game', 'mixed'
      validator: (value) => ['movie', 'show', 'game', 'mixed'].includes(value),
    },
    trendingLabel: {
      type: String,
      default: 'Trending Now',
    },
    primaryButtonLabel: {
      type: String,
      default: 'Watch Now',
    },
    primaryButtonLabelFn: {
      type: Function,
      default: null,
    },
    subtitleFn: {
      type: Function,
      default: null,
    },
    secondaryButtonLabel: {
      type: String,
      default: 'More Info',
    },
    emptyIcon: {
      type: String,
      default: 'movie',
    },
    emptyMessage: {
      type: String,
      default: 'No trending items available',
    },
  },
  setup(props) {
    const $q = useQuasar()
    const slide = ref(1)
    const autoplay = ref(true)

    watch(
      () => props.items,
      (items) => {
        if (slide.value > items.length) {
          slide.value = 1
        }
      },
    )

    // Responsive breakpoints
    const isMobile = computed(() => $q.screen.lt.md)
    const isTablet = computed(() => $q.screen.md)
    const isDesktop = computed(() => $q.screen.gt.md)

    // Dynamic carousel height based on screen size
    const carouselHeight = computed(() => {
      if (isMobile.value) return '42.5vh'
      if (isTablet.value) return '46.75vh'
      return '55.25vh'
    })

    // Dynamic description length based on screen size
    const descriptionLength = computed(() => {
      if (isMobile.value) return 150
      if (isTablet.value) return 200
      return 250
    })

    // Pause autoplay on hover
    function pauseAutoplay() {
      autoplay.value = false
    }

    // Resume autoplay when mouse leaves
    function resumeAutoplay() {
      autoplay.value = true
    }

    // Get item title based on type
    function getItemTitle(item) {
      switch (props.itemType) {
        case 'movie':
          return item.title
        case 'show':
          return item.name || item.title
        case 'game':
          return item.name || item.title
        case 'mixed':
          // For mixed content, use the item's type property to determine the correct field
          if (item.type === 'movie') {
            return item.title
          } else if (item.type === 'show') {
            return item.name || item.title
          } else if (item.type === 'game') {
            return item.name || item.title
          }
          return item.title || item.name
        default:
          return item.title || item.name
      }
    }

    // Get item description based on type
    function getItemDescription(item) {
      // Try multiple possible description fields
      const description = item.description || item.overview || item.summary || item.synopsis || ''

      switch (props.itemType) {
        case 'movie':
          return description || item.overview
        case 'show':
          return description || item.overview
        case 'game':
          return description || item.summary
        case 'mixed':
          if (item.type === 'game') {
            return description || item.summary
          }
          return description || item.overview
        default:
          return description
      }
    }

    // Get item release date based on type
    function getItemReleaseDate(item) {
      switch (props.itemType) {
        case 'movie':
          return item.release_date
        case 'show':
          return item.first_air_date
        case 'game':
          return item.first_release_date
        case 'mixed':
          if (item.type === 'movie') {
            return item.release_date
          } else if (item.type === 'show') {
            return item.first_air_date
          } else if (item.type === 'game') {
            return item.first_release_date
          }
          return item.release_date || item.first_air_date || item.first_release_date
        default:
          return item.release_date || item.first_air_date || item.first_release_date
      }
    }

    // Get item rating based on type
    function getItemRating(item) {
      switch (props.itemType) {
        case 'movie':
          return item.vote_average
        case 'show':
          return item.vote_average
        case 'game':
          return item.rating
        case 'mixed':
          if (item.type === 'game') {
            return item.rating
          }
          return item.vote_average
        default:
          return item.vote_average || item.rating
      }
    }

    // Get item poster URL
    function getItemPoster(item) {
      // Local media items: hand off to the overlay-aware serving route.
      // It returns a pre-rendered overlay on cache hit and 302-redirects
      // to the original poster on miss, so this stays cheap.
      const overlay = overlayServeUrl(item, 'POSTER')
      if (overlay) return overlay

      if (!item.poster_path && !item.cover) return '/icons/favicon-96x96.png'

      // Full URL (e.g. IGDB games stored in DB)
      if (item.poster_path && item.poster_path.startsWith('http')) {
        return item.poster_path
      }

      // For TMDB items (movies/shows)
      if (item.poster_path) {
        return getTmdbImageUrl(item.poster_path, 'w300')
      }

      // For raw IGDB items (games) with cover object
      if (item.cover && item.cover.url) {
        return `https:${item.cover.url.replace('t_thumb', 't_cover_big')}`
      }

      return '/icons/favicon-96x96.png'
    }

    // Format release date to year only
    function formatReleaseYear(dateString) {
      if (!dateString) return 'TBA'

      // Handle UNIX timestamp (games)
      if (typeof dateString === 'number') {
        return new Date(dateString * 1000).getFullYear().toString()
      }

      // Handle date string
      return new Date(dateString).getFullYear().toString()
    }

    // Truncate description for hero section
    function truncateDescription(text, maxLength) {
      if (!text) return ''
      if (text.length <= maxLength) return text
      return text.substring(0, maxLength).trim() + '...'
    }

    // Get carousel slide background image URL for img-src
    function getSlideBackgroundImage(item) {
      // Full URL (e.g. IGDB games stored in DB)
      if (item.backdrop_path && item.backdrop_path.startsWith('http')) {
        return item.backdrop_path
      }

      // Local movie/show: use overlay-aware backdrop serving.
      if (item.backdrop_path || item.poster_path) {
        const overlay = overlayServeUrl(item, 'BACKDROP')
        if (overlay) return overlay
      }

      // For movies/shows - prefer backdrop, fallback to poster
      if (item.backdrop_path) {
        return getTmdbImageUrl(item.backdrop_path, 'w1280')
      }

      // Full URL poster fallback
      if (item.poster_path && item.poster_path.startsWith('http')) {
        return item.poster_path
      }

      // Fallback to poster image for movies/shows without backdrop
      if (item.poster_path) {
        return getTmdbImageUrl(item.poster_path, 'w1280')
      }

      // For raw IGDB items - use screenshot or artwork
      if (item.screenshots && item.screenshots.length > 0) {
        return `https:${item.screenshots[0].url.replace('t_thumb', 't_screenshot_big')}`
      }

      if (item.artworks && item.artworks.length > 0) {
        return `https:${item.artworks[0].url.replace('t_thumb', 't_1080p')}`
      }

      return null
    }

    // Calculate dynamic font size based on title length
    function getTitleStyle(title) {
      if (!title) return {}

      const length = title.length
      let fontSize = '3.5rem'

      // Adjust font size based on title length - more aggressive scaling
      if (length > 60) {
        fontSize = '1.5rem'
      } else if (length > 50) {
        fontSize = '1.8rem'
      } else if (length > 40) {
        fontSize = '2.2rem'
      } else if (length > 30) {
        fontSize = '2.8rem'
      } else if (length > 20) {
        fontSize = '3.2rem'
      }

      // Further reduce for mobile
      if (isMobile.value) {
        if (length > 40) {
          fontSize = '0.9rem'
        } else if (length > 30) {
          fontSize = '1.1rem'
        } else if (length > 20) {
          fontSize = '1.3rem'
        } else if (length > 15) {
          fontSize = '1.5rem'
        } else {
          fontSize = '1.8rem'
        }
      } else if (isTablet.value) {
        if (length > 50) {
          fontSize = '1.3rem'
        } else if (length > 40) {
          fontSize = '1.6rem'
        } else if (length > 30) {
          fontSize = '2rem'
        } else if (length > 20) {
          fontSize = '2.3rem'
        } else {
          fontSize = '2.5rem'
        }
      }

      return { fontSize }
    }

    return {
      slide,
      autoplay,
      isMobile,
      isTablet,
      isDesktop,
      carouselHeight,
      descriptionLength,
      pauseAutoplay,
      resumeAutoplay,
      getTitleStyle,
      getItemTitle,
      getItemDescription,
      getItemReleaseDate,
      getItemRating,
      getItemPoster,
      formatReleaseYear,
      truncateDescription,
      getSlideBackgroundImage,
    }
  },
}
</script>

<style lang="scss" scoped>
// Hero Carousel Wrapper
.hero-carousel-wrapper {
  width: 100%;
  max-width: 1800px;
  margin: 0 auto;
  overflow: hidden;
  background: #000;
}

.hero-carousel-skeleton {
  width: 100%;
  border-radius: 0;

  .hero-skeleton-bg {
    border-radius: 0;
    background: linear-gradient(110deg, #111 0%, #222 45%, #141414 100%);
  }
}

.hero-carousel {
  width: 100%;
}

.hero-slide {
  background-size: cover;
  background-position: center;

  &::after {
    content: '';
    position: absolute;
    inset: 0;
    background: linear-gradient(to bottom, rgba(0, 0, 0, 0.08) 0%, rgba(0, 0, 0, 0.72) 100%);
    z-index: 0;
  }
}

// Carousel Overlay Styles
.carousel-overlay {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background:
    linear-gradient(
      90deg,
      rgba(0, 0, 0, 0.92) 0%,
      rgba(0, 0, 0, 0.68) 42%,
      rgba(0, 0, 0, 0.24) 100%
    ),
    linear-gradient(180deg, rgba(0, 0, 0, 0.12) 0%, rgba(0, 0, 0, 0.72) 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1;
  pointer-events: none;
  padding: clamp(1rem, 2vw, 2rem);
}

.carousel-content {
  display: flex;
  align-items: center;
  justify-content: space-between;
  max-width: 1400px;
  width: 100%;
  padding: clamp(1.25rem, 3vw, 3.5rem);
  gap: clamp(2rem, 5vw, 5rem);
  pointer-events: auto;
}

.carousel-text {
  flex: 2;
  color: white;
  max-width: 760px;
  width: 100%;
  min-width: 0;
  box-sizing: border-box;
}

.trending-badge-corner {
  position: absolute;
  top: clamp(14px, 2vw, 28px);
  left: clamp(14px, 2vw, 28px);
  z-index: 10;

  .trending-chip {
    min-height: 30px;
    padding: 0 0.85rem;
    border: 1px solid rgba(255, 255, 255, 0.22);
    background: rgba(242, 192, 55, 0.95) !important;
    box-shadow: 0 10px 24px rgba(0, 0, 0, 0.32);
    font-weight: 600;
    letter-spacing: 0;

    :deep(.q-chip__icon) {
      color: white;
      margin-right: 0.35rem;
    }
  }
}

.carousel-title {
  font-weight: 800;
  margin: 0 0 1.1rem 0;
  color: white;
  text-shadow: 0 3px 18px rgba(0, 0, 0, 0.68);
  line-height: 1.05;
  white-space: normal;
  letter-spacing: 0;
  overflow-wrap: anywhere;
}

.carousel-subtitle {
  margin: 0 0 0.85rem;
  color: rgba(255, 255, 255, 0.88);
  font-size: 1.05rem;
  font-weight: 600;
  text-shadow: 0 2px 10px rgba(0, 0, 0, 0.6);
}

.carousel-description {
  max-width: 680px;
  margin: 0 0 1.25rem;
  color: rgba(255, 255, 255, 0.84);
  font-size: 1.05rem;
  line-height: 1.55;
  text-shadow: 0 2px 10px rgba(0, 0, 0, 0.6);
  max-height: 8.2rem;
  overflow: hidden;
  word-wrap: break-word;
  overflow-wrap: break-word;
  hyphens: auto;
  text-align: left;
  display: block;
}

.carousel-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.75rem;
  margin-bottom: 1.75rem;

  .release-year {
    color: rgba(255, 255, 255, 0.9);
    font-size: 0.95rem;
    font-weight: 600;
  }

  .rating {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    color: rgba(255, 255, 255, 0.94);
    font-size: 0.95rem;
    font-weight: 700;
  }

  .release-year,
  .rating {
    min-height: 32px;
    padding: 0.35rem 0.75rem;
    border: 1px solid rgba(255, 255, 255, 0.16);
    border-radius: 999px;
    background: rgba(255, 255, 255, 0.1);
    backdrop-filter: blur(12px);
    box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.12);
  }
}

.carousel-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.85rem;
}

.carousel-poster {
  flex: 1;
  display: flex;
  justify-content: center;
  align-items: center;

  .poster-image {
    max-width: min(300px, 24vw);
    max-height: min(450px, 43vh);
    width: auto;
    height: auto;
    border: 1px solid rgba(255, 255, 255, 0.18);
    border-radius: 10px;
    box-shadow: 0 22px 52px rgba(0, 0, 0, 0.55);
    transition:
      transform 0.25s ease,
      box-shadow 0.25s ease;

    &:hover {
      box-shadow: 0 26px 62px rgba(0, 0, 0, 0.65);
      transform: translateY(-3px) scale(1.02);
    }
  }
}

.hero-btn-primary {
  min-height: 48px;
  padding: 0.65rem 1.45rem;
  font-weight: 600;
  text-transform: none;
  border-radius: 8px;
  border: 1px solid rgba(255, 255, 255, 0.86);
  background: rgba(255, 255, 255, 0.12) !important;
  box-shadow: 0 14px 28px rgba(0, 0, 0, 0.34);
  backdrop-filter: blur(14px);
  transition:
    background-color 0.2s ease,
    border-color 0.2s ease,
    box-shadow 0.2s ease,
    transform 0.2s ease;

  &:hover {
    border-color: white;
    background: rgba(255, 255, 255, 0.2) !important;
    box-shadow: 0 18px 34px rgba(0, 0, 0, 0.44);
    transform: translateY(-1px);
  }
}

.hero-btn-secondary {
  min-height: 48px;
  padding: 0.65rem 1.45rem;
  font-weight: 600;
  text-transform: none;
  border-radius: 8px;
  border: 1px solid rgba(255, 255, 255, 0.72);
  background: rgba(255, 255, 255, 0.92) !important;
  box-shadow: 0 14px 28px rgba(0, 0, 0, 0.28);
  transition:
    background-color 0.2s ease,
    border-color 0.2s ease,
    box-shadow 0.2s ease,
    transform 0.2s ease;

  &:hover {
    background: white !important;
    border-color: white;
    box-shadow: 0 18px 34px rgba(0, 0, 0, 0.38);
    transform: translateY(-1px);
  }
}

.hero-carousel-controls {
  display: flex;
  gap: 0.5rem;
  padding: 0.35rem;
  border: 1px solid rgba(255, 255, 255, 0.16);
  border-radius: 999px;
  background: rgba(0, 0, 0, 0.34);
  backdrop-filter: blur(12px);

  :deep(.q-btn) {
    width: 36px;
    height: 36px;
    color: white !important;
    background: rgba(255, 255, 255, 0.12) !important;
    box-shadow: none;
    transition:
      background-color 0.2s ease,
      transform 0.2s ease;

    &::before {
      display: none;
    }

    &:hover {
      background: rgba(255, 255, 255, 0.22) !important;
      transform: translateY(-1px);
    }
  }
}

// Responsive Design
@media (max-width: 1024px) {
  .carousel-overlay {
    padding: 1rem;
  }

  .carousel-content {
    padding: 1.5rem;
    gap: 2rem;
  }

  .carousel-description {
    font-size: 1rem;
    line-height: 1.55;
    max-height: 7.75rem;
  }
}

@media (max-width: 768px) {
  .carousel-overlay {
    background:
      linear-gradient(to bottom, rgba(0, 0, 0, 0.26) 0%, rgba(0, 0, 0, 0.9) 100%),
      linear-gradient(to right, rgba(0, 0, 0, 0.36) 0%, rgba(0, 0, 0, 0.18) 100%);
    padding: 0.75rem;
    align-items: flex-end;
  }

  .carousel-content {
    flex-direction: column;
    gap: 0.75rem;
    text-align: center;
    padding: 1rem;
  }

  .carousel-text {
    flex: none;
    max-width: 100%;
  }

  .carousel-meta {
    justify-content: center;
    gap: 0.5rem;
    margin-bottom: 1rem;

    .release-year,
    .rating {
      min-height: 30px;
      font-size: 0.85rem;
    }
  }

  .carousel-actions {
    flex-direction: row;
    justify-content: center;
    gap: 1rem;
  }

  .hero-btn-primary,
  .hero-btn-secondary {
    min-width: 44px;
    min-height: 44px;
    width: auto;
    padding: 0.5rem;
  }
}

@media (max-width: 480px) {
  .carousel-overlay {
    padding: 0.5rem;
  }

  .carousel-content {
    padding: 0.5rem;
    gap: 0.5rem;
  }

  .carousel-title {
    font-size: 1.4rem !important;
  }

  .carousel-meta {
    gap: 0.5rem;
    margin-bottom: 0.75rem;

    .release-year,
    .rating {
      font-size: 0.8rem;
    }
  }

  .trending-chip {
    font-size: 0.7rem;
  }
}
</style>
