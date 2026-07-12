<template>
  <q-page class="q-pa-md">
    <div class="row items-center q-mb-md">
      <div class="col">
        <h4 class="q-ma-none text-h4">{{ $t('viewingHistory.title') }}</h4>
      </div>
    </div>

    <!-- Table -->
    <q-table
      :rows="historyItems"
      :columns="columns"
      row-key="guid"
      flat
      bordered
      dark
      :loading="loading && historyItems.length === 0"
      :rows-per-page-options="[]"
      hide-pagination
    >
      <!-- Title column -->
      <template #body-cell-title="{ row }">
        <q-td>
          <div class="row no-wrap items-center q-gutter-sm">
            <q-avatar square size="48px">
              <img
                :src="getPosterUrl(row)"
                :alt="getTitle(row)"
                style="object-fit: cover; width: 100%; height: 100%"
              />
            </q-avatar>
            <div>
              <div class="text-body2">{{ getTitle(row) }}</div>
              <q-chip
                dense
                size="sm"
                :color="typeChipMeta(row.content_type).color"
                text-color="white"
                :icon="typeChipMeta(row.content_type).icon"
                class="q-ml-none q-mt-xs"
              />
            </div>
          </div>
        </q-td>
      </template>

      <!-- Progress column -->
      <template #body-cell-progress="{ row }">
        <q-td>
          <div v-if="row.is_completed">
            <q-chip dense size="sm" color="positive" text-color="white" icon="mdi-check-circle">
              {{ $t('viewingHistory.completed') }}
            </q-chip>
          </div>
          <div v-else-if="row.progress_percentage > 0">
            <q-linear-progress
              :value="row.progress_percentage / 100"
              color="primary"
              track-color="grey-8"
              size="6px"
              rounded
              class="q-mb-xs"
              style="width: 120px"
            />
            <div class="text-caption text-grey-5">
              {{ Math.round(row.progress_percentage) }}%
              <span v-if="row.progress_seconds">
                · {{ formatWatchTime(row.progress_seconds) }}</span
              >
              <span v-if="row.duration_seconds">
                / {{ formatWatchTime(row.duration_seconds) }}</span
              >
            </div>
          </div>
          <div v-else class="text-grey-7 text-caption">-</div>
        </q-td>
      </template>

      <!-- Date column -->
      <template #body-cell-last_watched="{ row }">
        <q-td class="text-caption text-grey-5">{{ formatDate(row.last_watched_at) }}</q-td>
      </template>

      <!-- Actions column -->
      <template #body-cell-actions="{ row }">
        <q-td>
          <q-btn
            flat
            dense
            size="sm"
            color="primary"
            :icon="row.is_completed ? 'mdi-replay' : 'mdi-play'"
            :label="
              row.is_completed ? $t('viewingHistory.watchAgain') : $t('viewingHistory.continue')
            "
            @click="playItem(row)"
          />
          <q-btn
            flat
            dense
            size="sm"
            color="grey-6"
            icon="mdi-delete-outline"
            class="q-ml-xs"
            @click="confirmDelete(row)"
          >
            <q-tooltip>{{ $t('viewingHistory.delete') }}</q-tooltip>
          </q-btn>
        </q-td>
      </template>

      <!-- Empty state -->
      <template #no-data>
        <div class="full-width text-center q-pa-xl">
          <q-icon name="mdi-history" size="4rem" color="grey-5" />
          <div class="text-grey-5 q-mt-md">{{ $t('viewingHistory.empty') }}</div>
        </div>
      </template>
    </q-table>

    <!-- Load More -->
    <div v-if="hasMore" class="text-center q-mt-md">
      <q-btn
        outline
        color="primary"
        icon="mdi-chevron-down"
        :label="$t('viewingHistory.loadMore')"
        :loading="loading"
        @click="loadMore"
      />
    </div>

    <!-- Delete Confirm Dialog -->
    <q-dialog v-model="deleteDialog">
      <q-card style="min-width: 300px">
        <q-card-section>
          <div class="text-h6">{{ $t('viewingHistory.deleteConfirmTitle') }}</div>
        </q-card-section>
        <q-card-section class="q-pt-none text-grey-4">
          {{ $t('viewingHistory.deleteConfirmText') }}
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat :label="$t('common.cancel')" v-close-popup />
          <q-btn
            flat
            color="negative"
            :label="$t('common.delete')"
            :loading="deleting"
            @click="deleteItem"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  getViewingHistory,
  deleteViewingHistoryItem,
} from 'src/services/userMediaService'
import { getTmdbImageUrl, formatWatchTime } from 'src/composables/useMediaFormatters'
import { overlayServeUrl } from 'src/utils/posters'

const router = useRouter()
const { t } = useI18n()

const historyItems = ref([])
const loading = ref(false)
const activeFilter = ref('all')
const currentPage = ref(1)
const totalPages = ref(1)
const deleteDialog = ref(false)
const deleting = ref(false)
const itemToDelete = ref(null)

const hasMore = computed(() => currentPage.value < totalPages.value)

const columns = [
  { name: 'title', label: t('viewingHistory.col.title'), field: 'title', align: 'left' },
  {
    name: 'progress',
    label: t('viewingHistory.col.progress'),
    field: 'progress_percentage',
    align: 'left',
  },
  {
    name: 'last_watched',
    label: t('viewingHistory.col.lastWatched'),
    field: 'last_watched_at',
    align: 'left',
  },
  { name: 'actions', label: '', field: 'actions', align: 'right' },
]

const loadHistory = async (append = false) => {
  loading.value = true
  try {
    const params = { page: currentPage.value, per_page: 20 }
    if (activeFilter.value === 'movie') params.content_type = 'movie'
    else if (activeFilter.value === 'episode') params.content_type = 'episode'

    const data = await getViewingHistory(params)
    let items = data.items || []

    if (activeFilter.value === 'in_progress') {
      items = items.filter((i) => !i.is_completed && i.progress_percentage > 0)
    }

    if (append) historyItems.value.push(...items)
    else historyItems.value = items

    totalPages.value = data.total_pages || 1
  } catch {
    // silently ignore
  } finally {
    loading.value = false
  }
}

const loadMore = async () => {
  currentPage.value++
  await loadHistory(true)
}

watch(activeFilter, () => {
  currentPage.value = 1
  loadHistory(false)
})

const getPosterUrl = (item) => {
  const media = item.media_item
  if (!media) return '/icons/favicon-128x128.png'
  const overlay = overlayServeUrl(media, 'POSTER')
  if (overlay) return overlay
  if (media.backdrop_path) return getTmdbImageUrl(media.backdrop_path, 'w780')
  if (media.poster_path) return getTmdbImageUrl(media.poster_path, 'w500')
  return '/icons/favicon-128x128.png'
}

const typeChipMeta = (contentType) => {
  switch (contentType) {
    case 'movie':
      return { color: 'blue-grey-8', icon: 'mdi-movie-open' }
    case 'games':
      return { color: 'green-8', icon: 'mdi-controller' }
    case 'songs':
      return { color: 'teal-8', icon: 'mdi-music' }
    case 'books':
      return { color: 'brown-8', icon: 'mdi-book-open-page-variant' }
    default:
      return { color: 'purple-8', icon: 'mdi-television-play' }
  }
}

// Maps viewing-history content_type (plural, from MediaType) to the
// singular ?type= param PlayPage expects.
const PLAY_TYPE = {
  movie: 'movie',
  episode: 'episode',
  games: 'game',
  songs: 'music',
  books: 'book',
}

const getTitle = (item) => {
  if (item.content_type === 'movie')
    return item.media_item?.title || t('viewingHistory.unknownMovie')
  if (item.content_type === 'games')
    return item.media_item?.title || t('viewingHistory.unknownGame')
  const episodeTitle = item.media_item?.title
  const showTitle = item.show_title
  const s = item.season_number
  const e = item.episode_number
  if (showTitle && s != null && e != null) {
    const code = `S${String(s).padStart(2, '0')}E${String(e).padStart(2, '0')}`
    return episodeTitle ? `${showTitle} - ${code}: ${episodeTitle}` : `${showTitle} - ${code}`
  }
  return episodeTitle || t('viewingHistory.unknownEpisode')
}

const formatDate = (dateStr) => {
  const date = new Date(dateStr)
  const now = new Date()
  const diffH = Math.floor((now - date) / (1000 * 60 * 60))
  if (diffH < 1) return t('viewingHistory.justNow')
  if (diffH < 24) return t('viewingHistory.hoursAgo', { n: diffH })
  const diffD = Math.floor(diffH / 24)
  if (diffD === 1) return t('viewingHistory.yesterday')
  if (diffD < 7) return t('viewingHistory.daysAgo', { n: diffD })
  return date.toLocaleDateString(undefined, { day: '2-digit', month: '2-digit', year: 'numeric' })
}

const playItem = (item) => {
  const guid =
    item.content_type === 'episode'
      ? item.episode_guid
      : item.movie_guid || item.media_item?.guid
  const type = PLAY_TYPE[item.content_type] || item.content_type
  router.push({ path: `/play/${guid}`, query: { type } })
}

const confirmDelete = (item) => {
  itemToDelete.value = item
  deleteDialog.value = true
}

const deleteItem = async () => {
  if (!itemToDelete.value) return
  deleting.value = true
  try {
    await deleteViewingHistoryItem(itemToDelete.value.guid)
    historyItems.value = historyItems.value.filter((i) => i.guid !== itemToDelete.value.guid)
    deleteDialog.value = false
  } catch {
    // silently ignore
  } finally {
    deleting.value = false
    itemToDelete.value = null
  }
}

onMounted(() => loadHistory())
</script>
