<template>
  <q-page class="q-pa-md">
    <div class="text-h4 q-mb-md">{{ $t('adminDownloads.title') }}</div>
    <div class="text-subtitle1 text-grey-7 q-mb-lg">{{ $t('adminDownloads.subtitle') }}</div>

    <q-card flat bordered>
      <q-card-section>
        <div class="row q-col-gutter-md q-mb-md">
          <div class="col-12 col-md-6">
            <q-input
              v-model="search"
              :label="$t('common.search')"
              outlined
              dark
              dense
              clearable
              @update:model-value="debouncedSearch"
            >
              <template v-slot:prepend>
                <q-icon name="mdi-magnify" />
              </template>
            </q-input>
          </div>

          <div class="col-12 col-md-6">
            <q-select
              v-model="statusFilter"
              :options="statusOptions"
              :label="$t('adminDownloads.filterByStatus')"
              outlined
              dark
              dense
              emit-value
              map-options
              clearable
              @update:model-value="loadDownloads"
            >
              <template v-slot:prepend>
                <q-icon name="mdi-filter" />
              </template>
            </q-select>
          </div>
        </div>

        <q-table
          flat
          bordered
          dark
          :rows="downloads"
          :columns="columns"
          :loading="loading"
          row-key="guid"
          binary-state-sort
          :rows-per-page-options="[10, 25, 50, 100]"
        >
          <template v-slot:body-cell-type="props">
            <q-td :props="props">
              <q-icon :name="getTypeIcon(props.value)" size="sm" :color="getTypeColor(props.value)">
                <q-tooltip>{{ props.value }}</q-tooltip>
              </q-icon>
            </q-td>
          </template>

          <template v-slot:body-cell-display_title="props">
            <q-td :props="props">
              <router-link
                v-if="props.row.media_item_guid"
                :to="`/media/${props.row.media_item_guid}`"
                class="text-primary"
                style="text-decoration: none"
              >
                {{ props.row.display_title }}
              </router-link>
              <span v-else>{{ props.row.display_title }}</span>
            </q-td>
          </template>

          <template v-slot:body-cell-status="props">
            <q-td :props="props">
              <q-chip :color="getStatusColor(props.value)" text-color="white" size="sm" dense>
                {{ getStatusLabel(props.value) }}
              </q-chip>
              <div
                v-if="getStatusDetail(props.row)"
                class="download-status-detail text-caption text-grey-5 q-mt-xs"
              >
                {{ getStatusDetail(props.row) }}
              </div>
            </q-td>
          </template>

          <template v-slot:body-cell-downloader_name="props">
            <q-td :props="props">
              <div v-if="props.row.downloader_name" class="row items-center no-wrap">
                <q-icon
                  :name="props.row.downloader_type === 'sabnzbd' ? 'mdi-download' : 'mdi-magnet'"
                  size="xs"
                  class="q-mr-xs"
                  :color="props.row.downloader_type === 'sabnzbd' ? 'amber' : 'light-blue'"
                />
                <span>{{ props.row.downloader_name }}</span>
              </div>
              <span v-else class="text-grey">-</span>
            </q-td>
          </template>

          <template v-slot:body-cell-progress="props">
            <q-td :props="props">
              <div v-if="props.value !== null" class="row items-center no-wrap">
                <q-linear-progress
                  :value="props.value / 100"
                  :color="props.value >= 100 ? 'positive' : 'primary'"
                  class="col q-mr-sm"
                  size="8px"
                  rounded
                />
                <span class="text-caption">{{ props.value.toFixed(1) }}%</span>
              </div>
              <span v-else class="text-grey">-</span>
            </q-td>
          </template>

          <template v-slot:body-cell-started_by_name="props">
            <q-td :props="props">
              <router-link
                v-if="props.row.user_guid"
                :to="`/admin/users/${props.row.user_guid}`"
                class="text-primary"
                style="text-decoration: none"
              >
                {{ props.row.started_by_name }}
              </router-link>
              <span v-else>{{ props.row.started_by_name || '-' }}</span>
            </q-td>
          </template>

          <template v-slot:body-cell-actions="props">
            <q-td :props="props">
              <q-btn
                v-if="isPausable(props.row)"
                flat
                dense
                round
                icon="mdi-pause"
                color="warning"
                size="sm"
                @click="togglePause(props.row, true)"
              >
                <q-tooltip>{{ $t('common.pause', 'Pause') }}</q-tooltip>
              </q-btn>
              <q-btn
                v-if="isPaused(props.row)"
                flat
                dense
                round
                icon="mdi-play"
                color="positive"
                size="sm"
                @click="togglePause(props.row, false)"
              >
                <q-tooltip>{{ $t('common.resume', 'Resume') }}</q-tooltip>
              </q-btn>
              <q-btn
                flat
                dense
                round
                icon="mdi-delete"
                color="negative"
                size="sm"
                @click="confirmDelete(props.row)"
              >
                <q-tooltip>{{ $t('common.delete') }}</q-tooltip>
              </q-btn>
            </q-td>
          </template>
        </q-table>
      </q-card-section>
    </q-card>

    <ConfirmDeleteDialog
      v-model="showDeleteDialog"
      :message="$t('adminDownloads.confirmDelete')"
      :loading="deleting"
      @confirm="deleteDownload"
    />
  </q-page>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from 'boot/axios'
import { debounce } from 'quasar'
import { logger } from 'src/utils/logger'
import ConfirmDeleteDialog from 'src/components/ConfirmDeleteDialog.vue'

const { t } = useI18n()

const downloads = ref([])
const loading = ref(false)
const search = ref('')
const statusFilter = ref(null)
const showDeleteDialog = ref(false)
const deleting = ref(false)
const selectedDownload = ref(null)

const statusOptions = computed(() => [
  { label: t('adminDownloads.statuses.pending'), value: 'pending' },
  { label: t('adminDownloads.statuses.queued'), value: 'queued' },
  { label: t('adminDownloads.statuses.downloading'), value: 'downloading' },
  { label: t('adminDownloads.statuses.paused'), value: 'paused' },
  { label: t('adminDownloads.statuses.completed'), value: 'completed' },
  { label: t('adminDownloads.statuses.failed'), value: 'failed' },
  { label: t('adminDownloads.statuses.imported'), value: 'imported' },
])

const columns = computed(() => [
  {
    name: 'type',
    label: t('adminDownloads.columns.type'),
    align: 'center',
    field: 'type',
    sortable: true,
    style: 'width: 40px',
  },
  {
    name: 'display_title',
    required: true,
    label: t('adminDownloads.columns.title'),
    align: 'left',
    field: 'display_title',
    sortable: true,
  },
  {
    name: 'status',
    label: t('adminDownloads.columns.status'),
    align: 'left',
    field: 'status',
    sortable: true,
  },
  {
    name: 'downloader_name',
    label: t('adminDownloads.columns.downloader'),
    align: 'left',
    field: 'downloader_name',
    sortable: true,
    format: (val) => val || '-',
  },
  {
    name: 'progress',
    label: t('adminDownloads.columns.progress'),
    align: 'left',
    field: 'progress',
    sortable: true,
  },
  {
    name: 'speed',
    label: t('adminDownloads.columns.speed', 'Speed'),
    align: 'right',
    field: 'speed_bps',
    sortable: true,
    format: (val) => formatSpeed(val),
  },
  {
    name: 'started_by_name',
    label: t('adminDownloads.columns.startedBy'),
    align: 'left',
    field: 'started_by_name',
    sortable: true,
    format: (val) => val || '-',
  },
  {
    name: 'created_at',
    label: t('adminDownloads.columns.created'),
    align: 'left',
    field: 'created_at',
    sortable: true,
    format: (val) => (val ? new Date(val).toLocaleString() : '-'),
  },
  {
    name: 'actions',
    label: t('common.actions'),
    align: 'center',
    field: 'actions',
  },
])

const loadDownloads = async (silent = false) => {
  if (!silent) loading.value = true
  try {
    const response = await api.get('/api/downloads')
    downloads.value = response.data

    // Apply local filtering
    if (search.value) {
      downloads.value = downloads.value.filter((d) =>
        d.display_title.toLowerCase().includes(search.value.toLowerCase()),
      )
    }

    if (statusFilter.value) {
      downloads.value = downloads.value.filter(
        (d) => (d.status || '').toLowerCase() === statusFilter.value,
      )
    }
  } catch (error) {
    logger.error('Failed to load downloads:', error)
  } finally {
    if (!silent) loading.value = false
  }
}

const formatSpeed = (bps) => {
  const n = Number(bps) || 0
  if (n <= 0) return '-'
  if (n >= 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB/s`
  if (n >= 1024) return `${(n / 1024).toFixed(0)} KB/s`
  return `${n} B/s`
}

const isPaused = (download) => (download?.status || '').toLowerCase() === 'paused'
const isPausable = (download) =>
  ['downloading', 'queued'].includes((download?.status || '').toLowerCase())

const togglePause = async (download, pause) => {
  try {
    await api.post(`/api/downloads/${download.guid}/${pause ? 'pause' : 'resume'}`)
    loadDownloads(true)
  } catch (error) {
    logger.error(`Failed to ${pause ? 'pause' : 'resume'} download:`, error)
  }
}

const debouncedSearch = debounce(() => {
  loadDownloads()
}, 500)

const getTypeIcon = (type) => {
  const t = (type || '').toLowerCase()
  // The backend sends media-type values (MOVIES/SHOWS/GAMES/SONGS/BOOKS) as
  // well as legacy singular forms — map both.
  const icons = {
    movie: 'mdi-movie',
    movies: 'mdi-movie',
    episode: 'mdi-television',
    episodes: 'mdi-television',
    show: 'mdi-television',
    shows: 'mdi-television',
    music: 'mdi-music',
    song: 'mdi-music',
    songs: 'mdi-music',
    game: 'mdi-gamepad-variant',
    games: 'mdi-gamepad-variant',
    book: 'mdi-book',
    books: 'mdi-book',
  }
  return icons[t] || 'mdi-download'
}

const getTypeColor = (type) => {
  const t = (type || '').toLowerCase()
  const colors = {
    movie: 'amber',
    movies: 'amber',
    episode: 'light-blue',
    episodes: 'light-blue',
    show: 'light-blue',
    shows: 'light-blue',
    music: 'pink',
    song: 'pink',
    songs: 'pink',
    game: 'purple',
    games: 'purple',
    book: 'brown',
    books: 'brown',
  }
  return colors[t] || 'grey'
}

const getStatusColor = (status) => {
  const s = (status || '').toLowerCase()
  const colors = {
    queued: 'grey',
    downloading: 'blue',
    paused: 'orange',
    completed: 'green',
    failed: 'red',
    imported: 'teal',
  }
  return colors[s] || 'grey'
}

const getStatusLabel = (status) => {
  const s = (status || '').toLowerCase()
  return t(`adminDownloads.statuses.${s}`, status)
}

const STATUS_DETAIL_KEYS = {
  preparing: 'adminDownloads.statusDetails.preparing',
  searching: 'adminDownloads.statusDetails.searching',
  retrying_release: 'adminDownloads.statusDetails.retryingRelease',
  importing: 'adminDownloads.statusDetails.importing',
}

const getStatusDetail = (download) => {
  const explicitDetail = download?.status_detail || download?.error_reason
  if (explicitDetail) return explicitDetail

  const phase = (download?.status_phase || '').toLowerCase()
  const key = STATUS_DETAIL_KEYS[phase]
  return key ? t(key) : ''
}

const confirmDelete = (download) => {
  selectedDownload.value = download
  showDeleteDialog.value = true
}

const deleteDownload = async () => {
  if (!selectedDownload.value) return

  deleting.value = true
  try {
    await api.delete(`/api/downloads/${selectedDownload.value.guid}`)

    showDeleteDialog.value = false
    selectedDownload.value = null
    loadDownloads()
  } catch (error) {
    logger.error('Failed to delete download:', error)
  } finally {
    deleting.value = false
  }
}

let pollTimer = null

onMounted(() => {
  loadDownloads()
  // Background refresh so progress + live speed update without a manual
  // reload. Silent so the table doesn't flash a spinner every tick.
  pollTimer = setInterval(() => loadDownloads(true), 5000)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<style scoped>
.q-chip {
  font-weight: 500;
}

.download-status-detail {
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
