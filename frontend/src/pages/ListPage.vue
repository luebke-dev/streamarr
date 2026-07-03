<template>
  <div class="list-detail-page q-pa-md">
    <!-- Loading Indicator -->
    <div v-if="loading" class="flex flex-center" style="min-height: 70vh">
      <q-spinner-dots size="50px" color="primary" />
    </div>

    <!-- Error State -->
    <div v-else-if="error" class="flex flex-center" style="min-height: 70vh">
      <div class="text-center">
        <q-icon name="mdi-alert-circle" size="4em" color="negative" />
        <div class="text-h6 text-negative q-mt-md">{{ error }}</div>
        <q-btn
          color="primary"
          :label="$t('listPage.backToLists')"
          @click="$router.push('/')"
          class="q-mt-md"
        />
      </div>
    </div>

    <!-- List Details -->
    <div v-else-if="list">
      <!-- Page Header -->
      <div class="list-header q-mb-lg">
        <div class="row items-center q-mb-sm">
          <q-btn
            flat
            round
            icon="mdi-arrow-left"
            color="grey-4"
            :title="$t('listPage.backToLists')"
            @click="$router.go(-1)"
            class="q-mr-sm"
          />
          <div class="col">
            <div class="text-h5 text-white text-weight-bold">{{ getListName(list) }}</div>
            <div v-if="getListDescription(list)" class="text-grey-5 text-body2 q-mt-xs">
              {{ getListDescription(list) }}
            </div>
          </div>
          <div class="row q-gutter-sm items-center">
            <!-- View toggle -->
            <q-btn-toggle
              v-model="viewMode"
              flat
              dense
              toggle-color="primary"
              :options="[
                { value: 'grid', icon: 'mdi-view-grid' },
                { value: 'table', icon: 'mdi-view-list' },
              ]"
            />
            <q-btn
              v-if="isPlaylistRoute && listItems && listItems.length > 0"
              color="primary"
              icon="mdi-playlist-play"
              :label="$q.screen.gt.sm ? $t('listPage.playPlaylist') : ''"
              :loading="playingPlaylist"
              @click="playPlaylist"
            >
              <q-tooltip v-if="!$q.screen.gt.sm">{{ $t('listPage.playPlaylist') }}</q-tooltip>
            </q-btn>
            <q-btn
              v-if="canEditList"
              color="primary"
              icon="mdi-plus"
              :label="$q.screen.gt.sm ? $t('listPage.addItems') : ''"
              no-caps
              @click="openAddItemDialog"
            >
              <q-tooltip v-if="!$q.screen.gt.sm">{{ $t('listPage.addItems') }}</q-tooltip>
            </q-btn>
            <q-btn
              v-if="canEditList"
              flat
              round
              icon="mdi-pencil"
              color="primary"
              :title="$t('listPage.editList')"
              @click="editList"
            />
            <q-btn
              v-if="authStore.isAuthenticated && !canEditList"
              flat
              round
              icon="mdi-heart-outline"
              color="grey-4"
              :title="`${$t('listPage.like')} (${list.like_count})`"
              @click="likeList"
            />
            <q-btn
              v-if="canEditList"
              flat
              round
              icon="mdi-delete-outline"
              color="negative"
              :title="$t('listPage.deleteList')"
              @click="confirmDeleteList"
            />
          </div>
        </div>

        <!-- Meta chips -->
        <div class="row items-center q-gutter-xs q-ml-xl q-pl-sm">
          <q-chip
            v-if="list.owner && list.visibility === 'PUBLIC'"
            :label="
              $t('listPage.byUser', {
                name:
                  list.owner.preferred_username ||
                  `${list.owner.first_name} ${list.owner.last_name}`,
              })
            "
            color="grey-8"
            text-color="white"
            size="sm"
            dense
            icon="mdi-account"
          />
          <q-chip
            :label="formatVisibility(list.visibility)"
            :color="list.visibility === 'PUBLIC' ? 'positive' : 'orange-9'"
            text-color="white"
            size="sm"
            dense
          />
          <q-chip
            :label="$t('listPage.itemCount', { count: list.item_count })"
            color="grey-8"
            text-color="white"
            size="sm"
            dense
            icon="mdi-format-list-bulleted"
          />
          <q-chip
            v-if="list.like_count"
            :label="String(list.like_count)"
            color="grey-8"
            text-color="white"
            size="sm"
            dense
            icon="mdi-heart"
          />
          <q-chip
            v-if="list.tags"
            :label="list.tags"
            color="grey-8"
            text-color="white"
            size="sm"
            dense
            icon="mdi-tag-outline"
          />
        </div>
      </div>

      <!-- Items Loading -->
      <div v-if="loadingItems" class="flex flex-center q-py-xl">
        <q-spinner-dots size="40px" color="primary" />
      </div>

      <!-- Items Grid View -->
      <div v-else-if="listItems && listItems.length > 0 && viewMode === 'grid'">
        <div class="row q-col-gutter-md">
          <div v-for="item in listItems" :key="item.guid" class="col-6 col-sm-4 col-md-3 col-lg-2">
            <div class="relative-position">
              <PosterCard
                :title="getItemTitle(item)"
                :image-url="getItemPoster(item)"
                :type="mapItemType(item.item_type)"
                :subtitle="getItemYear(item) ? String(getItemYear(item)) : ''"
                :platforms="item.platforms"
                @click="navigateToItem(item)"
              />
              <div v-if="canRemoveItems" class="absolute-top-right q-ma-xs" style="z-index: 1">
                <q-btn
                  round
                  dense
                  size="sm"
                  icon="mdi-close"
                  color="negative"
                  class="remove-btn"
                  :title="$t('listPage.removeFromList')"
                  @click.stop="removeItem(item)"
                />
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Items Table View -->
      <q-table
        v-else-if="listItems && listItems.length > 0 && viewMode === 'table'"
        flat
        bordered
        dark
        :rows="listItems"
        :columns="tableColumns"
        row-key="guid"
        :rows-per-page-options="[25, 50, 100]"
        @row-click="(evt, row) => navigateToItem(row)"
        class="list-table"
      >
        <template v-slot:body-cell-poster="props">
          <q-td :props="props" style="width: 50px; padding: 4px">
            <q-img
              v-if="getItemPoster(props.row)"
              :src="getItemPoster(props.row)"
              :ratio="2 / 3"
              style="width: 40px; border-radius: 4px"
            />
          </q-td>
        </template>
        <template v-slot:body-cell-type="props">
          <q-td :props="props">
            <q-badge :label="props.row.item_type" color="grey-8" />
          </q-td>
        </template>
        <template v-slot:body-cell-actions="props">
          <q-td :props="props" auto-width>
            <q-btn
              v-if="canRemoveItems"
              flat
              dense
              round
              icon="mdi-close"
              color="negative"
              size="sm"
              @click.stop="removeItem(props.row)"
            />
          </q-td>
        </template>
      </q-table>

      <!-- Empty State -->
      <div v-else class="flex flex-center q-py-xl">
        <div class="text-center">
          <q-icon name="mdi-format-list-bulleted" size="5em" color="grey-7" />
          <div class="text-h6 text-grey-5 q-mt-md">{{ $t('listPage.noItems') }}</div>
          <div class="text-body2 text-grey-6 q-mt-sm q-mb-lg">{{ $t('listPage.noItemsDesc') }}</div>
        </div>
      </div>
    </div>

    <q-dialog v-model="showAddItemDialog">
      <q-card dark style="min-width: 420px; max-width: 720px; width: 90vw">
        <q-card-section>
          <div class="text-h6">{{ $t('listPage.addItemDialogTitle') }}</div>
          <div class="text-caption text-grey-5">{{ $t('listPage.addItemDialogDesc') }}</div>
        </q-card-section>

        <q-card-section class="q-gutter-md">
          <div class="row q-col-gutter-sm">
            <div class="col">
              <q-input
                v-model="addItemQuery"
                :label="$t('common.search')"
                outlined
                dense
                dark
                autofocus
                debounce="300"
                @update:model-value="searchAddItems"
              >
                <template #prepend>
                  <q-icon name="mdi-magnify" />
                </template>
              </q-input>
            </div>
            <div class="col-auto">
              <q-btn
                color="primary"
                icon="mdi-magnify"
                :loading="addItemSearching"
                @click="searchAddItems"
              />
            </div>
          </div>

          <q-list bordered separator>
            <q-item v-if="addItemSearching">
              <q-item-section avatar>
                <q-spinner color="primary" size="sm" />
              </q-item-section>
              <q-item-section>{{ $t('common.loading') }}</q-item-section>
            </q-item>
            <q-item v-else-if="addItemResults.length === 0">
              <q-item-section avatar>
                <q-icon name="mdi-magnify-close" color="grey-5" />
              </q-item-section>
              <q-item-section>
                <q-item-label>{{ $t('listPage.noSearchResults') }}</q-item-label>
              </q-item-section>
            </q-item>
            <template v-else>
              <q-item v-for="item in addItemResults" :key="addItemResultKey(item)">
                <q-item-section avatar>
                  <q-avatar rounded>
                    <q-img v-if="addItemPoster(item)" :src="addItemPoster(item)" />
                    <q-icon v-else :name="addItemIcon(item)" />
                  </q-avatar>
                </q-item-section>
                <q-item-section>
                  <q-item-label>{{
                    item.title || item.name || $t('listPage.unknownItem')
                  }}</q-item-label>
                  <q-item-label caption>
                    {{ addItemTypeLabel(item) }}
                    <span v-if="addItemYear(item)"> · {{ addItemYear(item) }}</span>
                  </q-item-label>
                </q-item-section>
                <q-item-section side>
                  <q-btn
                    color="primary"
                    dense
                    no-caps
                    :label="addItemActionLabel(item)"
                    :loading="addingItemId === addItemResultKey(item)"
                    :disable="!canAddSearchResult(item)"
                    @click="addSearchResultToList(item)"
                  />
                </q-item-section>
              </q-item>
            </template>
          </q-list>
        </q-card-section>

        <q-card-actions align="right">
          <q-btn flat :label="$t('common.close')" v-close-popup />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted, toRaw } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { Dialog, useQuasar } from 'quasar'
import { useAuthStore } from 'src/stores/auth'
import {
  isAddableSearchResult,
  listItemTypeFromSearchResult,
  mediaGuidFromSearchResult,
  useListsStore,
} from 'src/stores/lists'
import { useAudioPlayerStore } from 'src/stores/audioPlayer'
import PosterCard from 'src/components/PosterCard.vue'
import { logger } from 'src/utils/logger'
import { getTmdbImageUrl } from 'src/composables/useMediaFormatters'
import { overlayServeUrl } from 'src/utils/posters'
import { useListTranslation } from 'src/composables/useListTranslation'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const $q = useQuasar()
const authStore = useAuthStore()
const listsStore = useListsStore()
const audioPlayerStore = useAudioPlayerStore()

const { getListName, getListDescription } = useListTranslation()
const error = ref(null)
const viewMode = ref('grid')
const playingPlaylist = ref(false)
const showAddItemDialog = ref(false)
const addItemQuery = ref('')
const addItemResults = ref([])
const addItemSearching = ref(false)
const addingItemId = ref(null)

// Table pagination (kept for store compatibility)
const tablePagination = ref({
  sortBy: 'created_at',
  descending: true,
  page: 1,
  rowsPerPage: 50,
  rowsNumber: 0,
})

// Table columns
const tableColumns = computed(() => [
  { name: 'poster', label: '', field: 'guid', align: 'center', sortable: false },
  {
    name: 'title',
    label: t('common.title', 'Title'),
    field: (row) => getItemTitle(row),
    align: 'left',
    sortable: true,
  },
  {
    name: 'type',
    label: t('common.type', 'Type'),
    field: 'item_type',
    align: 'left',
    sortable: true,
  },
  {
    name: 'year',
    label: t('common.year', 'Year'),
    field: (row) => getItemYear(row),
    align: 'left',
    sortable: true,
  },
  { name: 'actions', label: '', field: 'guid', align: 'right', sortable: false },
])

// Computed properties using store data
const list = computed(() => listsStore.getCurrentList)
const listItems = computed(() => listsStore.getCurrentListItems)
const loading = computed(() => listsStore.isLoadingList)
const loadingItems = computed(() => listsStore.isLoadingItems)
const isPlaylistRoute = computed(() => route.path.startsWith('/playlists/'))

const canEditList = computed(() => {
  if (!list.value || !authStore.user || !authStore.isAuthenticated) return false
  return list.value.owner_guid === authStore.user.guid || authStore.user.is_superuser
})

const canRemoveItems = computed(() => canEditList.value)

const existingListItemKeys = computed(() => {
  return new Set((listItems.value || []).map(listItemKey).filter(Boolean))
})

// Get item poster URL — prefer the overlay-serve route for local
// movies/shows so 4K/HDR badges show up on list cards.
function getItemPoster(item) {
  if (!item.item_data) return null
  const overlay = overlayServeUrl(
    { guid: item.item_data.guid, media_type: item.item_data.media_type },
    'POSTER',
  )
  if (overlay) return overlay
  if (!item.item_data.poster_path) return null
  if (item.item_data.poster_path.startsWith('http')) return item.item_data.poster_path
  return getTmdbImageUrl(item.item_data.poster_path, 'w500')
}

// Get item title
function getItemTitle(item) {
  if (!item.item_data) return t('listPage.unknownItem')
  return item.item_data.title || item.item_data.name || t('listPage.unknownItem')
}

// Get item year
function getItemYear(item) {
  if (!item.item_data) return null
  const date = item.item_data.release_date || item.item_data.first_air_date
  if (!date) return null
  return new Date(date).getFullYear()
}

function addItemResultKey(item) {
  return String(item.id || item.guid || item.tmdb_id || item.igdb_id || item.spotify_id || item.title)
}

function addItemGuid(item) {
  return mediaGuidFromSearchResult(item)
}

function addItemType(item) {
  return listItemTypeFromSearchResult(item)
}

function normalizedListItemType(type) {
  return type ? String(type).toUpperCase() : null
}

function itemMediaGuid(item) {
  return item?.item_guid || item?.media_item_guid || item?.item_data?.guid || null
}

function mediaListItemKey(type, guid) {
  const normalizedType = normalizedListItemType(type)
  return normalizedType && guid ? `${normalizedType}:${guid}` : null
}

function listItemKey(item) {
  return mediaListItemKey(item?.item_type, itemMediaGuid(item))
}

function addItemListKey(item) {
  return mediaListItemKey(addItemType(item), addItemGuid(item))
}

function isSearchResultInList(item) {
  const key = addItemListKey(item)
  return Boolean(key && existingListItemKeys.value.has(key))
}

function canAddSearchResult(item) {
  return isAddableSearchResult(item) && !isSearchResultInList(item)
}

function addItemActionLabel(item) {
  return isSearchResultInList(item) ? t('listPage.alreadyInList') : t('listPage.add')
}

function addItemPoster(item) {
  const poster = item.poster_path || item.image || item.image_url || item.cover_url
  if (!poster) return null
  if (poster.startsWith?.('http')) return poster
  return getTmdbImageUrl(poster, 'w185')
}

function addItemYear(item) {
  const date = item.release_date || item.first_air_date || item.year
  if (!date) return null
  if (Number.isFinite(Number(date))) return Number(date)
  return new Date(date).getFullYear()
}

function addItemTypeLabel(item) {
  const type = addItemType(item)
  if (!type) return t('listPage.unknown')
  return type
}

function addItemIcon(item) {
  switch (addItemType(item)) {
    case 'MOVIE':
      return 'mdi-movie'
    case 'SHOW':
    case 'EPISODE':
      return 'mdi-television'
    case 'GAME':
      return 'mdi-gamepad-variant'
    case 'MUSIC':
      return 'mdi-music'
    case 'BOOK':
    case 'AUDIOBOOK':
      return 'mdi-book-open'
    default:
      return 'mdi-file-question'
  }
}

// Map backend item_type to PosterCard type prop
function mapItemType(itemType) {
  switch (itemType) {
    case 'movie':
      return 'movie'
    case 'show':
      return 'show'
    case 'game':
      return 'game'
    case 'music':
      return 'music'
    case 'artist':
      return 'artist'
    case 'album':
      return 'album'
    case 'song':
      return 'song'
    case 'book':
      return 'book'
    case 'audiobook':
      return 'book'
    default:
      return 'movie'
  }
}

// Format visibility
function formatVisibility(visibility) {
  switch (visibility) {
    case 'PUBLIC':
      return t('listPage.public')
    case 'PRIVATE':
      return t('listPage.private')
    case 'UNLISTED':
      return t('listPage.unlisted')
    default:
      return visibility
  }
}

// Navigate to item detail page
function navigateToItem(item) {
  if (!item.item_data) return
  router.push(`/media/${item.item_data.guid}`)
}

function queueItemToAudioTrack(item) {
  return {
    guid: item.media_item_guid,
    title: item.title || t('listPage.unknownItem'),
    artist: list.value ? getListName(list.value) : '',
    albumTitle: list.value ? getListName(list.value) : '',
    albumArt: item.poster_path || item.backdrop_path || null,
    duration: item.duration_seconds || 0,
    mediaType: item.item_type,
  }
}

function queueItemToPlayType(item) {
  switch (item.item_type) {
    case 'episode':
    case 'show':
      return 'episode'
    case 'game':
      return 'game'
    case 'music':
      return 'music'
    case 'book':
    case 'audiobook':
      return 'book'
    case 'movie':
    default:
      return 'movie'
  }
}

async function playPlaylist() {
  if (!list.value || playingPlaylist.value) return

  playingPlaylist.value = true
  try {
    const queue = await listsStore.fetchPlaylistQueue(list.value.guid)
    if (!queue || !queue.items || queue.items.length === 0 || !queue.current_item) {
      $q.notify({ type: 'warning', message: t('listPage.playlistEmpty') })
      return
    }

    const audioItems = queue.items.filter((item) => item.item_type === 'music')
    if (audioItems.length === queue.items.length) {
      const tracks = queue.items.map(queueItemToAudioTrack)
      const startIndex = Math.min(queue.start_index || 0, tracks.length - 1)
      await audioPlayerStore.play(tracks[startIndex], tracks)
      return
    }

    const current = queue.current_item
    router.push({
      path: `/play/${current.media_item_guid}`,
      query: {
        type: queueItemToPlayType(current),
        playlist: list.value.guid,
        playlist_index: queue.start_index || 0,
      },
    })
  } catch (err) {
    logger.error('Error playing playlist:', err)
    $q.notify({
      type: 'negative',
      message: err.response?.data?.detail || t('listPage.failedToPlayPlaylist'),
    })
  } finally {
    playingPlaylist.value = false
  }
}

function openAddItemDialog() {
  addItemQuery.value = ''
  addItemResults.value = []
  showAddItemDialog.value = true
}

async function searchAddItems() {
  const query = addItemQuery.value.trim()
  if (!query) {
    addItemResults.value = []
    return
  }

  addItemSearching.value = true
  try {
    addItemResults.value = await listsStore.searchAddableItems(query)
  } catch (err) {
    logger.error('Error searching list items:', err)
    $q.notify({
      type: 'negative',
      message: err.response?.data?.detail || t('listPage.failedToSearchItems'),
    })
  } finally {
    addItemSearching.value = false
  }
}

async function addSearchResultToList(item) {
  if (!list.value || !canAddSearchResult(item)) return

  const key = addItemResultKey(item)
  addingItemId.value = key
  try {
    await listsStore.addItemToList(list.value.guid, {
      item_type: addItemType(item),
      item_guid: addItemGuid(item),
    })
    await loadListItems()
    addItemResults.value = addItemResults.value.filter(
      (candidate) => addItemResultKey(candidate) !== key,
    )
    $q.notify({ type: 'positive', message: t('listPage.itemAddedToList') })
  } catch (err) {
    logger.error('Error adding item to list:', err)
    $q.notify({
      type: 'negative',
      message: err.response?.data?.detail || t('listPage.failedToAddItem'),
    })
  } finally {
    addingItemId.value = null
  }
}

// Load single list from server using store
async function loadList() {
  const listId = route.params.guid
  if (!listId) {
    error.value = t('listPage.noListIdProvided')
    return
  }

  error.value = null

  try {
    if (isPlaylistRoute.value) {
      await listsStore.fetchPlaylist(listId)
    } else {
      await listsStore.fetchList(listId)
    }
  } catch (err) {
    logger.error('Error loading list:', err)
    error.value = err.response?.data?.detail || t('listPage.failedToLoadList')
  }
}

// Load list items using store
async function loadListItems() {
  if (!list.value) return

  try {
    const result = isPlaylistRoute.value
      ? await listsStore.fetchPlaylistItems(
          list.value.guid,
          tablePagination.value.page,
          tablePagination.value.rowsPerPage,
        )
      : await listsStore.fetchListItems(
          list.value.guid,
          tablePagination.value.page,
          tablePagination.value.rowsPerPage,
        )

    tablePagination.value.rowsNumber = result.total || list.value.item_count || 0
  } catch (err) {
    logger.error('Error loading list items:', err)
  }
}

// Edit list
async function editList() {
  const { default: EditListDialog } = await import('src/components/EditListDialog.vue')
  Dialog.create({
    component: EditListDialog,
    componentProps: { list: JSON.parse(JSON.stringify(toRaw(list.value))) },
  }).onOk(() => {
    loadList()
  })
}

// Like list using store
async function likeList() {
  try {
    await listsStore.toggleListLike(list.value.guid)
  } catch (err) {
    logger.error('Error liking list:', err)
  }
}

// Remove item from list using store
async function removeItem(item) {
  try {
    await listsStore.removeItemFromList(list.value.guid, item.guid)
  } catch (err) {
    logger.error('Error removing item:', err)
  }
}

// Confirm delete list
function confirmDeleteList() {
  if (!list.value) return

  Dialog.create({
    title: t('listPage.deleteListTitle'),
    message: t('listPage.deleteListConfirm', { name: getListName(list.value) }),
    cancel: true,
    persistent: true,
    color: 'negative',
    ok: {
      label: t('listPage.deleteBtn'),
      color: 'negative',
    },
  }).onOk(async () => {
    await deleteList()
  })
}

// Delete list using store
async function deleteList() {
  if (!list.value) return

  try {
    await listsStore.deleteList(list.value.guid)
    router.push('/')
  } catch (err) {
    logger.error('Error deleting list:', err)
  }
}

// Watch for list changes to load items
watch(list, (newList) => {
  if (newList) loadListItems()
})

// Clean up when component unmounts
onUnmounted(() => {
  listsStore.clearCurrentList()
})

// Initialize auth store when component mounts
onMounted(async () => {
  try {
    if (!authStore.initialized) {
      await authStore.initialize()
    }
  } catch (err) {
    logger.error('Failed to initialize auth store:', err)
  }
})

// Watch route changes to reload list
watch(
  () => route.params.guid,
  (newGuid) => {
    if (newGuid) loadList()
  },
  { immediate: true },
)
</script>

<style lang="scss" scoped>
.list-detail-page {
  min-height: 100vh;
  color: white;
}

.list-header {
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  padding-bottom: 16px;
}

.remove-btn {
  opacity: 0;
  transition: opacity 0.2s ease;
}

.relative-position:hover .remove-btn {
  opacity: 1;
}

.list-table {
  :deep(tbody tr) {
    cursor: pointer;
  }
}
</style>
