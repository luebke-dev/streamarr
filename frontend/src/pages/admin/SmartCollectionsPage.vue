<template>
  <q-page class="q-pa-md">
    <div class="text-h4 q-mb-md">{{ $t('adminSmartCollections.title') }}</div>
    <div class="text-subtitle1 text-grey-7 q-mb-lg">
      {{ $t('adminSmartCollections.subtitle') }}
    </div>

    <q-card flat bordered>
      <q-card-section>
        <div class="row q-col-gutter-md q-mb-md">
          <div class="col-12 col-md-6">
            <q-input
              v-model="filter"
              :label="$t('common.search')"
              outlined dark dense clearable
            >
              <template v-slot:prepend>
                <q-icon name="mdi-magnify" />
              </template>
            </q-input>
          </div>
          <div class="col-12 col-md-6 text-right">
            <q-btn
              color="primary"
              icon="mdi-plus"
              :label="$t('adminSmartCollections.addRule')"
              @click="openCreate"
              unelevated
            />
          </div>
        </div>

        <q-table
          flat bordered dark
          :rows="filteredRows"
          :columns="columns"
          row-key="guid"
          :loading="loading"
          v-model:pagination="pagination"
          :rows-per-page-options="[10, 25, 50]"
        >
          <template v-slot:body-cell-status="props">
            <q-td :props="props">
              <q-chip
                v-if="props.row.last_run_status"
                :color="statusColor(props.row.last_run_status)"
                text-color="white" size="sm"
                :label="props.row.last_run_status"
              />
              <span v-else class="text-grey-6">—</span>
            </q-td>
          </template>
          <template v-slot:body-cell-enabled="props">
            <q-td :props="props">
              <q-toggle
                :model-value="props.row.enabled"
                @update:model-value="toggleEnabled(props.row, $event)"
                color="primary"
                dense
              />
            </q-td>
          </template>
          <template v-slot:body-cell-actions="props">
            <q-td :props="props">
              <q-btn
                flat dense round icon="mdi-play" color="positive" size="sm"
                @click="runNow(props.row)"
              >
                <q-tooltip>{{ $t('adminSmartCollections.runNow') }}</q-tooltip>
              </q-btn>
              <q-btn
                flat dense round icon="mdi-history" color="primary" size="sm"
                @click="openHistory(props.row)"
              >
                <q-tooltip>{{ $t('adminSmartCollections.history') }}</q-tooltip>
              </q-btn>
              <q-btn
                flat dense round icon="mdi-pencil" color="primary" size="sm"
                @click="openEdit(props.row)"
              >
                <q-tooltip>{{ $t('common.edit') }}</q-tooltip>
              </q-btn>
              <q-btn
                v-if="!props.row.is_system"
                flat dense round icon="mdi-delete" color="negative" size="sm"
                @click="confirmDelete(props.row)"
              >
                <q-tooltip>{{ $t('common.delete') }}</q-tooltip>
              </q-btn>
            </q-td>
          </template>
        </q-table>
      </q-card-section>
    </q-card>

    <!-- Create / edit dialog -->
    <q-dialog v-model="showDialog" persistent>
      <q-card dark style="min-width: 640px; max-width: 800px">
        <q-card-section>
          <div class="text-h6">
            {{ editMode
              ? $t('adminSmartCollections.editRule')
              : $t('adminSmartCollections.addRule') }}
          </div>
          <div v-if="form.is_system" class="text-caption text-warning q-mt-xs">
            {{ $t('adminSmartCollections.systemReadOnly') }}
          </div>
        </q-card-section>

        <q-card-section class="q-pt-none">
          <q-form @submit.prevent="save" class="q-gutter-md">
            <q-input
              outlined dark dense v-model="form.name"
              :label="$t('adminSmartCollections.fields.name')"
              :rules="[(v) => !!v || $t('common.required')]"
              :disable="form.is_system && editMode"
            />
            <q-input
              outlined dark dense v-model="form.description"
              :label="$t('adminSmartCollections.fields.description')"
              type="textarea" autogrow
              :disable="form.is_system && editMode"
            />

            <div class="row q-col-gutter-md">
              <q-select
                outlined dark dense class="col"
                v-model="form.media_type"
                :options="['MOVIE','SHOW']"
                :label="$t('adminSmartCollections.fields.mediaType')"
                :disable="form.is_system && editMode"
              />
              <q-select
                outlined dark dense class="col"
                v-model="form.builder_type"
                :options="builderOptions"
                :label="$t('adminSmartCollections.fields.builderType')"
                emit-value map-options
                :disable="form.is_system && editMode"
                @update:model-value="onBuilderChange"
              />
            </div>

            <div v-if="selectedBuilder" class="text-caption text-grey-6">
              <span v-if="selectedBuilder.requires_api_key">
                {{ $t('adminSmartCollections.builderNeedsApiKey') }}
              </span>
              <span v-else>{{ $t('adminSmartCollections.builderKeyless') }}</span>
            </div>

            <q-expansion-item
              :label="$t('adminSmartCollections.fields.builderConfig')"
              icon="mdi-tune-variant"
              default-opened
              header-class="text-primary"
              dark
            >
              <div class="q-pt-md">
                <DynamicConfigForm
                  v-if="selectedBuilder"
                  :schema="selectedBuilder.config_schema"
                  v-model="form.builder_config"
                  :disabled="form.is_system && editMode"
                />
                <div v-else class="text-grey-6 q-pa-md">
                  {{ $t('adminSmartCollections.pickBuilderFirst') }}
                </div>
              </div>
            </q-expansion-item>

            <q-expansion-item
              :label="$t('adminSmartCollections.fields.filters')"
              icon="mdi-filter-variant"
              header-class="text-primary"
              dark
            >
              <div class="q-pt-md">
                <DynamicConfigForm
                  :schema="filterSchema"
                  v-model="form.filters"
                  :disabled="form.is_system && editMode"
                />
              </div>
            </q-expansion-item>

            <div class="row q-col-gutter-md">
              <q-select
                outlined dark dense class="col"
                v-model="form.sync_mode"
                :options="['SYNC','APPEND']"
                :label="$t('adminSmartCollections.fields.syncMode')"
                :disable="form.is_system && editMode"
              />
              <q-input
                outlined dark dense class="col"
                v-model.number="form.item_limit"
                type="number" min="1" max="2000"
                :label="$t('adminSmartCollections.fields.itemLimit')"
                :disable="form.is_system && editMode"
              />
            </div>

            <q-input
              outlined dark dense
              v-model="form.schedule_cron"
              :label="$t('adminSmartCollections.fields.cron')"
              hint="0 6 * * *"
              :rules="[(v) => !!v || $t('common.required')]"
            />

            <q-toggle
              v-model="form.enabled"
              :label="$t('adminSmartCollections.fields.enabled')"
              color="primary"
            />
          </q-form>
        </q-card-section>

        <q-card-actions align="right">
          <q-btn flat v-close-popup :label="$t('common.cancel')" />
          <q-btn color="primary" unelevated :label="$t('common.save')" @click="save" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Run-history dialog -->
    <q-dialog v-model="showHistory">
      <q-card dark style="min-width: 720px; max-width: 900px">
        <q-card-section>
          <div class="text-h6">{{ $t('adminSmartCollections.history') }}</div>
          <div class="text-caption text-grey-6">{{ historyRule?.name }}</div>
        </q-card-section>
        <q-card-section class="q-pt-none">
          <q-table
            flat bordered dark
            :rows="historyRuns"
            :columns="historyColumns"
            row-key="guid"
            :loading="historyLoading"
            :rows-per-page-options="[10,25]"
          />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat v-close-popup :label="$t('common.close')" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import DynamicConfigForm from 'src/components/DynamicConfigForm.vue'
import {
  createSmartCollection,
  deleteSmartCollection,
  listBuilders,
  listSmartCollectionRuns,
  listSmartCollections,
  runSmartCollectionNow,
  updateSmartCollection,
} from 'src/services/smartCollectionService'

// Filter DSL exposed as a static schema (no backend round-trip needed —
// it doesn't change without code release). Mirrors filter_resolved &
// apply_media_filters_to_query in backend/smart_collections/filters.py.
const filterSchema = {
  min_rating: { type: 'integer', hint: '0–10 (TMDb vote_average)' },
  max_rating: { type: 'integer', hint: '0–10' },
  min_year: { type: 'integer' },
  max_year: { type: 'integer' },
  min_age: { type: 'integer', hint: 'years (parental rating floor)' },
  max_age: { type: 'integer', hint: 'years (parental rating ceiling)' },
  availability: {
    type: 'string_list',
    options: ['available', 'downloadable', 'unknown'],
    hint: 'allowed availability_status values',
  },
  language: {
    type: 'string_list',
    hint: 'ISO 639-1 codes; only refs with that original_language pass',
  },
  genre_in: {
    type: 'string_list',
    hint: 'case-insensitive genre names; any-match',
  },
  genre_not_in: { type: 'string_list', hint: 'exclude these genres' },
  require_files: { type: 'boolean', hint: 'drop items without local files' },
}

const $q = useQuasar()
const { t } = useI18n()

const rows = ref([])
const loading = ref(false)
const filter = ref('')
const pagination = ref({ rowsPerPage: 25 })

const builders = ref([])
const showDialog = ref(false)
const editMode = ref(false)
const showHistory = ref(false)
const historyRule = ref(null)
const historyRuns = ref([])
const historyLoading = ref(false)

const _emptyForm = () => ({
  guid: null,
  name: '',
  description: '',
  media_type: 'MOVIE',
  builder_type: 'tmdb',
  builder_config: {},
  filters: {},
  sync_mode: 'SYNC',
  item_limit: 80,
  schedule_cron: '0 */6 * * *',
  enabled: true,
  is_system: false,
})
const form = ref(_emptyForm())

const columns = computed(() => [
  { name: 'name', label: t('adminSmartCollections.columnName'), field: 'name', align: 'left', sortable: true },
  { name: 'media_type', label: t('adminSmartCollections.columnMediaType'), field: 'media_type', sortable: true },
  { name: 'builder_type', label: t('adminSmartCollections.columnBuilder'), field: 'builder_type', sortable: true },
  { name: 'schedule_cron', label: t('adminSmartCollections.columnCron'), field: 'schedule_cron' },
  { name: 'last_run_at', label: t('adminSmartCollections.columnLastRun'), field: 'last_run_at',
    format: (v) => (v ? new Date(v).toLocaleString() : '—'), sortable: true },
  { name: 'status', label: t('adminSmartCollections.columnStatus'), field: 'last_run_status' },
  { name: 'enabled', label: t('adminSmartCollections.columnEnabled'), field: 'enabled' },
  { name: 'actions', label: t('common.actions'), field: 'guid', align: 'right' },
])

const historyColumns = computed(() => [
  { name: 'started_at', label: t('adminSmartCollections.runStarted'), field: 'started_at',
    format: (v) => new Date(v).toLocaleString() },
  { name: 'status', label: t('adminSmartCollections.columnStatus'), field: 'status' },
  { name: 'added', label: '+items', field: 'items_added' },
  { name: 'removed', label: '−items', field: 'items_removed' },
  { name: 'unresolved', label: t('adminSmartCollections.unresolved'), field: 'items_unresolved' },
  { name: 'duration_ms', label: 'ms', field: 'duration_ms' },
  { name: 'error', label: 'error', field: 'error', format: (v) => v || '' },
])

const builderOptions = computed(() =>
  builders.value.map((b) => ({ label: b.type, value: b.type }))
)
const selectedBuilder = computed(() =>
  builders.value.find((b) => b.type === form.value.builder_type) || null
)

const filteredRows = computed(() => {
  const q = filter.value?.toLowerCase()
  if (!q) return rows.value
  return rows.value.filter((r) => r.name.toLowerCase().includes(q))
})

function statusColor(s) {
  if (s === 'SUCCESS') return 'positive'
  if (s === 'FAILED') return 'negative'
  if (s === 'RUNNING' || s === 'PENDING') return 'info'
  return 'grey'
}

async function load() {
  loading.value = true
  try {
    rows.value = await listSmartCollections()
  } catch (e) {
    $q.notify({ type: 'negative', message: e?.message || t('common.error') })
  } finally { loading.value = false }
}

async function loadBuilders() {
  try { builders.value = await listBuilders() } catch { /* ignore */ }
}

function onBuilderChange() {
  if (!selectedBuilder.value) return
  const supports = selectedBuilder.value.supported_media_types
  if (supports?.length && !supports.includes(form.value.media_type)) {
    form.value.media_type = supports[0]
  }
}

function openCreate() {
  editMode.value = false
  form.value = _emptyForm()
  showDialog.value = true
}

function openEdit(row) {
  editMode.value = true
  form.value = {
    ...row,
    builder_config: { ...(row.builder_config || {}) },
    filters: { ...(row.filters || {}) },
  }
  showDialog.value = true
}

async function save() {
  const payload = {
    name: form.value.name,
    description: form.value.description || null,
    media_type: form.value.media_type,
    builder_type: form.value.builder_type,
    builder_config: form.value.builder_config || {},
    filters: form.value.filters || {},
    sync_mode: form.value.sync_mode,
    item_limit: form.value.item_limit || null,
    schedule_cron: form.value.schedule_cron,
    enabled: form.value.enabled,
  }
  try {
    if (editMode.value) {
      await updateSmartCollection(form.value.guid, payload)
    } else {
      await createSmartCollection(payload)
    }
    $q.notify({ type: 'positive', message: t('common.saved') })
    showDialog.value = false
    await load()
  } catch (e) {
    $q.notify({ type: 'negative', message: e?.response?.data?.detail || e.message })
  }
}

async function toggleEnabled(row, value) {
  try {
    await updateSmartCollection(row.guid, { enabled: value })
    row.enabled = value
  } catch (e) {
    $q.notify({ type: 'negative', message: e?.response?.data?.detail || e.message })
  }
}

async function runNow(row) {
  try {
    await runSmartCollectionNow(row.guid)
    $q.notify({ type: 'positive', message: t('adminSmartCollections.runQueued') })
  } catch (e) {
    $q.notify({ type: 'negative', message: e?.response?.data?.detail || e.message })
  }
}

async function openHistory(row) {
  historyRule.value = row
  historyRuns.value = []
  historyLoading.value = true
  showHistory.value = true
  try {
    historyRuns.value = await listSmartCollectionRuns(row.guid, 50)
  } finally { historyLoading.value = false }
}

function confirmDelete(row) {
  $q.dialog({
    title: t('adminSmartCollections.deleteConfirmTitle'),
    message: t('adminSmartCollections.deleteConfirm', { name: row.name }),
    ok: { label: t('common.delete'), color: 'negative' },
    cancel: true,
    dark: true,
  }).onOk(async () => {
    try {
      await deleteSmartCollection(row.guid)
      await load()
    } catch (e) {
      $q.notify({ type: 'negative', message: e?.response?.data?.detail || e.message })
    }
  })
}

onMounted(async () => {
  await Promise.all([load(), loadBuilders()])
})
</script>
