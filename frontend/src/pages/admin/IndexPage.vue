<template>
  <q-page class="admin-dashboard q-pa-md q-pa-md-lg">
    <!-- Status Cards -->
    <div class="row q-col-gutter-md q-mb-lg">
      <div class="col-6 col-md-3">
        <q-card class="stat-card" flat>
          <q-card-section class="row items-center no-wrap q-pa-sm q-pa-md-md">
            <q-avatar
              :color="systemHealth === 'healthy' ? 'positive' : 'negative'"
              text-color="white"
              size="42px"
              class="q-mr-md"
            >
              <q-icon :name="systemHealth === 'healthy' ? 'mdi-check' : 'mdi-alert'" size="20px" />
            </q-avatar>
            <div>
              <div class="stat-label">{{ $t('adminDashboard.systemHealth') }}</div>
              <div class="stat-value">
                {{
                  systemHealth === 'healthy'
                    ? $t('adminDashboard.healthy')
                    : $t('adminDashboard.unhealthy')
                }}
              </div>
            </div>
          </q-card-section>
        </q-card>
      </div>

      <div class="col-6 col-md-3">
        <q-card class="stat-card clickable" flat @click="router.push('/admin/active-sessions')">
          <q-card-section class="row items-center no-wrap q-pa-sm q-pa-md-md">
            <q-avatar color="teal" text-color="white" size="42px" class="q-mr-md">
              <q-icon name="mdi-cast" size="20px" />
            </q-avatar>
            <div>
              <div class="stat-label">{{ $t('adminDashboard.activeStreams') }}</div>
              <div class="stat-value">{{ stats.activeStreams }}</div>
            </div>
          </q-card-section>
        </q-card>
      </div>

      <div class="col-6 col-md-3">
        <q-card class="stat-card clickable" flat @click="router.push('/admin/downloads')">
          <q-card-section class="row items-center no-wrap q-pa-sm q-pa-md-md">
            <q-avatar color="info" text-color="white" size="42px" class="q-mr-md">
              <q-icon name="mdi-download" size="20px" />
            </q-avatar>
            <div>
              <div class="stat-label">{{ $t('adminDashboard.activeDownloads') }}</div>
              <div class="stat-value">{{ stats.activeDownloads }}</div>
            </div>
          </q-card-section>
        </q-card>
      </div>

      <div class="col-6 col-md-3">
        <q-card class="stat-card clickable" flat @click="router.push('/admin/users')">
          <q-card-section class="row items-center no-wrap q-pa-sm q-pa-md-md">
            <q-avatar color="orange" text-color="white" size="42px" class="q-mr-md">
              <q-icon name="mdi-account-group" size="20px" />
            </q-avatar>
            <div>
              <div class="stat-label">{{ $t('adminDashboard.activeUsers') }}</div>
              <div class="stat-value">
                {{ stats.totalUsers
                }}<span class="stat-sub">
                  / {{ stats.activeUsers }} {{ $t('adminDashboard.online') }}</span
                >
              </div>
            </div>
          </q-card-section>
        </q-card>
      </div>
    </div>

    <!-- Library Breakdown -->
    <q-card flat class="dash-card q-mb-md" v-if="libraryStats.length">
      <q-card-section class="q-pb-sm">
        <div class="dash-heading">{{ $t('adminDashboard.libraryOverview') }}</div>
      </q-card-section>
      <q-card-section class="q-pt-none">
        <div class="row q-col-gutter-sm">
          <div v-for="lib in libraryStats" :key="lib.type" class="col-6 col-sm-4 col-md">
            <div class="lib-chip">
              <q-icon :name="lib.icon" :color="lib.color" size="18px" class="q-mr-xs" />
              <span class="text-weight-medium">{{ lib.count }}</span>
              <span class="text-grey-5 q-ml-xs">{{ lib.name }}</span>
            </div>
          </div>
        </div>
      </q-card-section>
    </q-card>

    <div class="row q-col-gutter-md">
      <!-- Main Column -->
      <div class="col-12 col-lg-8">
        <!-- Active Streams -->
        <q-card flat class="dash-card q-mb-md" v-if="sessions.length > 0">
          <q-card-section class="q-pb-none row items-center justify-between">
            <div class="dash-heading">{{ $t('adminDashboard.activeStreams') }}</div>
            <q-btn
              flat
              dense
              size="sm"
              color="primary"
              :label="$t('adminDashboard.viewAll')"
              @click="router.push('/admin/active-sessions')"
            />
          </q-card-section>
          <q-list separator class="q-pt-sm">
            <q-item v-for="s in sessions.slice(0, 5)" :key="s.session_id" dense>
              <q-item-section avatar>
                <q-avatar color="teal-9" text-color="white" size="32px">
                  <q-icon
                    :name="s.content_type === 'movie' ? 'mdi-movie' : 'mdi-television'"
                    size="16px"
                  />
                </q-avatar>
              </q-item-section>
              <q-item-section>
                <q-item-label>{{ s.content_title || s.content_id }}</q-item-label>
                <q-item-label caption
                  >{{ s.user_name || $t('adminDashboard.unknownUser') }} &middot;
                  {{ s.video_codec }}/{{ s.audio_codec
                  }}<span v-if="s.resolution"> &middot; {{ s.resolution }}</span></q-item-label
                >
              </q-item-section>
              <q-item-section side>
                <q-badge outline color="teal" :label="formatTime(s.duration_seconds)" />
              </q-item-section>
            </q-item>
          </q-list>
        </q-card>

        <!-- Recent Downloads -->
        <q-card flat class="dash-card q-mb-md">
          <q-card-section class="q-pb-none row items-center justify-between">
            <div class="dash-heading">{{ $t('adminDashboard.recentDownloads') }}</div>
            <q-btn
              flat
              dense
              size="sm"
              color="primary"
              :label="$t('adminDashboard.viewAll')"
              @click="router.push('/admin/downloads')"
            />
          </q-card-section>
          <div v-if="recentDownloads.length === 0" class="text-center text-grey-6 q-pa-lg">
            {{ $t('adminDashboard.noRecentDownloads') }}
          </div>
          <q-list v-else separator class="q-pt-sm">
            <q-item v-for="dl in recentDownloads" :key="dl.guid" dense>
              <q-item-section avatar>
                <q-avatar :color="downloadStatusColor(dl.status)" text-color="white" size="32px">
                  <q-icon :name="downloadStatusIcon(dl.status)" size="16px" />
                </q-avatar>
              </q-item-section>
              <q-item-section>
                <q-item-label>{{ dl.display_title || dl.title }}</q-item-label>
                <q-item-label caption>
                  {{ dl.started_by_name || '' }}
                  <span v-if="dl.created_at">
                    &middot; {{ formatRelativeTime(dl.created_at) }}</span
                  >
                </q-item-label>
              </q-item-section>
              <q-item-section side class="row items-center q-gutter-xs">
                <q-linear-progress
                  v-if="dl.progress != null && dl.status === 'downloading'"
                  :value="dl.progress / 100"
                  color="info"
                  track-color="grey-8"
                  rounded
                  size="4px"
                  style="width: 50px"
                />
                <q-badge :color="downloadStatusColor(dl.status)" :label="dl.status" />
              </q-item-section>
            </q-item>
          </q-list>
        </q-card>
      </div>

      <!-- Sidebar -->
      <div class="col-12 col-lg-4">
        <!-- Storage -->
        <q-card flat class="dash-card q-mb-md">
          <q-card-section class="q-pb-sm">
            <div class="dash-heading">{{ $t('adminDashboard.storage.title') }}</div>
          </q-card-section>
          <q-card-section class="q-pt-none" v-if="storageLoading">
            <q-spinner color="primary" size="1.5rem" />
          </q-card-section>
          <q-card-section class="q-pt-none column q-gutter-sm" v-else-if="storageData">
            <div v-for="(lib, name) in storageData.libraries" :key="name">
              <div class="row items-center justify-between text-caption">
                <span class="text-grey-5 text-capitalize">{{ name }}</span>
                <span class="text-weight-medium">{{ formatFileSize(lib.directory_size) }}</span>
              </div>
              <q-linear-progress
                :value="totalLibrarySize > 0 ? lib.directory_size / totalLibrarySize : 0"
                color="purple"
                track-color="grey-9"
                rounded
                size="3px"
                class="q-mt-xs"
              />
            </div>
            <q-separator class="q-my-xs" />
            <div v-for="comp in storageCompartments" :key="comp.key">
              <div class="row items-center justify-between text-caption">
                <span class="text-grey-5">{{ $t(`adminDashboard.storage.${comp.labelKey}`) }}</span>
                <span class="text-weight-medium">{{
                  formatFileSize(comp.entry.directory_size)
                }}</span>
              </div>
              <q-linear-progress
                :value="comp.entry.total > 0 ? comp.entry.used / comp.entry.total : 0"
                :color="comp.color"
                track-color="grey-9"
                rounded
                size="3px"
                class="q-mt-xs"
              />
              <div class="text-caption text-grey-6 q-mt-xs">
                {{ comp.entry.usage_percent }}% {{ $t('adminDashboard.storage.diskUsage') }}
              </div>
            </div>
          </q-card-section>
        </q-card>

        <!-- System Info -->
        <q-card flat class="dash-card q-mb-md">
          <q-card-section class="q-pb-sm">
            <div class="dash-heading">{{ $t('adminDashboard.systemInfo') }}</div>
          </q-card-section>
          <q-card-section class="q-pt-none">
            <div class="info-row" v-for="item in sysInfoItems" :key="item.label">
              <span class="text-grey-5">{{ item.label }}</span>
              <span class="text-weight-medium">{{ item.value }}</span>
            </div>
          </q-card-section>
        </q-card>

        <!-- Quick Actions -->
        <q-card flat class="dash-card">
          <q-card-section class="q-pb-sm">
            <div class="dash-heading">{{ $t('adminDashboard.quickActions') }}</div>
          </q-card-section>
          <q-card-section class="q-pt-none column q-gutter-xs">
            <q-btn
              v-for="action in quickActions"
              :key="action.route"
              flat
              no-caps
              align="left"
              class="action-btn"
              @click="router.push(action.route)"
            >
              <q-icon :name="action.icon" :color="action.color" size="20px" class="q-mr-sm" />
              {{ action.label }}
            </q-btn>
          </q-card-section>
        </q-card>
      </div>
    </div>
  </q-page>
</template>

<script setup>
import { ref, reactive, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { api } from 'boot/axios'
import { logger } from 'src/utils/logger'
import { formatFileSize, formatTime } from 'src/composables/useMediaFormatters'

const { t } = useI18n()
const router = useRouter()

const systemHealth = ref('healthy')

const stats = reactive({
  activeDownloads: 0,
  activeStreams: 0,
  totalLibraryItems: 0,
  totalUsers: 0,
  activeUsers: 0,
  movieCount: 0,
  showCount: 0,
  musicCount: 0,
  gameCount: 0,
  bookCount: 0,
})

const systemInfo = reactive({ activeIndexers: 0, activeDownloaders: 0, libraryCount: 0 })
const sessions = ref([])
const recentDownloads = ref([])
const storageLoading = ref(false)
const storageData = ref(null)

const totalLibrarySize = computed(() => {
  if (!storageData.value?.libraries) return 0
  return Object.values(storageData.value.libraries).reduce((s, l) => s + (l.directory_size || 0), 0)
})

// Two storage compartments outside library directories: yt-dlp/torrent
// downloads + transcode/temp scratch. Rendered as identical progress bars
// so we collapse them into a single data-driven loop in the template.
const storageCompartments = computed(() => {
  const data = storageData.value
  if (!data) return []
  return [
    { key: 'downloads', labelKey: 'downloads', color: 'info', entry: data.downloads },
    { key: 'temp', labelKey: 'transcodes', color: 'amber', entry: data.temp },
  ]
})

// Each library type with its presentation metadata + the matching key on
// the reactive `stats` object. Driving the breakdown row through a single
// data table beats five copy-pasted card definitions.
const LIBRARY_TYPES = [
  { type: 'movies', countKey: 'movieCount', icon: 'mdi-movie', color: 'purple' },
  { type: 'shows', countKey: 'showCount', icon: 'mdi-television', color: 'teal' },
  { type: 'music', countKey: 'musicCount', icon: 'mdi-music', color: 'pink' },
  { type: 'games', countKey: 'gameCount', icon: 'mdi-gamepad-variant', color: 'green' },
  { type: 'books', countKey: 'bookCount', icon: 'mdi-book', color: 'amber' },
]

const libraryStats = computed(() =>
  LIBRARY_TYPES.map(({ type, countKey, icon, color }) => ({
    type,
    icon,
    color,
    name: t(`adminDashboard.${type}`),
    count: stats[countKey],
  })).filter((x) => x.count > 0),
)

const sysInfoItems = computed(() => [
  { label: t('adminDashboard.activeIndexers'), value: systemInfo.activeIndexers },
  { label: t('adminDashboard.activeDownloaders'), value: systemInfo.activeDownloaders },
  { label: t('adminDashboard.libraries'), value: systemInfo.libraryCount },
])

const quickActions = computed(() => [
  {
    icon: 'mdi-plus',
    color: 'purple',
    label: t('adminDashboard.addLibrary'),
    route: '/admin/libraries/create',
  },
  {
    icon: 'mdi-account-plus',
    color: 'orange',
    label: t('adminDashboard.manageUsers'),
    route: '/admin/users',
  },
  {
    icon: 'mdi-server',
    color: 'teal',
    label: t('adminDashboard.manageSessions'),
    route: '/admin/active-sessions',
  },
  {
    icon: 'mdi-cloud-search',
    color: 'amber',
    label: t('adminDashboard.metadataProviders'),
    route: '/admin/metadata',
  },
  {
    icon: 'mdi-cog',
    color: 'grey-5',
    label: t('adminDashboard.systemSettings'),
    route: '/admin/settings',
  },
])

const formatRelativeTime = (dateStr) => {
  const diffMin = Math.floor((Date.now() - new Date(dateStr)) / 60000)
  if (diffMin < 1) return t('adminDashboard.justNow')
  if (diffMin < 60) return `${diffMin}m`
  const diffH = Math.floor(diffMin / 60)
  if (diffH < 24) return `${diffH}h`
  return `${Math.floor(diffH / 24)}d`
}

const downloadStatusColor = (status) =>
  ({
    downloading: 'info',
    completed: 'positive',
    failed: 'negative',
    queued: 'grey-7',
    importing: 'amber',
    in_progress: 'info',
  })[status] || 'grey-7'

const downloadStatusIcon = (status) =>
  ({
    downloading: 'mdi-download',
    completed: 'mdi-check',
    failed: 'mdi-alert',
    queued: 'mdi-clock-outline',
    importing: 'mdi-import',
    in_progress: 'mdi-progress-download',
  })[status] || 'mdi-help'

// Data loading
const loadAll = () =>
  Promise.all([
    loadHealth(),
    loadStats(),
    loadSessions(),
    loadDownloads(),
    loadSystemInfo(),
    loadStorage(),
  ])

const loadHealth = async () => {
  try {
    await api.get('/api/settings/system')
    systemHealth.value = 'healthy'
  } catch (e) {
    logger.warn('System health probe failed', e)
    systemHealth.value = 'unhealthy'
  }
}

const loadStats = async () => {
  try {
    const mediaTypes = ['MOVIES', 'SHOWS', 'SONGS', 'GAMES', 'BOOKS']
    const [usersRes, totalRes, ...mediaRes] = await Promise.all([
      api.get('/api/users'),
      api.get('/api/media', { params: { per_page: 1 } }),
      ...mediaTypes.map((media_type) =>
        api.get('/api/media', { params: { media_type, per_page: 1 } }),
      ),
    ])
    stats.totalUsers = (usersRes.data || []).length
    try {
      const onlineRes = await api.get('/api/users/online')
      stats.activeUsers = onlineRes.data?.count ?? 0
    } catch (err) {
      logger.warn('Failed to load online user count:', err)
      stats.activeUsers = 0
    }
    stats.totalLibraryItems = totalRes?.data?.total || 0
    ;[stats.movieCount, stats.showCount, stats.musicCount, stats.gameCount, stats.bookCount] =
      mediaRes.map((r) => r?.data?.total || 0)
  } catch (error) {
    logger.error('Error loading stats:', error)
  }
}

const loadSessions = async () => {
  try {
    const res = await api.get('/api/sessions')
    sessions.value = res.data.sessions || []
    stats.activeStreams = res.data.active_count || 0
  } catch (error) {
    logger.error('Error loading sessions:', error)
  }
}

const loadDownloads = async () => {
  try {
    const all = (await api.get('/api/downloads')).data || []
    stats.activeDownloads = all.filter(
      (d) => d.status === 'downloading' || d.status === 'in_progress' || d.status === 'queued',
    ).length
    recentDownloads.value = [...all]
      .sort((a, b) => new Date(b.created_at) - new Date(a.created_at))
      .slice(0, 5)
  } catch (error) {
    logger.error('Error loading downloads:', error)
  }
}

const loadSystemInfo = async () => {
  try {
    const [i, d, l] = await Promise.all([
      api.get('/api/indexers'),
      api.get('/api/downloaders'),
      api.get('/api/libraries', { params: { include_disabled: true } }),
    ])
    systemInfo.activeIndexers = i.data?.length || 0
    systemInfo.activeDownloaders = d.data?.length || 0
    systemInfo.libraryCount = l.data?.length || 0
  } catch (error) {
    logger.error('Error loading system info:', error)
  }
}

const loadStorage = async () => {
  storageLoading.value = true
  try {
    storageData.value = (await api.get('/api/settings/storage/overview')).data
  } catch (error) {
    logger.error('Error loading storage:', error)
  } finally {
    storageLoading.value = false
  }
}

onMounted(() => loadAll())
</script>

<style lang="scss" scoped>
.stat-card {
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 10px;
  transition:
    transform 0.15s ease,
    box-shadow 0.15s ease;

  &.clickable {
    cursor: pointer;
    &:hover {
      transform: translateY(-1px);
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.25);
    }
  }
}

.stat-label {
  font-size: 0.75rem;
  color: #999;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}
.stat-value {
  font-size: 1.25rem;
  font-weight: 700;
  line-height: 1.3;
}
.stat-sub {
  font-size: 0.75rem;
  font-weight: 400;
  color: #888;
}

.dash-card {
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 10px;
}

.dash-heading {
  font-size: 0.85rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: #aaa;
}

.lib-chip {
  display: flex;
  align-items: center;
  padding: 6px 10px;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.04);
  font-size: 0.875rem;
}

.info-row {
  display: flex;
  justify-content: space-between;
  padding: 6px 0;
  font-size: 0.85rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  &:last-child {
    border-bottom: none;
  }
}

.action-btn {
  border-radius: 6px;
  font-size: 0.85rem;
  &:hover {
    background: rgba(255, 255, 255, 0.06);
  }
}
</style>
