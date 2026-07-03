<template>
  <q-layout view="lHh Lpr lFf">
    <q-header class="bg-dark">
      <q-toolbar>
        <q-btn
          flat
          dense
          round
          icon="mdi-menu"
          :aria-label="$t('drawer.menu')"
          @click="toggleLeftDrawer"
        />

        <!-- Normal mode: Show title and other elements -->
        <template v-if="!searchMode">
          <q-toolbar-title> {{ settingsStore.getSiteName }} </q-toolbar-title>

          <q-space />

          <PartyButton />

          <RemoteControlButton />

          <UserMenu />

          <q-btn
            v-if="authStore.isAdmin && layoutExists"
            flat
            dense
            round
            :icon="layoutEditMode ? 'mdi-pencil-off' : 'mdi-pencil'"
            :color="layoutEditMode ? 'positive' : undefined"
            @click="layoutEditMode = !layoutEditMode"
          >
            <q-tooltip>{{
              layoutEditMode ? $t('pageLayouts.exitEditMode') : $t('pageLayouts.editLayout')
            }}</q-tooltip>
          </q-btn>

          <q-btn
            flat
            dense
            round
            icon="mdi-magnify"
            :aria-label="$t('moviesPage.search')"
            @click="openSearch"
          />
        </template>

        <!-- Search mode: Show search input -->
        <template v-else>
          <q-input
            ref="searchInputRef"
            v-model="searchQuery"
            class="full-width-search q-ml-sm"
            :placeholder="$t('indexPage.searchPlaceholder')"
            dense
            standout
            borderless
            dark
            @keyup.escape="closeSearch"
          >
            <template v-slot:prepend>
              <q-icon name="mdi-magnify" color="white" />
            </template>
            <template v-slot:append>
              <q-btn
                v-if="searchQuery"
                flat
                round
                dense
                icon="mdi-delete"
                color="white"
                @click="clearSearch"
              />
              <q-btn flat round dense icon="mdi-close" color="white" @click="closeSearch" />
            </template>
            <q-menu
              v-model="showSearchSuggestions"
              anchor="bottom left"
              self="top left"
              fit
              no-focus
              class="search-suggestions-menu"
            >
              <q-list dense class="search-suggestions-list">
                <q-item
                  v-for="suggestion in typedSuggestions"
                  :key="`${suggestion.type}:${suggestion.value}`"
                  clickable
                  @click="selectSearchSuggestion(suggestion)"
                >
                  <q-item-section avatar>
                    <q-icon :name="suggestionIcon(suggestion)" color="primary" />
                  </q-item-section>
                  <q-item-section>
                    <q-item-label lines="1">{{ suggestion.label }}</q-item-label>
                    <q-item-label caption lines="1">
                      {{ $t(suggestionTypeLabelKey(suggestion)) }}
                      <span v-if="suggestion.count"> · {{ suggestion.count }}</span>
                    </q-item-label>
                  </q-item-section>
                </q-item>
              </q-list>
            </q-menu>
          </q-input>
        </template>
      </q-toolbar>
    </q-header>

    <q-drawer v-model="leftDrawerOpen" bordered>
      <q-list dense>
        <q-item-label header>{{ $t('drawer.menu') }}</q-item-label>
        <DrawerItem icon="mdi-home" :title="$t('home')" to="/" />
        <DrawerItem icon="mdi-history" :title="$t('viewingHistory.drawerTitle')" to="/history" />
        <q-item-label header>{{ $t('drawer.libraries') }}</q-item-label>
        <DrawerItem v-for="link in linksList" :key="link.title" v-bind="link" />
      </q-list>

      <q-list separator dense v-if="authStore.isLoggedIn">
        <q-item-label header class="row items-center justify-between">
          {{ $t('drawer.myLists') }}
          <q-btn flat dense round size="sm" icon="mdi-plus" @click="createNewList">
            <q-tooltip>
              {{ $t('drawer.createNewList') }}
            </q-tooltip>
          </q-btn>
        </q-item-label>
        <q-tabs
          v-model="listTypeFilter"
          dense
          class="text-grey list-filter-tabs"
          active-color="primary"
          indicator-color="primary"
          align="justify"
          narrow-indicator
          no-caps
          inline-label
        >
          <q-tab name="" :label="$t('drawer.filterAll')" class="list-filter-tab">
            <q-tooltip>{{ $t('drawer.filterAll') }}</q-tooltip>
          </q-tab>
          <q-tab
            v-for="tab in listFilterTabs"
            :key="tab.name"
            :name="tab.name"
            :icon="tab.icon"
            class="list-filter-tab"
          >
            <q-tooltip>{{ tab.label }}</q-tooltip>
          </q-tab>
        </q-tabs>
        <q-item v-if="listsLoading">
          <q-item-section avatar>
            <q-spinner color="primary" size="sm" />
          </q-item-section>
          <q-item-section>
            <q-item-label>{{ $t('drawer.loadingLists') }}</q-item-label>
          </q-item-section>
        </q-item>
        <q-separator />
        <q-item
          v-for="list in filteredUserLists"
          :key="list.guid"
          clickable
          tag="a"
          dense
          :to="`/lists/${list.guid}`"
        >
          <q-item-section avatar>
            <q-icon name="mdi-format-list-bulleted" />
          </q-item-section>
          <q-item-section>
            <q-item-label>{{ list.name }}</q-item-label>
          </q-item-section>
        </q-item>

        <q-item v-if="!listsLoading && filteredUserLists.length === 0" disable>
          <q-item-section class="text-center">
            <q-item-label class="text-grey-6">{{ $t('drawer.noLists') }}</q-item-label>
            <q-item-label caption>{{ $t('drawer.createFirstList') }}</q-item-label>
          </q-item-section>
        </q-item>
      </q-list>
    </q-drawer>

    <q-page-container :style="audioPlayerPadding">
      <!-- Global Banners -->
      <GlobalBanners />
      <FriendRequestBanner />

      <router-view />
    </q-page-container>

    <AudioPlayer />
  </q-layout>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch, computed, nextTick } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from 'src/stores/auth'
import { useListsStore } from 'src/stores/lists'
import { useSettingsStore } from 'src/stores/settings'
import DrawerItem from 'components/DrawerItem.vue'
import UserMenu from 'components/UserMenu.vue'
import PartyButton from 'components/PartyButton.vue'
import RemoteControlButton from 'components/RemoteControlButton.vue'
import GlobalBanners from 'components/GlobalBanners.vue'
import FriendRequestBanner from 'components/FriendRequestBanner.vue'
import AudioPlayer from 'components/AudioPlayer.vue'
import { useAudioPlayerStore } from 'src/stores/audioPlayer'
import { logger } from 'src/utils/logger'
import { layoutEditMode, layoutExists } from 'src/composables/useLayoutEditor'
import { useTypedAutocomplete } from 'src/composables/useTypedAutocomplete'

const router = useRouter()
const route = useRoute()
const $q = useQuasar()
const { t } = useI18n()
const authStore = useAuthStore()
const listsStore = useListsStore()
const settingsStore = useSettingsStore()
const audioPlayerStore = useAudioPlayerStore()

const audioPlayerPadding = computed(() => ({
  paddingBottom: audioPlayerStore.isVisible ? '68px' : '0px',
}))

// Search functionality
const searchQuery = ref('')
const searchMode = ref(false)
const searchInputRef = ref(null)
let searchDebounceTimer = null
const {
  suggestions: typedSuggestions,
  fetchSuggestions,
  clearSuggestions: clearTypedSuggestions,
  navigateSuggestion: navigateTypedSuggestion,
  suggestionIcon,
  suggestionTypeLabelKey,
} = useTypedAutocomplete(router)
const showSearchSuggestions = computed({
  get: () => searchMode.value && typedSuggestions.value.length > 0,
  set: (visible) => {
    if (!visible) clearTypedSuggestions()
  },
})

// Watch route changes - close search when navigating away from search results
watch(
  () => route.path,
  (newPath) => {
    if (newPath !== '/search' && searchMode.value) {
      // Clear debounce timer
      if (searchDebounceTimer) {
        clearTimeout(searchDebounceTimer)
      }
      searchMode.value = false
      searchQuery.value = ''
    }
  },
)

// Debounced search - navigates to search results page after typing
watch(searchQuery, (newQuery) => {
  // Clear existing timer
  if (searchDebounceTimer) {
    clearTimeout(searchDebounceTimer)
  }

  // Only search if query is at least 2 characters
  const term = newQuery.trim()
  if (term.length >= 2) {
    fetchSuggestions(term)
    searchDebounceTimer = setTimeout(() => {
      router.push({
        path: '/search',
        query: { q: term },
      })
    }, 200) // 200ms debounce
  } else {
    clearTypedSuggestions()
  }
})

const linksList = computed(() => {
  logger.debug('[MainLayout] Computing linksList')
  logger.debug('[MainLayout] availableLibrariesLoaded:', settingsStore.availableLibrariesLoaded)
  logger.debug('[MainLayout] availableLibraries:', settingsStore.availableLibraries)

  // If configured libraries are loaded, use them
  if (settingsStore.availableLibrariesLoaded && settingsStore.availableLibraries.length > 0) {
    logger.debug('[MainLayout] Using configured libraries')
    // Map library type to icon
    const iconMap = {
      MOVIES: 'mdi-movie',
      SHOWS: 'mdi-television-classic',
      MUSIC: 'mdi-music',
      GAMES: 'mdi-gamepad-variant',
      BOOKS: 'mdi-book-open-page-variant',
    }

    // Map library type to translation key
    const titleMap = {
      MOVIES: 'movies',
      SHOWS: 'shows',
      MUSIC: 'music',
      GAMES: 'games',
      BOOKS: 'books',
    }

    // Filter by enabled + user's allowed_libraries permission
    const allowedLibs = authStore.user?.allowed_libraries || null
    return settingsStore.availableLibraries
      .filter((library) => library.enabled)
      .filter(
        (library) => !allowedLibs || allowedLibs.length === 0 || allowedLibs.includes(library.type),
      )
      .map((library) => ({
        title: t(titleMap[library.type] || library.type),
        icon: iconMap[library.type] || 'mdi-folder',
        link: `/${library.type.toLowerCase()}`,
        enabled: true,
      }))
  }

  logger.debug('[MainLayout] No configured libraries, showing empty navigation')
  // Return empty array if no libraries configured
  return []
})

const leftDrawerOpen = ref(false)

// Search functions
function openSearch() {
  searchMode.value = true
  // Focus input after it becomes visible
  nextTick(() => {
    if (searchInputRef.value) {
      searchInputRef.value.focus()
    }
  })
}

function closeSearch() {
  searchMode.value = false
  // Clear debounce timer when closing
  if (searchDebounceTimer) {
    clearTimeout(searchDebounceTimer)
  }
  clearTypedSuggestions()
  searchQuery.value = ''
}

function clearSearch() {
  // Clear debounce timer when clearing
  if (searchDebounceTimer) {
    clearTimeout(searchDebounceTimer)
  }
  clearTypedSuggestions()
  searchQuery.value = ''
}

async function selectSearchSuggestion(suggestion) {
  if (searchDebounceTimer) {
    clearTimeout(searchDebounceTimer)
  }
  await navigateTypedSuggestion(suggestion)
  searchMode.value = false
  searchQuery.value = ''
  clearTypedSuggestions()
}

// Use computed properties to get reactive data from stores
const listTypeFilter = ref('')

// Map library types to ListItemType filter values
const listFilterTabs = computed(() => {
  const typeToTab = {
    MOVIES: { name: 'MOVIE', icon: 'mdi-movie', label: t('movies') },
    SHOWS: { name: 'SHOW', icon: 'mdi-television', label: t('shows') },
    GAMES: { name: 'GAME', icon: 'mdi-gamepad-variant', label: t('games') },
    MUSIC: { name: 'MUSIC', icon: 'mdi-music', label: t('music') },
    BOOKS: { name: 'BOOK', icon: 'mdi-book-open', label: t('books') },
  }
  if (!settingsStore.availableLibrariesLoaded) return []
  return settingsStore.availableLibraries
    .filter((lib) => lib.enabled && typeToTab[lib.type])
    .map((lib) => typeToTab[lib.type])
})

const userLists = computed(() => listsStore.getUserLists)

const filteredUserLists = computed(() => {
  if (!listTypeFilter.value) return userLists.value
  return userLists.value.filter(
    (list) => list.item_types && list.item_types.includes(listTypeFilter.value),
  )
})
const listsLoading = computed(() => listsStore.isLoading)

function toggleLeftDrawer() {
  leftDrawerOpen.value = !leftDrawerOpen.value
}

function navigateToList(listGuid) {
  router.push(`/lists/${listGuid}`)
}

async function createNewList() {
  $q.dialog({
    title: t('settings.createListTitle'),
    message: t('settings.createListMessage'),
    prompt: {
      model: '',
      type: 'text',
    },
    cancel: true,
    persistent: true,
  }).onOk(async (listName) => {
    if (!listName.trim()) return

    try {
      logger.debug('[MainLayout] Creating new list with name:', listName)

      const response = await listsStore.createList({
        name: listName.trim(),
        description: '',
        list_type: 'user',
        visibility: 'private',
      })

      logger.debug('[MainLayout] List created, response:', response)

      // Navigate to the new list
      if (response.guid) {
        navigateToList(response.guid)
      }
    } catch (error) {
      logger.error('Failed to create list:', error)
    }
  })
}

// Watch for authentication changes
watch(
  () => (authStore.isLoggedIn ? authStore.user?.guid || null : null),
  async (userGuid, previousGuid) => {
    logger.debug('[MainLayout] Active user changed:', previousGuid, '->', userGuid)

    if (userGuid === previousGuid) return

    if (userGuid) {
      // Fetch library settings when user logs in
      await settingsStore.fetchLibrariesSettings()
      await settingsStore.fetchAvailableLibraries()
      // Fetch subscription settings when user logs in
      await settingsStore.fetchSubscriptionSettings()
      // Fetch invite and friends settings when user logs in
      await settingsStore.fetchInviteSettings()
      await settingsStore.fetchFriendsSettings()
      await listsStore.fetchUserLists(userGuid)
    } else {
      listsStore.clearLists()
    }
  },
  { immediate: true },
)

// Global keyboard shortcut: '/' opens search
function handleGlobalKeydown(event) {
  // Ignore if search is already open
  if (searchMode.value) return

  // Ignore if focus is on an input, textarea, or contenteditable element
  const tag = document.activeElement?.tagName?.toLowerCase()
  const isEditable = document.activeElement?.isContentEditable
  if (tag === 'input' || tag === 'textarea' || tag === 'select' || isEditable) return

  if (event.key === '/') {
    event.preventDefault()
    openSearch()
  }
}

onMounted(async () => {
  document.addEventListener('keydown', handleGlobalKeydown)
  logger.debug('[MainLayout] Component mounted')
  logger.debug('[MainLayout] Auth status:', authStore.isLoggedIn)
  logger.debug('[MainLayout] User:', authStore.user)

  // Fetch system settings (site name)
  await settingsStore.fetchSiteName()
})

onUnmounted(() => {
  document.removeEventListener('keydown', handleGlobalKeydown)
  if (searchDebounceTimer) {
    clearTimeout(searchDebounceTimer)
  }
})
</script>

<style lang="scss" scoped>
.list-filter-tabs {
  min-height: 32px;
  margin-bottom: 8px;
}
.list-filter-tab {
  min-width: 0;
  padding: 0 6px;
  min-height: 32px;
}

// Full-width search input in toolbar
.full-width-search {
  flex: 1;
  max-width: none;

  &:deep(.q-field__control) {
    border-radius: 8px;
    background: rgba(255, 255, 255, 0.1);
    border: 1px solid rgba(255, 255, 255, 0.2);

    &:hover {
      background: rgba(255, 255, 255, 0.15);
      border-color: rgba(255, 255, 255, 0.3);
    }
  }

  &:deep(.q-field__native) {
    color: white;
    font-size: 16px;

    &::placeholder {
      color: rgba(255, 255, 255, 0.6);
    }
  }

  &:deep(.q-field__prepend),
  &:deep(.q-field__append) {
    .q-icon {
      color: rgba(255, 255, 255, 0.8);
    }

    .q-btn {
      transition: all 0.2s ease;

      &:hover {
        background: rgba(255, 255, 255, 0.1);
      }
    }
  }
}

.search-suggestions-menu {
  max-width: min(640px, calc(100vw - 32px));
}

.search-suggestions-list {
  min-width: 280px;
  max-height: 360px;
}
</style>
