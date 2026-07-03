<template>
  <q-page class="q-pa-md">
    <div class="text-h4 q-mb-md">{{ $t('adminMassOperations.title') }}</div>
    <div class="text-subtitle1 text-grey-7 q-mb-lg">
      {{ $t('adminMassOperations.subtitle') }}
    </div>

    <q-card flat bordered>
      <q-card-section>
        <div class="row q-col-gutter-md q-mb-md">
          <div class="col-12 col-md-6">
            <q-input v-model="filter" :label="$t('common.search')" outlined dark dense clearable>
              <template v-slot:prepend><q-icon name="mdi-magnify" /></template>
            </q-input>
          </div>
          <div class="col-12 col-md-6 text-right">
            <q-btn color="primary" icon="mdi-plus"
                   :label="$t('adminMassOperations.addRule')" @click="openCreate" unelevated />
          </div>
        </div>

        <q-table flat bordered dark
          :rows="filteredRows" :columns="columns" row-key="guid"
          :loading="loading" v-model:pagination="pagination"
          :rows-per-page-options="[10,25,50]"
        >
          <template v-slot:body-cell-action="props">
            <q-td :props="props">
              <q-chip size="sm" color="primary" text-color="white" :label="props.row.action?.type || '—'" />
            </q-td>
          </template>
          <template v-slot:body-cell-enabled="props">
            <q-td :props="props">
              <q-toggle :model-value="props.row.enabled"
                @update:model-value="toggleEnabled(props.row, $event)" color="primary" dense />
            </q-td>
          </template>
          <template v-slot:body-cell-actions="props">
            <q-td :props="props">
              <q-btn flat dense round icon="mdi-eye" color="info" size="sm"
                @click="dryRun(props.row)">
                <q-tooltip>{{ $t('adminMassOperations.dryRun') }}</q-tooltip>
              </q-btn>
              <q-btn flat dense round icon="mdi-play" color="positive" size="sm"
                @click="runNow(props.row)">
                <q-tooltip>{{ $t('adminMassOperations.runNow') }}</q-tooltip>
              </q-btn>
              <q-btn flat dense round icon="mdi-pencil" color="primary" size="sm"
                @click="openEdit(props.row)">
                <q-tooltip>{{ $t('common.edit') }}</q-tooltip>
              </q-btn>
              <q-btn v-if="!props.row.is_system" flat dense round icon="mdi-delete"
                color="negative" size="sm" @click="confirmDelete(props.row)">
                <q-tooltip>{{ $t('common.delete') }}</q-tooltip>
              </q-btn>
            </q-td>
          </template>
        </q-table>
      </q-card-section>
    </q-card>

    <!-- Create / edit dialog -->
    <q-dialog v-model="showDialog" persistent>
      <q-card dark style="min-width: 700px; max-width: 900px">
        <q-card-section>
          <div class="text-h6">
            {{ editMode
              ? $t('adminMassOperations.editRule')
              : $t('adminMassOperations.addRule') }}
          </div>
          <div v-if="form.is_system" class="text-caption text-warning q-mt-xs">
            {{ $t('adminMassOperations.systemReadOnly') }}
          </div>
        </q-card-section>

        <q-card-section class="q-pt-none">
          <q-form @submit.prevent="save" class="q-gutter-md">
            <q-input outlined dark dense v-model="form.name"
              :label="$t('adminMassOperations.fields.name')"
              :rules="[(v) => !!v || $t('common.required')]"
              :disable="form.is_system && editMode" />
            <q-input outlined dark dense v-model="form.description"
              :label="$t('adminMassOperations.fields.description')"
              type="textarea" autogrow
              :disable="form.is_system && editMode" />

            <q-expansion-item
              :label="$t('adminMassOperations.fields.targetFilter')"
              icon="mdi-filter-variant"
              default-opened
              header-class="text-primary"
              dark
            >
              <div class="q-pt-md">
                <DynamicConfigForm
                  :schema="targetFilterSchema"
                  v-model="form.target_filter"
                  :disabled="form.is_system && editMode"
                />
              </div>
            </q-expansion-item>

            <q-select
              outlined dark dense
              :model-value="form.action?.type || 'set_genre'"
              :options="actionTypeOptions"
              emit-value map-options
              :label="$t('adminMassOperations.fields.actionType')"
              :disable="form.is_system && editMode"
              @update:model-value="onActionTypeChange"
            />
            <DynamicConfigForm
              :schema="actionSchemaForType(form.action?.type)"
              v-model="form.action"
              :disabled="form.is_system && editMode"
            />

            <q-input outlined dark dense
              v-model="form.schedule_cron"
              :label="$t('adminMassOperations.fields.cron')"
              :hint="$t('adminMassOperations.cronHint')" />

            <q-toggle v-model="form.enabled"
              :label="$t('adminMassOperations.fields.enabled')" color="primary" />
          </q-form>
        </q-card-section>

        <q-card-actions align="right">
          <q-btn flat v-close-popup :label="$t('common.cancel')" />
          <q-btn color="primary" unelevated :label="$t('common.save')" @click="save" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Dry-run result dialog -->
    <q-dialog v-model="showDryRun">
      <q-card dark style="min-width: 600px">
        <q-card-section>
          <div class="text-h6">{{ $t('adminMassOperations.dryRunResult') }}</div>
          <div class="text-caption text-grey-6">{{ dryRunRule?.name }}</div>
        </q-card-section>
        <q-card-section v-if="dryRunData" class="q-pt-none">
          <div class="row q-col-gutter-md q-mb-md">
            <q-chip color="info" text-color="white"
              :label="`matched: ${dryRunData.items_matched}`" />
            <q-chip color="primary" text-color="white"
              :label="`would update: ${dryRunData.items_updated}`" />
            <q-chip color="grey" text-color="white"
              :label="`skipped: ${dryRunData.items_skipped}`" />
            <q-chip color="secondary" text-color="white"
              :label="`${dryRunData.duration_ms} ms`" />
          </div>
          <div class="text-caption text-grey-7 q-mb-xs">
            {{ $t('adminMassOperations.firstMatches') }}
          </div>
          <div class="text-mono">
            <div v-for="g in dryRunData.changed_sample" :key="g">{{ g }}</div>
          </div>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat v-close-popup :label="$t('common.close')" />
          <q-btn v-if="dryRunRule && !dryRunRule.is_system"
                 color="positive" unelevated icon="mdi-play"
                 :label="$t('adminMassOperations.applyNow')"
                 @click="applyAfterDryRun" />
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
  createMassOperation,
  deleteMassOperation,
  dryRunMassOperation,
  listMassOperations,
  runMassOperationNow,
  updateMassOperation,
} from 'src/services/massOperationService'

// Filter schema for ``target_filter`` — mirrors the smart-collections
// page minus the rating fields (which only apply to ExternalRef.extra).
const targetFilterSchema = {
  media_type_in: {
    type: 'string_list',
    options: ['MOVIES', 'SHOWS'],
    hint: 'restrict to top-level media types',
  },
  min_year: { type: 'integer' },
  max_year: { type: 'integer' },
  min_age: { type: 'integer' },
  max_age: { type: 'integer' },
  availability: {
    type: 'string_list',
    options: ['available', 'downloadable', 'unknown'],
  },
  genre_in: { type: 'string_list' },
  genre_not_in: { type: 'string_list' },
  require_files: { type: 'boolean' },
}

// Action-type → field schema. The "type" field stays in form.action so
// the dynamic form just augments it with the per-action fields.
const actionTypeOptions = [
  { label: 'Set genres', value: 'set_genre' },
  { label: 'Set parental rating (min_age)', value: 'set_min_age' },
  { label: 'Set availability', value: 'set_availability' },
  { label: 'Set description', value: 'set_description' },
  { label: 'Set poster URL', value: 'set_poster_path' },
  { label: 'Clear a field', value: 'clear' },
]

function actionSchemaForType(actionType) {
  // ``type`` is intentionally excluded — the outer select drives it.
  switch (actionType) {
    case 'set_genre':
      return {
        values: { type: 'string_list', required: true, hint: 'list of genre names' },
        mode: {
          type: 'select', options: ['add', 'set'], required: true,
          hint: '"add" appends; "set" replaces',
        },
      }
    case 'set_min_age':
      return {
        value: { type: 'integer', required: true, hint: 'minimum viewer age in years' },
      }
    case 'set_availability':
      return {
        value: {
          type: 'select',
          options: ['available', 'downloadable', 'unknown'],
          required: true,
        },
      }
    case 'set_description':
    case 'set_poster_path':
      return {
        value: { type: 'string', required: true },
      }
    case 'clear':
      return {
        field: {
          type: 'select',
          options: [
            'description', 'tagline', 'poster_path', 'backdrop_path',
            'content_rating', 'min_age',
          ],
          required: true,
          hint: 'column to NULL on every matching item',
        },
      }
    default:
      return {}
  }
}

function onActionTypeChange(newType) {
  // Reset the action object when the type changes so we don't carry over
  // fields from the previous shape.
  form.value.action = { type: newType }
}

const $q = useQuasar()
const { t } = useI18n()

const rows = ref([])
const loading = ref(false)
const filter = ref('')
const pagination = ref({ rowsPerPage: 25 })

const showDialog = ref(false)
const editMode = ref(false)
const showDryRun = ref(false)
const dryRunRule = ref(null)
const dryRunData = ref(null)

const _emptyForm = () => ({
  guid: null,
  name: '',
  description: '',
  target_filter: {},
  action: { type: 'set_genre', values: [], mode: 'add' },
  schedule_cron: null,
  enabled: true,
  is_system: false,
})
const form = ref(_emptyForm())

const columns = computed(() => [
  { name: 'name', label: t('adminMassOperations.columnName'), field: 'name', align: 'left', sortable: true },
  { name: 'action', label: t('adminMassOperations.columnAction'), field: 'action' },
  { name: 'schedule_cron', label: t('adminMassOperations.columnCron'), field: 'schedule_cron',
    format: (v) => v || '—' },
  { name: 'last_run_at', label: t('adminMassOperations.columnLastRun'), field: 'last_run_at',
    format: (v) => (v ? new Date(v).toLocaleString() : '—') },
  { name: 'last_run_status', label: t('adminMassOperations.columnStatus'),
    field: 'last_run_status', format: (v) => v || '—' },
  { name: 'enabled', label: t('adminMassOperations.columnEnabled'), field: 'enabled' },
  { name: 'actions', label: t('common.actions'), field: 'guid', align: 'right' },
])

const filteredRows = computed(() => {
  const q = filter.value?.toLowerCase()
  if (!q) return rows.value
  return rows.value.filter((r) => r.name.toLowerCase().includes(q))
})

async function load() {
  loading.value = true
  try {
    rows.value = await listMassOperations()
  } catch (e) {
    $q.notify({ type: 'negative', message: e?.message || t('common.error') })
  } finally { loading.value = false }
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
    target_filter: { ...(row.target_filter || {}) },
    action: { ...(row.action || { type: 'set_genre' }) },
  }
  showDialog.value = true
}

async function save() {
  const payload = {
    name: form.value.name,
    description: form.value.description || null,
    target_filter: form.value.target_filter || {},
    action: form.value.action || {},
    schedule_cron: form.value.schedule_cron || null,
    enabled: form.value.enabled,
  }
  try {
    if (editMode.value) {
      await updateMassOperation(form.value.guid, payload)
    } else {
      await createMassOperation(payload)
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
    await updateMassOperation(row.guid, { enabled: value })
    row.enabled = value
  } catch (e) {
    $q.notify({ type: 'negative', message: e?.response?.data?.detail || e.message })
  }
}

async function dryRun(row) {
  dryRunRule.value = row
  dryRunData.value = null
  showDryRun.value = true
  try {
    dryRunData.value = await dryRunMassOperation(row.guid)
  } catch (e) {
    showDryRun.value = false
    $q.notify({ type: 'negative', message: e?.response?.data?.detail || e.message })
  }
}

async function applyAfterDryRun() {
  if (!dryRunRule.value) return
  try {
    await runMassOperationNow(dryRunRule.value.guid)
    $q.notify({ type: 'positive', message: t('adminMassOperations.runQueued') })
    showDryRun.value = false
  } catch (e) {
    $q.notify({ type: 'negative', message: e?.response?.data?.detail || e.message })
  }
}

async function runNow(row) {
  $q.dialog({
    title: t('adminMassOperations.runConfirmTitle'),
    message: t('adminMassOperations.runConfirm', { name: row.name }),
    ok: { label: t('adminMassOperations.applyNow'), color: 'positive' },
    cancel: true,
    dark: true,
  }).onOk(async () => {
    try {
      await runMassOperationNow(row.guid)
      $q.notify({ type: 'positive', message: t('adminMassOperations.runQueued') })
    } catch (e) {
      $q.notify({ type: 'negative', message: e?.response?.data?.detail || e.message })
    }
  })
}

function confirmDelete(row) {
  $q.dialog({
    title: t('adminMassOperations.deleteConfirmTitle'),
    message: t('adminMassOperations.deleteConfirm', { name: row.name }),
    ok: { label: t('common.delete'), color: 'negative' },
    cancel: true,
    dark: true,
  }).onOk(async () => {
    try {
      await deleteMassOperation(row.guid)
      await load()
    } catch (e) {
      $q.notify({ type: 'negative', message: e?.response?.data?.detail || e.message })
    }
  })
}

onMounted(load)
</script>

<style scoped>
.text-mono {
  font-family: monospace;
  font-size: 12px;
  max-height: 240px;
  overflow-y: auto;
  background: rgba(255,255,255,0.04);
  padding: 8px;
  border-radius: 4px;
}
</style>
