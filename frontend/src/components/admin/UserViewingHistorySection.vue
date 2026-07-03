<template>
  <q-card flat bordered>
    <q-card-section>
      <div class="text-h6 q-mb-md">
        <q-icon name="mdi-history" class="q-mr-sm" color="deep-purple" />
        {{ $t('adminUserPage.viewingHistory') }}
      </div>

      <div v-if="items.length === 0 && !loading" class="text-center q-pa-lg text-grey">
        {{ $t('adminUserPage.noViewingHistory') }}
      </div>

      <q-table
        v-else
        flat
        bordered
        dark
        :rows="items"
        :columns="columns"
        row-key="guid"
        :rows-per-page-options="[10, 25, 50]"
        v-model:pagination="paginationModel"
        :loading="loading"
        @request="onRequest"
      >
        <template #body-cell-media="props">
          <q-td :props="props">
            <div class="row items-center no-wrap q-gutter-sm">
              <q-img
                v-if="props.row.media_item?.poster_path"
                :src="getPosterUrl(props.row.media_item)"
                width="40px"
                ratio="2/3"
                class="rounded-borders"
              />
              <div>
                <div class="text-weight-medium">{{ getTitle(props.row) }}</div>
                <div
                  v-if="props.row.content_type === 'episode' && props.row.show_title"
                  class="text-caption text-grey"
                >
                  {{ props.row.show_title }}
                </div>
              </div>
            </div>
          </q-td>
        </template>

        <template #body-cell-type="props">
          <q-td :props="props">
            <q-badge
              :color="getContentTypeBadgeColor(props.row.content_type)"
              :label="getContentTypeLabel(props.row.content_type)"
            />
          </q-td>
        </template>

        <template #body-cell-progress="props">
          <q-td :props="props">
            <div class="row items-center q-gutter-sm" style="min-width: 140px">
              <q-linear-progress
                :value="(props.row.progress_percentage || 0) / 100"
                :color="props.row.is_completed ? 'positive' : 'primary'"
                track-color="grey-3"
                rounded
                size="8px"
                class="col"
              />
              <span class="text-caption" style="min-width: 35px">
                {{ Math.round(props.row.progress_percentage || 0) }}%
              </span>
            </div>
          </q-td>
        </template>

        <template #body-cell-duration="props">
          <q-td :props="props">
            {{ formatSeconds(props.row.progress_seconds) }} /
            {{ formatSeconds(props.row.duration_seconds) }}
          </q-td>
        </template>

        <template #body-cell-completed="props">
          <q-td :props="props">
            <q-icon
              :name="props.row.is_completed ? 'mdi-check-circle' : 'mdi-clock-outline'"
              :color="props.row.is_completed ? 'positive' : 'grey'"
              size="sm"
            />
          </q-td>
        </template>

        <template #body-cell-lastWatched="props">
          <q-td :props="props">{{ formatLocaleDate(props.row.last_watched_at) }}</q-td>
        </template>
      </q-table>
    </q-card-section>
  </q-card>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { getTmdbImageUrl } from 'src/composables/useMediaFormatters'
import { overlayServeUrl } from 'src/utils/posters'

const props = defineProps({
  items: { type: Array, required: true },
  loading: { type: Boolean, default: false },
  pagination: { type: Object, required: true },
})

const emit = defineEmits(['request', 'update:pagination'])

const { t } = useI18n()

const paginationModel = computed({
  get: () => props.pagination,
  set: (value) => emit('update:pagination', value),
})

const columns = computed(() => [
  {
    name: 'media',
    label: t('adminUserPage.historyTitle'),
    field: 'media_item',
    align: 'left',
    sortable: false,
  },
  { name: 'type', label: t('adminUserPage.historyType'), field: 'content_type', align: 'center' },
  {
    name: 'progress',
    label: t('adminUserPage.historyProgress'),
    field: 'progress_percentage',
    align: 'left',
  },
  {
    name: 'duration',
    label: t('adminUserPage.historyDuration'),
    field: 'duration_seconds',
    align: 'left',
  },
  {
    name: 'completed',
    label: t('adminUserPage.historyCompleted'),
    field: 'is_completed',
    align: 'center',
  },
  {
    name: 'lastWatched',
    label: t('adminUserPage.historyLastWatched'),
    field: 'last_watched_at',
    align: 'left',
  },
])

const onRequest = (requestProps) => emit('request', requestProps)

const getPosterUrl = (mediaItem) => {
  const overlay = overlayServeUrl(mediaItem, 'POSTER')
  if (overlay) return overlay
  if (!mediaItem?.poster_path) return ''
  if (mediaItem.poster_path.startsWith('http')) return mediaItem.poster_path
  return getTmdbImageUrl(mediaItem.poster_path, 'w92')
}

const getTitle = (row) => {
  if (!row.media_item) return t('adminUserPage.unknown')
  if (row.content_type === 'episode') {
    const sNum = row.season_number
    const eNum = row.episode_number
    const prefix =
      sNum != null && eNum != null
        ? `S${String(sNum).padStart(2, '0')}E${String(eNum).padStart(2, '0')} `
        : ''
    return `${prefix}${row.media_item.title || ''}`
  }
  return row.media_item.title || ''
}

const getContentTypeLabel = (type) => {
  const labels = {
    movie: t('adminUserPage.typeMovie'),
    episode: t('adminUserPage.typeEpisode'),
    show: t('adminUserPage.typeShow'),
    game: t('adminUserPage.typeGame'),
  }
  return labels[type] || type
}

const getContentTypeBadgeColor = (type) => {
  const colors = { movie: 'primary', episode: 'orange', show: 'teal', game: 'purple' }
  return colors[type] || 'grey'
}

const formatSeconds = (seconds) => {
  if (!seconds) return '—'
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = Math.floor(seconds % 60)
  if (h > 0) return `${h}h ${m}m`
  if (m > 0) return `${m}m ${s}s`
  return `${s}s`
}

const formatLocaleDate = (dateString) => {
  if (!dateString) return t('adminUserPage.unknown')
  return new Date(dateString).toLocaleString()
}
</script>
