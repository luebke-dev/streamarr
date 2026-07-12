<template>
  <div class="person-page">
    <!-- Loading -->
    <div v-if="loading" class="flex flex-center" style="min-height: 60vh">
      <q-spinner-dots color="primary" size="48px" />
    </div>

    <!-- Error -->
    <div v-else-if="error" class="flex flex-center column" style="min-height: 60vh">
      <q-icon name="mdi-alert-circle" size="64px" color="negative" class="q-mb-md" />
      <p class="text-grey-5">{{ error }}</p>
      <q-btn
        flat
        color="primary"
        icon="mdi-arrow-left"
        :label="$t('common.back')"
        @click="$router.back()"
      />
    </div>

    <!-- Person Details -->
    <div v-else-if="person" class="person-content q-pa-xl">
      <!-- Back button -->
      <q-btn
        flat
        dense
        icon="mdi-arrow-left"
        :label="$t('common.back')"
        text-color="white"
        class="q-mb-lg"
        @click="$router.back()"
      />

      <!-- Person Header -->
      <div class="row q-gutter-xl q-mb-xl">
        <!-- Profile Photo -->
        <div class="person-photo-container">
          <q-img
            v-if="person.profile_path"
            :src="getTmdbImageUrl(person.profile_path, 'w342')"
            :ratio="2 / 3"
            class="person-photo rounded-borders"
          >
            <template #error>
              <div class="absolute-full flex flex-center bg-grey-8 rounded-borders">
                <q-icon name="mdi-account" size="96px" color="grey-6" />
              </div>
            </template>
          </q-img>
          <div v-else class="person-photo-placeholder flex flex-center bg-grey-8 rounded-borders">
            <q-icon name="mdi-account" size="96px" color="grey-6" />
          </div>
        </div>

        <!-- Person Info -->
        <div class="col">
          <h3 class="text-white q-mt-none q-mb-sm">{{ person.name }}</h3>
          <div v-if="person.known_for_department" class="text-grey-5 text-subtitle1 q-mb-sm">
            {{ person.known_for_department }}
          </div>

          <div v-if="person.external_links?.length" class="person-links q-mb-md">
            <q-btn
              v-for="link in person.external_links"
              :key="`${link.provider}:${link.provider_id || link.url}`"
              :label="link.display_name"
              :href="safeExternalHref(link.url)"
              target="_blank"
              rel="noopener noreferrer"
              icon-right="mdi-open-in-new"
              color="blue-grey-7"
              text-color="white"
              no-caps
              dense
            />
          </div>

          <!-- Biography metadata -->
          <div v-if="person.birthday || person.place_of_birth" class="q-mb-md">
            <div v-if="person.birthday" class="text-grey-5 text-body2">
              <q-icon name="mdi-cake-variant" size="xs" class="q-mr-xs" />
              {{ formatAirDate(person.birthday) }}
              <span v-if="person.deathday"> — {{ formatAirDate(person.deathday) }}</span>
              <span v-else-if="age"> ({{ age }})</span>
            </div>
            <div v-if="person.place_of_birth" class="text-grey-5 text-body2 q-mt-xs">
              <q-icon name="mdi-map-marker" size="xs" class="q-mr-xs" />
              {{ person.place_of_birth }}
            </div>
          </div>

          <!-- Biography -->
          <div v-if="person.biography" class="q-mb-md">
            <p
              class="text-grey-3 text-body2 person-biography"
              :class="{ 'biography-collapsed': !biographyExpanded }"
            >
              {{ person.biography }}
            </p>
            <q-btn
              v-if="person.biography.length > 500"
              flat
              dense
              size="sm"
              color="primary"
              :label="
                biographyExpanded
                  ? $t('common.showLess', 'Show less')
                  : $t('common.showMore', 'Show more')
              "
              @click="biographyExpanded = !biographyExpanded"
            />
          </div>

          <!-- Import status -->
          <div v-if="!person.metadata_imported && person.tmdb_id" class="q-mb-sm">
            <q-chip color="info" text-color="white" icon="mdi-download" size="sm">
              {{ $t('person.importingFilmography', 'Importing filmography...') }}
            </q-chip>
          </div>
        </div>
      </div>

      <!-- Filmography -->
      <div class="credits-section">
        <!-- Movies -->
        <div v-if="movieCredits.length > 0" class="q-mb-xl">
          <h5 class="text-white q-mb-md">
            {{ $t('person.movies', 'Movies') }}
            <q-badge color="grey-7" class="q-ml-sm">{{ movieCredits.length }}</q-badge>
          </h5>
          <div class="credits-grid">
            <div v-for="credit in movieCredits" :key="credit.media_item?.guid" class="credit-item">
              <PosterCard
                type="movie"
                :title="credit.media_item?.title || '—'"
                :image-url="
                  posterUrl(
                    credit.media_item,
                    () =>
                      credit.media_item?.poster_path
                        ? getTmdbImageUrl(credit.media_item.poster_path, 'w300')
                        : null,
                  )
                "
                :subtitle="credit.roles?.join(', ')"
                @click="navigateToMedia(credit)"
              />
            </div>
          </div>
        </div>

        <!-- Shows -->
        <div v-if="showCredits.length > 0" class="q-mb-xl">
          <h5 class="text-white q-mb-md">
            {{ $t('person.shows', 'TV Shows') }}
            <q-badge color="grey-7" class="q-ml-sm">{{ showCredits.length }}</q-badge>
          </h5>
          <div class="credits-grid">
            <div v-for="credit in showCredits" :key="credit.media_item?.guid" class="credit-item">
              <PosterCard
                type="show"
                :title="credit.media_item?.title || '—'"
                :image-url="
                  posterUrl(
                    credit.media_item,
                    () =>
                      credit.media_item?.poster_path
                        ? getTmdbImageUrl(credit.media_item.poster_path, 'w300')
                        : null,
                  )
                "
                :subtitle="credit.roles?.join(', ')"
                @click="navigateToMedia(credit)"
              />
            </div>
          </div>
        </div>

        <!-- Loading filmography indicator -->
        <div v-if="creditsLoading" class="text-center q-pa-lg">
          <q-spinner-dots color="primary" size="32px" />
          <div class="text-grey-5 q-mt-sm">
            {{ $t('person.loadingCredits', 'Loading filmography...') }}
          </div>
        </div>

        <!-- Empty state -->
        <div
          v-else-if="credits.length === 0 && !creditsLoading"
          class="text-grey-5 q-mt-lg text-center"
        >
          <q-icon name="mdi-movie-open-outline" size="3em" class="q-mb-sm" />
          <div>{{ $t('person.noCredits', 'No filmography available yet.') }}</div>
          <q-btn
            v-if="person.tmdb_id && !person.metadata_imported"
            flat
            color="primary"
            icon="mdi-refresh"
            :label="$t('person.refreshFilmography', 'Refresh')"
            class="q-mt-md"
            :loading="refreshing"
            @click="refreshFilmography"
          />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  getPerson,
  getPersonCredits,
  importPersonFilmography,
} from 'src/services/userMediaService'
import { getTmdbImageUrl, formatAirDate } from 'src/composables/useMediaFormatters'
import { posterUrl } from 'src/utils/posters'
import { safeExternalHref } from 'src/composables/useExternalLinks'
import { useWebSocket } from 'src/composables/useWebSocket'
import PosterCard from 'components/PosterCard.vue'
import { logger } from 'src/utils/logger'

const route = useRoute()
const router = useRouter()

const loading = ref(true)
const creditsLoading = ref(false)
const error = ref(null)
const person = ref(null)
const credits = ref([])
const biographyExpanded = ref(false)
const refreshing = ref(false)
let pollTimer = null
// Tracks the "final catch-up" reload scheduled after import completes so it can
// be cancelled on route change / unmount instead of firing on a torn-down page.
let finalReloadTimer = null

const age = computed(() => {
  if (!person.value?.birthday || person.value?.deathday) return null
  const birth = new Date(person.value.birthday)
  const now = new Date()
  let a = now.getFullYear() - birth.getFullYear()
  const m = now.getMonth() - birth.getMonth()
  if (m < 0 || (m === 0 && now.getDate() < birth.getDate())) a--
  return a
})

// Deduplicate credits by media_item.guid and merge roles
function deduplicateCredits(filtered) {
  const map = new Map()
  for (const c of filtered) {
    const key = c.media_item?.guid
    if (!key) continue
    if (map.has(key)) {
      const existing = map.get(key)
      // Merge roles
      const role = c.character || c.job
      if (role && !existing.roles.includes(role)) {
        existing.roles.push(role)
      }
    } else {
      map.set(key, {
        ...c,
        roles: [c.character || c.job].filter(Boolean),
      })
    }
  }
  return [...map.values()].sort((a, b) => {
    const yearA = a.media_item?.release_date?.substring(0, 4) || '0000'
    const yearB = b.media_item?.release_date?.substring(0, 4) || '0000'
    return yearB.localeCompare(yearA)
  })
}

const movieCredits = computed(() =>
  deduplicateCredits(credits.value.filter((c) => c.media_item?.media_type === 'MOVIES')),
)

const showCredits = computed(() =>
  deduplicateCredits(credits.value.filter((c) => c.media_item?.media_type === 'SHOWS')),
)

async function loadPerson() {
  const guid = route.params.guid
  if (!guid) return

  loading.value = true
  error.value = null

  try {
    // Load person details (auto-triggers filmography import on backend if needed)
    const personData = await getPerson(guid)
    // Bail if the user navigated to a different person while this was in flight,
    // so a slower response can't overwrite the newer person's state.
    if (route.params.guid !== guid) return
    person.value = personData

    // Load credits (includes media_item data now - no N+1)
    await loadCredits(guid)
    if (route.params.guid !== guid) return

    // If filmography not yet imported, poll for updates
    if (person.value.tmdb_id && !person.value.metadata_imported) {
      startPolling(guid)
    }
  } catch (err) {
    if (route.params.guid !== guid) return
    logger.error('Failed to load person', err)
    error.value = err.response?.data?.detail || 'Failed to load person'
  } finally {
    if (route.params.guid === guid) loading.value = false
  }
}

async function loadCredits(guid) {
  creditsLoading.value = true
  try {
    const creditsData = await getPersonCredits(guid)
    if (route.params.guid !== guid) return
    credits.value = creditsData
  } catch (err) {
    logger.error('Failed to load credits:', err)
  } finally {
    if (route.params.guid === guid) creditsLoading.value = false
  }
}

function startPolling(guid) {
  stopPolling()
  let pollCount = 0
  const maxPolls = 20 // Poll for max ~2 minutes

  pollTimer = setInterval(async () => {
    pollCount++
    if (pollCount >= maxPolls) {
      stopPolling()
      return
    }

    try {
      // Re-check person status
      const personData = await getPerson(guid)
      // Stop applying poll results once the user has navigated away.
      if (route.params.guid !== guid) {
        stopPolling()
        return
      }
      person.value = personData

      // Reload credits to pick up newly imported media
      const newCredits = await getPersonCredits(guid)
      if (route.params.guid !== guid) {
        stopPolling()
        return
      }

      if (newCredits.length > credits.value.length) {
        credits.value = newCredits
      }

      // Stop polling once metadata is imported
      if (person.value.metadata_imported) {
        // Stop the interval first, then schedule one final reload to catch last
        // imports. Tracking the timer lets stopPolling() cancel it on route
        // change / unmount so it never writes state on a torn-down page.
        stopPolling()
        finalReloadTimer = setTimeout(async () => {
          finalReloadTimer = null
          try {
            const finalCredits = await getPersonCredits(guid)
            if (route.params.guid !== guid) return
            credits.value = finalCredits
          } catch {
            // Ignore final reload errors
          }
        }, 3000)
      }
    } catch {
      // Ignore polling errors
    }
  }, 6000) // Poll every 6 seconds
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
  if (finalReloadTimer) {
    clearTimeout(finalReloadTimer)
    finalReloadTimer = null
  }
}

async function refreshFilmography() {
  if (!person.value?.guid) return
  refreshing.value = true
  try {
    await importPersonFilmography(person.value.guid)
    startPolling(person.value.guid)
  } catch (err) {
    logger.error('Failed to trigger filmography import:', err)
  } finally {
    refreshing.value = false
  }
}

function navigateToMedia(credit) {
  if (credit.media_item?.guid) {
    router.push(`/media/${credit.media_item.guid}`)
  }
}

const { subscribe, unsubscribe } = useWebSocket()
let wsHandler = null
// The guid we actually subscribed with, so unsubscribe always targets the same
// key even if the person fetch failed or the route changed since.
let wsSubscribedGuid = null

function teardownWebSocket() {
  if (wsHandler && wsSubscribedGuid) {
    unsubscribe('person', wsSubscribedGuid, wsHandler)
  }
  wsHandler = null
  wsSubscribedGuid = null
}

function setupWebSocket(guid) {
  teardownWebSocket()
  wsHandler = (event) => {
    if (event === 'person_credits_updated') {
      logger.debug('[PersonPage] Credits updated via WebSocket, reloading...')
      loadCredits(guid)
    }
  }
  subscribe('person', guid, wsHandler)
  wsSubscribedGuid = guid
}

watch(
  () => route.params.guid,
  (newGuid) => {
    stopPolling()
    teardownWebSocket()
    loadPerson()
    if (newGuid) setupWebSocket(newGuid)
  },
  { immediate: true },
)

onUnmounted(() => {
  stopPolling()
  teardownWebSocket()
})
</script>

<style lang="scss" scoped>
.person-page {
  min-height: 100vh;
  background: $dark;
}

.person-content {
  max-width: 1400px;
  margin: 0 auto;
}

.person-photo-container {
  width: 220px;
  min-width: 220px;
}

.person-photo {
  border-radius: 12px;
}

.person-photo-placeholder {
  width: 100%;
  aspect-ratio: 2 / 3;
  border-radius: 12px;
}

.person-biography {
  line-height: 1.6;
  white-space: pre-line;
}

.person-links {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.biography-collapsed {
  max-height: 120px;
  overflow: hidden;
  mask-image: linear-gradient(to bottom, black 60%, transparent 100%);
  -webkit-mask-image: linear-gradient(to bottom, black 60%, transparent 100%);
}

.credits-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 1rem;
}

.credit-card {
  border-radius: 8px;
  overflow: hidden;
  transition: transform 0.2s;

  &:hover {
    transform: translateY(-4px);
  }
}

.credit-poster {
  border-radius: 8px 8px 0 0;
}

.credit-poster-placeholder {
  width: 100%;
  aspect-ratio: 2 / 3;
  border-radius: 8px 8px 0 0;
}

@media (max-width: 768px) {
  .person-photo-container {
    width: 150px;
    min-width: 150px;
  }

  .person-content {
    padding: 16px !important;
  }

  .credits-grid {
    grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
  }
}
</style>
