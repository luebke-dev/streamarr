<template>
  <div>
    <div v-if="loadingGenres" class="flex flex-center q-pa-xl">
      <q-spinner-dots size="50px" color="primary" />
    </div>

    <div v-else class="genre-sections">
      <div v-for="genre in visibleGenres" :key="genre.id" class="section-container">
        <div class="section-header">
          <h4 class="section-title">{{ genre.name }}</h4>
          <q-btn
            flat
            dense
            color="grey-4"
            icon="mdi-arrow-right"
            :label="$t('common.seeAll', 'See all')"
            class="see-all-btn"
            @click="viewAllGenre(genre.id)"
          />
        </div>

        <!-- Sentinel element observed by IntersectionObserver -->
        <div :ref="(el) => setSentinel(genre.id, el)" class="media-row">
          <div v-if="genre.loading" class="skeleton-row">
            <q-skeleton
              v-for="n in 6"
              :key="n"
              type="rect"
              width="150px"
              height="225px"
              class="q-mr-sm"
            />
          </div>
          <div v-else-if="genre.items?.length" class="media-scrollable-row">
            <div v-for="item in genre.items" :key="item.guid" class="media-item">
              <PosterCard
                :type="getItemType(item)"
                :title="item.title"
                :image-url="getPosterUrl(item)"
                :subtitle="getItemSubtitle(item)"
                :rating="item.rating"
                :platforms="item.platforms"
                :content-rating="item.content_rating"
                :min-age="item.min_age"
                class="genre-media-card"
                @click="$emit('navigate-to-item', item)"
              />
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, onBeforeUnmount, computed } from 'vue'
import { useRouter } from 'vue-router'
import { searchMedia, getGenresWithItems, getGenres } from 'src/services/mediaComponentsService'
import { useMediaHelpers } from 'src/composables/useMediaHelpers'
import { getItemType } from 'src/composables/useMediaFormatters'
import PosterCard from 'src/components/PosterCard.vue'
import { logger } from 'src/utils/logger'

const props = defineProps({
  section: { type: Object, required: true },
  mediaType: { type: String, default: null },
})

defineEmits(['navigate-to-item'])

const router = useRouter()
const { getPosterUrl: getMediaPosterUrl, formatYear } = useMediaHelpers()

const genres = ref([])
const loadingGenres = ref(false)

const maxItemsPerGenre = computed(() => props.section.config?.max_items_per_genre || 10)
const filters = computed(() => props.section.config?.filters || {})
const hasFilters = computed(() => {
  const f = filters.value
  return f.availability || f.has_poster != null || f.has_description != null || f.platform_id
})

// Only show genres that haven't been loaded yet (skeleton) or have items
const visibleGenres = computed(() =>
  genres.value.filter((g) => g.items === null || g.items.length > 0),
)

// Track which genres have already been loaded or are in-flight
const loadedGenres = new Set()
const sentinelElements = new Map()
let observer = null

function getPosterUrl(item) {
  if (item.cover_url) return item.cover_url
  return getMediaPosterUrl(item)
}

function getItemSubtitle(item) {
  return formatYear(item.release_date || item.first_air_date)
}

function viewAllGenre(genreId) {
  const params = new URLSearchParams()
  params.set('genre_id', genreId)
  if (props.mediaType) params.set('media_type', props.mediaType)
  const f = filters.value
  if (f.availability) params.set('availability', f.availability)
  if (f.has_poster != null) params.set('has_poster', f.has_poster)
  if (f.has_description != null) params.set('has_description', f.has_description)
  if (f.platform_id) params.set('platform_id', f.platform_id)
  router.push(`/search?${params.toString()}`)
}

function setSentinel(genreId, el) {
  if (!el) {
    // Element unmounted — clean up
    const prev = sentinelElements.get(genreId)
    if (prev && observer) {
      observer.unobserve(prev)
    }
    sentinelElements.delete(genreId)
    return
  }

  sentinelElements.set(genreId, el)
  if (observer) {
    observer.observe(el)
  }
}

function createObserver() {
  observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue

        // Find which genre this sentinel belongs to
        for (const [genreId, el] of sentinelElements.entries()) {
          if (el === entry.target) {
            loadGenreItems(genreId)
            break
          }
        }
      }
    },
    { rootMargin: '200px' },
  )

  // Observe any sentinels already registered
  for (const el of sentinelElements.values()) {
    observer.observe(el)
  }
}

// Filter path only: fetch one genre's items via the search API (the search
// endpoint is the only one that honours availability/has_poster/platform_id).
async function loadGenreItems(genreId) {
  if (loadedGenres.has(genreId)) return
  loadedGenres.add(genreId)

  const genre = genres.value.find((g) => g.id === genreId)
  if (!genre) return

  genre.loading = true

  try {
    const f = filters.value
    const payload = {
      per_page: maxItemsPerGenre.value,
      page: 1,
      genre_id: genreId,
      search_type: 'all',
    }
    if (props.mediaType) {
      payload.media_type = props.mediaType
      payload.search_type = props.mediaType.toLowerCase()
    }
    if (f.availability) payload.availability = f.availability
    if (f.has_poster != null) payload.has_poster = f.has_poster
    if (f.has_description != null) payload.has_description = f.has_description
    if (f.platform_id) payload.platform_id = f.platform_id

    const res = await searchMedia(payload)
    genre.items = (res.hits || []).filter((item) => getPosterUrl(item))
  } catch (error) {
    logger.error(`Error loading items for genre ${genreId}:`, error)
    genre.items = []
  } finally {
    genre.loading = false

    // Stop observing this sentinel since it is loaded
    const el = sentinelElements.get(genreId)
    if (el && observer) {
      observer.unobserve(el)
    }
  }
}

// No-filter path (the common case): one optimised request returns every genre
// with its items. Empty or permission-filtered genres simply aren't returned,
// so there are no wasted per-genre round-trips.
async function loadAllGenresWithItems() {
  loadingGenres.value = true
  try {
    const params = { max_items_per_genre: maxItemsPerGenre.value }
    if (props.mediaType) params.media_type = props.mediaType
    const response = await getGenresWithItems(params)
    const data = Array.isArray(response) ? response : []
    genres.value = data.map((g) =>
      reactive({
        id: g.id,
        name: g.name,
        loading: false,
        items: g.items || [],
      }),
    )
  } catch (error) {
    logger.error('Error loading genres with items:', error)
    genres.value = []
  } finally {
    loadingGenres.value = false
  }
}

async function loadGenreList() {
  loadingGenres.value = true
  try {
    const params = {}
    if (props.mediaType) params.media_type = props.mediaType
    const rawGenres = (await getGenres(params)) || []
    // Wrap each genre in a reactive object with loading/items state
    genres.value = rawGenres.map((g) =>
      reactive({
        id: g.id,
        name: g.name,
        loading: false,
        items: null,
      }),
    )
  } catch (error) {
    logger.error('Error loading genre list:', error)
  } finally {
    loadingGenres.value = false
  }
}

onMounted(async () => {
  if (hasFilters.value) {
    // Filters active: fetch the genre list, then lazy-load each genre's items
    // via the search API as its row scrolls into view.
    await loadGenreList()
    createObserver()
  } else {
    // No filters: a single request returns all genres with their items.
    await loadAllGenresWithItems()
  }
})

onBeforeUnmount(() => {
  if (observer) {
    observer.disconnect()
    observer = null
  }
  sentinelElements.clear()
  loadedGenres.clear()
})
</script>
