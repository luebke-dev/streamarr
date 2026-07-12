<template>
  <div class="marker-editor">
    <div class="section-header q-mb-md row items-center justify-between">
      <h5 class="text-white q-my-none">
        <q-icon name="mdi-skip-next" class="q-mr-sm" />
        {{ $t('markers.title') }}
      </h5>
      <div class="row q-gutter-sm">
        <q-btn
          v-if="mediaType === 'EPISODES' || mediaType === 'SEASONS'"
          flat
          dense
          color="primary"
          icon="mdi-auto-fix"
          :label="$t('markers.detectAuto')"
          :loading="detecting"
          @click="triggerDetection"
        />
        <q-btn
          flat
          dense
          color="primary"
          icon="mdi-plus"
          :label="$t('markers.addMarker')"
          @click="showAddDialog = true"
        />
      </div>
    </div>

    <!-- Markers Table -->
    <q-table
      :rows="markers"
      :columns="columns"
      row-key="guid"
      class="bg-transparent"
      dark
      flat
      dense
      :no-data-label="$t('markers.noMarkers')"
      hide-pagination
    >
      <template v-slot:body-cell-type="props">
        <q-td :props="props">
          <q-chip :color="typeColor(props.row.marker_type)" text-color="white" size="sm" dense>
            {{ $t(`markers.types.${props.row.marker_type}`) }}
          </q-chip>
        </q-td>
      </template>

      <template v-slot:body-cell-source="props">
        <q-td :props="props">
          <q-chip
            :color="props.row.source === 'manual' ? 'primary' : 'grey-7'"
            text-color="white"
            size="sm"
            dense
          >
            {{ props.row.source }}
          </q-chip>
          <span v-if="props.row.confidence" class="text-grey-5 q-ml-xs text-caption">
            {{ Math.round(props.row.confidence * 100) }}%
          </span>
        </q-td>
      </template>

      <template v-slot:body-cell-start="props">
        <q-td :props="props">
          {{ formatTime(props.row.start_seconds) }}
        </q-td>
      </template>

      <template v-slot:body-cell-end="props">
        <q-td :props="props">
          {{ formatTime(props.row.end_seconds) }}
        </q-td>
      </template>

      <template v-slot:body-cell-actions="props">
        <q-td :props="props" class="text-right">
          <q-btn flat dense icon="mdi-pencil" size="sm" @click="editMarker(props.row)" />
          <q-btn
            flat
            dense
            icon="mdi-delete"
            size="sm"
            color="negative"
            @click="deleteMarker(props.row)"
          />
        </q-td>
      </template>
    </q-table>

    <!-- Visual Timeline -->
    <div v-if="markers.length > 0 && duration > 0" class="marker-timeline q-mt-md">
      <div class="timeline-bar">
        <div
          v-for="marker in markers"
          :key="marker.guid"
          class="timeline-segment"
          :class="marker.marker_type"
          :style="{
            left: `${(marker.start_seconds / duration) * 100}%`,
            width: `${((marker.end_seconds - marker.start_seconds) / duration) * 100}%`,
          }"
        >
          <q-tooltip>
            {{ $t(`markers.types.${marker.marker_type}`) }}:
            {{ formatTime(marker.start_seconds) }} - {{ formatTime(marker.end_seconds) }}
          </q-tooltip>
        </div>
      </div>
    </div>

    <!-- Add/Edit Dialog -->
    <q-dialog v-model="showAddDialog" persistent>
      <q-card style="min-width: 350px" dark>
        <q-card-section>
          <div class="text-h6">
            {{ editingMarker ? $t('markers.editMarker') : $t('markers.addMarker') }}
          </div>
        </q-card-section>

        <q-card-section class="q-gutter-md">
          <q-select
            v-model="form.marker_type"
            :options="typeOptions"
            :label="$t('markers.type')"
            outlined
            dark
            emit-value
            map-options
          />
          <q-input
            v-if="form.marker_type === 'song' || form.marker_type === 'ad'"
            v-model="form.label"
            :label="$t('markers.label')"
            outlined
            dark
            :placeholder="form.marker_type === 'song' ? 'Song title' : 'Ad name'"
          />
          <q-input
            v-model="form.start_time"
            :label="$t('markers.startTime')"
            outlined
            dark
            :hint="$t('markers.timeFormatHint')"
            placeholder="0:00"
          />
          <q-input
            v-model="form.end_time"
            :label="$t('markers.endTime')"
            outlined
            dark
            :hint="$t('markers.timeFormatHint')"
            placeholder="1:30"
          />
        </q-card-section>

        <q-card-actions align="right">
          <q-btn flat :label="$t('common.cancel')" @click="closeDialog" />
          <q-btn
            unelevated
            color="primary"
            :label="$t('common.save')"
            @click="saveMarker"
            :loading="saving"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import {
  getAllMarkers,
  updateMarker,
  createMarker,
  deleteMarker as deleteMarkerRequest,
  detectMarkers,
} from 'src/services/mediaComponentsService'
import { useI18n } from 'vue-i18n'
import { useQuasar } from 'quasar'
import { logger } from 'src/utils/logger'

const props = defineProps({
  mediaId: { type: String, required: true },
  mediaType: { type: String, default: '' },
  seasonId: { type: String, default: null },
  duration: { type: Number, default: 0 },
})

const { t } = useI18n()
const $q = useQuasar()

const markers = ref([])
const showAddDialog = ref(false)
const editingMarker = ref(null)
const saving = ref(false)
const detecting = ref(false)

const form = ref({
  marker_type: 'intro',
  start_time: '',
  end_time: '',
  label: '',
})

const columns = [
  { name: 'type', label: t('markers.type'), field: 'marker_type', align: 'left' },
  { name: 'source', label: t('markers.source'), field: 'source', align: 'left' },
  { name: 'start', label: t('markers.start'), field: 'start_seconds', align: 'left' },
  { name: 'end', label: t('markers.end'), field: 'end_seconds', align: 'left' },
  { name: 'actions', label: '', field: 'actions', align: 'right' },
]

const typeOptions = [
  { label: t('markers.types.intro'), value: 'intro' },
  { label: t('markers.types.outro'), value: 'outro' },
  { label: t('markers.types.credits'), value: 'credits' },
  { label: t('markers.types.song'), value: 'song' },
  { label: t('markers.types.ad'), value: 'ad' },
]

const typeColor = (type) => {
  switch (type) {
    case 'intro':
      return 'blue'
    case 'outro':
      return 'orange'
    case 'credits':
      return 'purple'
    case 'song':
      return 'teal'
    case 'ad':
      return 'red'
    default:
      return 'grey'
  }
}

const formatTime = (seconds) => {
  if (seconds == null) return '--:--'
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

const parseTime = (input) => {
  if (!input) return 0
  if (input.includes(':')) {
    const parts = input.split(':')
    return parseInt(parts[0]) * 60 + parseFloat(parts[1])
  }
  return parseFloat(input) || 0
}

const loadMarkers = async () => {
  try {
    markers.value = await getAllMarkers(props.mediaId)
  } catch (error) {
    logger.error('Failed to load markers:', error)
  }
}

const saveMarker = async () => {
  saving.value = true
  try {
    const data = {
      marker_type: form.value.marker_type,
      start_seconds: parseTime(form.value.start_time),
      end_seconds: parseTime(form.value.end_time),
      source: 'manual',
      label: form.value.label || null,
    }

    if (editingMarker.value) {
      await updateMarker(editingMarker.value.guid, {
        start_seconds: data.start_seconds,
        end_seconds: data.end_seconds,
      })
    } else {
      await createMarker(props.mediaId, data)
    }

    await loadMarkers()
    closeDialog()
    $q.notify({ type: 'positive', message: t('markers.saved') })
  } catch (error) {
    logger.error('Failed to save marker:', error)
    $q.notify({ type: 'negative', message: t('markers.saveError') })
  } finally {
    saving.value = false
  }
}

const editMarker = (marker) => {
  editingMarker.value = marker
  form.value = {
    marker_type: marker.marker_type,
    start_time: formatTime(marker.start_seconds),
    end_time: formatTime(marker.end_seconds),
    label: marker.label || '',
  }
  showAddDialog.value = true
}

const deleteMarker = async (marker) => {
  $q.dialog({
    title: t('markers.deleteConfirm'),
    message: t('markers.deleteMessage'),
    cancel: true,
    persistent: true,
    dark: true,
  }).onOk(async () => {
    try {
      await deleteMarkerRequest(marker.guid)
      await loadMarkers()
      $q.notify({ type: 'positive', message: t('markers.deleted') })
    } catch (error) {
      logger.error('Failed to delete marker:', error)
    }
  })
}

const triggerDetection = async () => {
  detecting.value = true
  try {
    const id = props.seasonId || props.mediaId
    const endpoint =
      props.mediaType === 'SEASONS' || props.mediaType === 'EPISODES'
        ? `/api/media/seasons/${id}/detect-markers`
        : `/api/media/${props.mediaId}/detect-credits`

    await detectMarkers(endpoint)
    $q.notify({ type: 'info', message: t('markers.detectionStarted') })
  } catch (error) {
    logger.error('Failed to trigger detection:', error)
    $q.notify({ type: 'negative', message: t('markers.detectionError') })
  } finally {
    detecting.value = false
  }
}

const closeDialog = () => {
  showAddDialog.value = false
  editingMarker.value = null
  form.value = { marker_type: 'intro', start_time: '', end_time: '', label: '' }
}

onMounted(loadMarkers)
</script>

<style lang="scss" scoped>
.marker-timeline {
  .timeline-bar {
    position: relative;
    height: 8px;
    background: rgba(255, 255, 255, 0.1);
    border-radius: 4px;
    overflow: hidden;
  }

  .timeline-segment {
    position: absolute;
    top: 0;
    height: 100%;
    border-radius: 4px;
    cursor: pointer;

    &.intro {
      background: rgba(33, 150, 243, 0.7);
    }
    &.outro {
      background: rgba(255, 152, 0, 0.7);
    }
    &.credits {
      background: rgba(156, 39, 176, 0.7);
    }
    &.song {
      background: rgba(0, 150, 136, 0.7);
    }
    &.ad {
      background: rgba(244, 67, 54, 0.7);
    }
  }
}
</style>
