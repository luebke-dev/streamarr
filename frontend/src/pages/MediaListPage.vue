<template>
  <div class="media-list-page">
    <!-- Loading layout -->
    <div v-if="loadingLayout" class="flex flex-center q-pa-xl" style="min-height: 50vh">
      <q-spinner-dots size="50px" color="primary" />
    </div>

    <!-- Render sections from layout config -->
    <template v-else-if="displaySections.length > 0">
      <template v-for="(section, idx) in displaySections" :key="section.guid">
        <!-- Add section button (before each section in edit mode) -->
        <AddSectionButton v-if="editor.editMode.value" :order-index="idx" />

        <!-- Section with optional edit overlay -->
        <SectionEditOverlay
          v-if="editor.editMode.value"
          :section="section"
          :index="idx"
          :is-first="idx === 0"
          :is-last="idx === displaySections.length - 1"
        >
          <SectionRenderer
            :section="section"
            :media-type="mediaType"
            :edit-mode="editor.editMode.value"
            @navigate-to-item="navigateToItem"
            @play-item="playItem"
          />
        </SectionEditOverlay>

        <SectionRenderer
          v-else
          :section="section"
          :media-type="mediaType"
          @navigate-to-item="navigateToItem"
          @play-item="playItem"
        />
      </template>

      <!-- Add section button at the end in edit mode -->
      <AddSectionButton v-if="editor.editMode.value" :order-index="displaySections.length" />
    </template>

    <!-- Admin empty state: no layout OR layout exists but has no sections.
         Branches on layoutExists to either create the layout row first or
         drop straight into edit mode with the "add section" dialog open. -->
    <div v-else-if="authStore.isAdmin" class="flex flex-center q-pa-xl" style="min-height: 50vh">
      <div class="text-center">
        <q-icon name="mdi-view-dashboard-outline" size="4em" color="grey-6" />
        <div class="text-h6 text-grey-5 q-mt-md">
          {{
            layoutExists
              ? $t('pageLayouts.emptyLayoutPrompt', 'This layout has no sections yet')
              : $t('pageLayouts.createLayoutPrompt')
          }}
        </div>
        <q-btn
          v-if="!layoutExists"
          color="primary"
          :label="$t('pageLayouts.createLayout')"
          icon="mdi-plus"
          class="q-mt-md"
          @click="createLayoutForPage"
          :loading="creatingLayout"
        />
        <q-btn
          v-else
          color="primary"
          :label="$t('pageLayouts.addSection', 'Add Section')"
          icon="mdi-plus"
          class="q-mt-md"
          @click="enterEditAndAddSection"
        />
      </div>
    </div>

    <!-- Fallback: non-admin, no layout / no sections -->
    <div v-else class="flex flex-center q-pa-xl">
      <div class="text-center text-grey-5">
        <q-icon name="mdi-view-dashboard-outline" size="4em" />
        <div class="q-mt-md">
          {{ $t('common.noLayoutConfigured', 'No page layout configured') }}
        </div>
      </div>
    </div>

    <!-- Section config dialog -->
    <SectionConfigDialog
      v-model="editor.showConfigDialog.value"
      :section="editor.editingSection.value"
      :genre-options="editor.genreOptions.value"
      :list-options="editor.listOptions.value"
      :platform-options="editor.platformOptions.value"
      :saving="editor.savingSection.value"
      @save="editor.saveSection"
    />

    <!-- IGDB Search Dialog (Games only) -->
    <q-dialog v-if="isGames" v-model="showIgdbSearch" persistent>
      <q-card dark style="min-width: 600px">
        <q-card-section>
          <div class="text-h6">{{ $t('game.searchIGDB') }}</div>
        </q-card-section>

        <q-card-section class="q-pt-none">
          <q-input
            v-model="igdbSearchQuery"
            :label="$t('game.searchForGames')"
            outlined
            @keyup.enter="searchIgdb"
          />
        </q-card-section>

        <q-card-actions align="right">
          <q-btn flat :label="$t('common.cancel')" color="grey-7" v-close-popup />
          <q-btn
            :label="$t('common.search')"
            color="primary"
            @click="searchIgdb"
            :loading="searchingIgdb"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { api } from 'boot/axios'
import { cachedApiGet } from 'src/composables/useApiResponseCache'
import { MediaTypes, getMediaItemChildren } from 'src/composables/useUnifiedMedia'
import { useAuthStore } from 'src/stores/auth'
import {
  useLayoutEditor,
  provideLayoutEditor,
  layoutExists as sharedLayoutExists,
} from 'src/composables/useLayoutEditor'
import SectionRenderer from 'src/components/sections/SectionRenderer.vue'
import SectionEditOverlay from 'src/components/sections/SectionEditOverlay.vue'
import AddSectionButton from 'src/components/sections/AddSectionButton.vue'
import SectionConfigDialog from 'src/components/sections/SectionConfigDialog.vue'
import { logger } from 'src/utils/logger'

const route = useRoute()
const router = useRouter()
useI18n()
const authStore = useAuthStore()
const editor = useLayoutEditor()
provideLayoutEditor(editor)

// Layout state
const loadingLayout = ref(false)
const layoutSections = ref([])
const layoutExists = sharedLayoutExists
const isFallbackLayout = ref(false)
const creatingLayout = ref(false)

// Check if this is the home page
const isHomePage = computed(() => route.path === '/' || route.meta.isHome)

// Media type from route param (e.g. /movies → 'MOVIES')
const mediaType = computed(() => {
  if (isHomePage.value) return null
  const param = route.params.mediaType
  return param ? param.toUpperCase() : null
})

const isGames = computed(() => mediaType.value === MediaTypes.GAMES)

// Sections to display: edit mode shows all (from editor), normal mode shows enabled only
const displaySections = computed(() => {
  if (editor.editMode.value) return editor.allSections.value
  return layoutSections.value
})

// Games-specific state
const showIgdbSearch = ref(false)
const igdbSearchQuery = ref('')
const searchingIgdb = ref(false)
// Deferred layout refresh after an IGDB import; tracked so it can be cancelled
// on unmount / route change instead of writing state on a departed page.
let igdbRefreshTimer = null

// Navigate to item detail page
function navigateToItem(guidOrItem) {
  const guid = typeof guidOrItem === 'string' ? guidOrItem : guidOrItem.guid
  router.push(`/media/${guid}`)
}

// Play item
async function playItem(item) {
  if (!item || !item.guid) return

  const type = getItemTypeSingular(item)

  if (type === 'show') {
    try {
      const resumeRes = await api.get(`/api/media/shows/${item.guid}/resume`)
      if (resumeRes.data?.episode?.guid) {
        router.push(`/play/${resumeRes.data.episode.guid}?type=episode`)
        return
      }
    } catch {
      // fallback below
    }

    try {
      const seasons = (await getMediaItemChildren(item.guid, true)) || []
      if (seasons.length === 0) {
        return
      }
      const firstSeason = seasons.find((s) => s.sequence_number === 1) || seasons[0]
      const episodes = (await getMediaItemChildren(firstSeason.guid, true)) || []
      if (episodes.length === 0) {
        return
      }
      const firstEpisode = episodes.find((e) => e.sequence_number === 1) || episodes[0]
      router.push(`/play/${firstEpisode.guid}?type=episode`)
    } catch (err) {
      logger.error('Error starting show playback:', err)
    }
    return
  }

  const playType = type === 'game' ? 'game' : 'movie'
  router.push(`/play/${item.guid}?type=${playType}`)
}

function getItemTypeSingular(item) {
  if (!item) return 'movie'
  const type = (item.media_type || item.type || '').toUpperCase()
  if (type === 'MOVIES' || type === 'MOVIE') return 'movie'
  if (type === 'SHOWS' || type === 'SHOW') return 'show'
  if (type === 'GAMES' || type === 'GAME') return 'game'
  if (type === 'MUSIC') return 'music'
  if (type === 'BOOKS' || type === 'BOOK') return 'book'
  return 'movie'
}

// Load page layout from API
async function loadLayout() {
  loadingLayout.value = true
  editor.editMode.value = false
  try {
    let response
    const fetchLayout = authStore.isAdmin ? api.get : cachedApiGet
    const renderedSuffix = authStore.isAdmin ? '' : '/rendered'
    if (mediaType.value) {
      response = await fetchLayout(
        `/api/page-layouts/media-type/${mediaType.value.toLowerCase()}${renderedSuffix}`,
        {},
        { ttlMs: 5 * 60_000, staleTtlMs: 30 * 60_000 },
      )
    } else {
      response = await fetchLayout(
        `/api/page-layouts/slug/home${renderedSuffix}`,
        {},
        { ttlMs: 5 * 60_000, staleTtlMs: 30 * 60_000 },
      )
    }
    const layout = response.data
    layoutExists.value = true

    // Check if this is a fallback layout (slug doesn't match current page)
    const expectedSlug = mediaType.value ? mediaType.value.toLowerCase() : 'home'
    const isFallback = mediaType.value && layout.slug !== expectedSlug
    isFallbackLayout.value = isFallback

    const allSections = (layout.sections || []).sort((a, b) => a.order_index - b.order_index)
    layoutSections.value = allSections.filter((s) => s.is_enabled)

    // Initialize editor — but not with fallback layout guid
    if (!isFallback) {
      editor.init(layout.guid, allSections)
    }
  } catch (error) {
    if (error.response?.status === 404) {
      layoutExists.value = false
      layoutSections.value = []
    } else {
      logger.error('Error loading page layout:', error)
      // Fallback: use default sections if API fails
      layoutSections.value = [
        {
          guid: 'fallback-hero',
          section_type: 'hero_carousel',
          order_index: 0,
          title: null,
          config: {},
          is_enabled: true,
        },
        {
          guid: 'fallback-cw',
          section_type: 'continue_watching',
          order_index: 1,
          title: null,
          config: {},
          is_enabled: true,
        },
        {
          guid: 'fallback-fav',
          section_type: 'favorites',
          order_index: 2,
          title: null,
          config: {},
          is_enabled: true,
        },
        {
          guid: 'fallback-latest',
          section_type: 'latest_items',
          order_index: 3,
          title: null,
          config: { max_items: 20 },
          is_enabled: true,
        },
        {
          guid: 'fallback-trailers',
          section_type: 'trailers',
          order_index: 4,
          title: null,
          config: { max_items: 20 },
          is_enabled: true,
        },
        {
          guid: 'fallback-genres',
          section_type: 'all_genres',
          order_index: 5,
          title: null,
          config: { max_items_per_genre: 10 },
          is_enabled: true,
        },
      ]
      layoutExists.value = true
    }
  } finally {
    loadingLayout.value = false
  }
}

// Create layout for this page
async function createLayoutForPage() {
  creatingLayout.value = true
  try {
    const slug = mediaType.value ? mediaType.value.toLowerCase() : 'home'
    const name = mediaType.value
      ? mediaType.value.charAt(0) + mediaType.value.slice(1).toLowerCase()
      : 'Home'
    await editor.createLayout(name, slug)
    layoutExists.value = true
  } catch (error) {
    // 409 = layout already exists for this slug; don't crash, just enter
    // edit mode on the existing one. Backend now returns the existing
    // layout's guid in the error detail so the editor can take it from there.
    const existingGuid = error?.response?.data?.detail?.existing_layout_guid
    if (error?.response?.status === 409 && existingGuid) {
      logger.info('Layout already exists; switching into edit mode')
      editor.init(existingGuid, [])
      editor.editMode.value = true
      layoutExists.value = true
    } else {
      logger.error('Error creating layout:', error)
    }
  } finally {
    creatingLayout.value = false
  }
}

// Drop into edit mode and immediately open the "add section" dialog so the
// admin doesn't have to hunt for the right button on an empty layout.
function enterEditAndAddSection() {
  editor.editMode.value = true
  editor.openAddDialog(0)
}

// When edit mode is activated on a fallback layout, create a page-specific layout first
watch(
  () => editor.editMode.value,
  async (active) => {
    if (active && isFallbackLayout.value) {
      const slug = mediaType.value ? mediaType.value.toLowerCase() : 'home'
      const name = mediaType.value
        ? mediaType.value.charAt(0) + mediaType.value.slice(1).toLowerCase()
        : 'Home'
      await editor.createLayout(name, slug)
      isFallbackLayout.value = false
      layoutExists.value = true
    }
  },
)

// Sync editor changes back to the normal display sections
watch(
  () => editor.allSections.value,
  (sections) => {
    layoutSections.value = sections.filter((s) => s.is_enabled)
  },
  { deep: true },
)

// IGDB Search
async function searchIgdb() {
  if (!igdbSearchQuery.value.trim()) return
  searchingIgdb.value = true
  try {
    await api.post('/api/games/search-igdb', { query: igdbSearchQuery.value })
    showIgdbSearch.value = false
    igdbSearchQuery.value = ''
    if (igdbRefreshTimer) clearTimeout(igdbRefreshTimer)
    igdbRefreshTimer = setTimeout(() => {
      igdbRefreshTimer = null
      loadLayout()
    }, 2000)
  } catch (error) {
    logger.error('Error searching IGDB:', error)
  } finally {
    searchingIgdb.value = false
  }
}

// Initialize
onMounted(async () => {
  loadLayout()
})

// Watch for route changes
watch(
  () => route.params.mediaType,
  () => {
    if (igdbRefreshTimer) {
      clearTimeout(igdbRefreshTimer)
      igdbRefreshTimer = null
    }
    layoutSections.value = []
    loadLayout()
  },
)

onUnmounted(() => {
  if (igdbRefreshTimer) {
    clearTimeout(igdbRefreshTimer)
    igdbRefreshTimer = null
  }
})
</script>

<style lang="scss" scoped>
.media-list-page {
  min-height: 100vh;
  background: $dark;
  padding-bottom: 2rem;
}
</style>
