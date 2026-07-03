<template>
  <q-page class="q-pa-md">
    <div class="text-h4 q-mb-md">{{ $t('adminOverlays.title') }}</div>
    <div class="text-subtitle1 text-grey-7 q-mb-lg">
      {{ $t('adminOverlays.subtitle') }}
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
                   :label="$t('adminOverlays.addTemplate')" @click="openCreate" unelevated />
          </div>
        </div>

        <q-table flat bordered dark
          :rows="filteredRows" :columns="columns" row-key="guid"
          :loading="loading" v-model:pagination="pagination"
          :rows-per-page-options="[10,25,50]"
        >
          <template v-slot:body-cell-enabled="props">
            <q-td :props="props">
              <q-toggle :model-value="props.row.enabled"
                        @update:model-value="toggleEnabled(props.row, $event)"
                        color="primary" dense />
            </q-td>
          </template>
          <template v-slot:body-cell-actions="props">
            <q-td :props="props">
              <q-btn flat dense round icon="mdi-refresh" color="positive" size="sm"
                     @click="rerender(props.row)">
                <q-tooltip>{{ $t('adminOverlays.rerender') }}</q-tooltip>
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
    <q-dialog v-model="showDialog" persistent maximized-on-mobile>
      <q-card dark style="min-width: 880px; max-width: 1100px">
        <q-card-section>
          <div class="text-h6">
            {{ editMode ? $t('adminOverlays.editTemplate') : $t('adminOverlays.addTemplate') }}
          </div>
          <div v-if="form.is_system" class="text-caption text-warning q-mt-xs">
            {{ $t('adminOverlays.systemReadOnly') }}
          </div>
        </q-card-section>

        <q-card-section class="q-pt-none">
          <div class="row q-col-gutter-md">
            <div class="col-12 col-md-7">
              <q-form @submit.prevent="save" class="q-gutter-md">
                <q-input outlined dark dense v-model="form.name"
                  :label="$t('adminOverlays.fields.name')"
                  :rules="[(v) => !!v || $t('common.required')]"
                  :disable="form.is_system && editMode" />
                <q-input outlined dark dense v-model="form.description"
                  :label="$t('adminOverlays.fields.description')"
                  type="textarea" autogrow
                  :disable="form.is_system && editMode" />

                <div class="row q-col-gutter-md">
                  <q-select outlined dark dense class="col"
                    v-model="form.media_scope"
                    :options="['MOVIE','SHOW','BOTH']"
                    :label="$t('adminOverlays.fields.mediaScope')"
                    :disable="form.is_system && editMode" />
                  <q-select outlined dark dense class="col"
                    v-model="form.target"
                    :options="['POSTER','BACKDROP']"
                    :label="$t('adminOverlays.fields.target')"
                    :disable="form.is_system && editMode" />
                  <q-input outlined dark dense class="col"
                    v-model.number="form.z_order"
                    type="number"
                    :label="$t('adminOverlays.fields.zOrder')"
                    :disable="form.is_system && editMode" />
                </div>

                <q-expansion-item
                  :label="$t('adminOverlays.fields.condition')"
                  icon="mdi-filter-variant"
                  default-opened
                  header-class="text-primary"
                  dark
                >
                  <div class="q-pt-md">
                    <q-toggle
                      v-model="conditionEnabled"
                      :label="$t('adminOverlays.conditionEnable')"
                      :disable="form.is_system && editMode"
                      color="primary"
                      class="q-mb-md"
                      @update:model-value="onConditionEnabledChange"
                    />
                    <ConditionTreeEditor
                      v-if="conditionEnabled"
                      v-model="form.condition"
                      :disabled="form.is_system && editMode"
                    />
                    <div v-else class="text-grey-6 text-caption">
                      {{ $t('adminOverlays.conditionDisabled') }}
                    </div>
                  </div>
                </q-expansion-item>

                <q-expansion-item
                  :label="$t('adminOverlays.fields.elements')"
                  icon="mdi-format-list-bulleted-square"
                  default-opened
                  header-class="text-primary"
                  dark
                >
                  <div class="q-pt-md">
                    <OverlayElementsEditor
                      v-model="form.elements"
                      :disabled="form.is_system && editMode"
                    />
                  </div>
                </q-expansion-item>

                <q-toggle v-model="form.enabled"
                  :label="$t('adminOverlays.fields.enabled')" color="primary" />
              </q-form>
            </div>

            <!-- Live preview pane -->
            <div class="col-12 col-md-5">
              <div class="text-subtitle2 q-mb-sm">{{ $t('adminOverlays.preview') }}</div>
              <q-input outlined dark dense
                v-model="previewMediaGuid"
                :label="$t('adminOverlays.previewMediaGuid')"
                clearable
                @keyup.enter="refreshPreview"
              >
                <template v-slot:append>
                  <q-btn flat dense round icon="mdi-refresh" @click="refreshPreview" />
                </template>
              </q-input>
              <div class="q-mt-sm preview-frame">
                <img v-if="previewSrc" :src="previewSrc"
                     :alt="$t('adminOverlays.preview')"
                     class="full-width"
                     @error="onPreviewError" />
                <div v-else class="text-grey-6 q-pa-md">
                  {{ $t('adminOverlays.previewHint') }}
                </div>
              </div>
              <div v-if="previewError" class="text-negative text-caption q-mt-xs">
                {{ previewError }}
              </div>
            </div>
          </div>
        </q-card-section>

        <q-card-actions align="right">
          <q-btn flat v-close-popup :label="$t('common.cancel')" />
          <q-btn color="primary" unelevated :label="$t('common.save')" @click="save" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import ConditionTreeEditor from 'src/components/ConditionTreeEditor.vue'
import OverlayElementsEditor from 'src/components/OverlayElementsEditor.vue'
import {
  createOverlayTemplate,
  deleteOverlayTemplate,
  listOverlayTemplates,
  overlayPreviewUrl,
  rerenderOverlayTemplate,
  updateOverlayTemplate,
} from 'src/services/overlayService'

const $q = useQuasar()
const { t } = useI18n()

const rows = ref([])
const loading = ref(false)
const filter = ref('')
const pagination = ref({ rowsPerPage: 25 })

const showDialog = ref(false)
const editMode = ref(false)

const _emptyForm = () => ({
  guid: null,
  name: '',
  description: '',
  media_scope: 'BOTH',
  target: 'POSTER',
  condition: null,
  elements: [],
  z_order: 0,
  enabled: true,
  is_system: false,
})
const form = ref(_emptyForm())
const conditionEnabled = ref(false)

const previewMediaGuid = ref('')
const previewSrc = ref(null)
const previewError = ref(null)

const columns = computed(() => [
  { name: 'name', label: t('adminOverlays.columnName'), field: 'name', align: 'left', sortable: true },
  { name: 'media_scope', label: t('adminOverlays.columnScope'), field: 'media_scope' },
  { name: 'target', label: t('adminOverlays.columnTarget'), field: 'target' },
  { name: 'z_order', label: t('adminOverlays.columnZ'), field: 'z_order' },
  { name: 'enabled', label: t('adminOverlays.columnEnabled'), field: 'enabled' },
  { name: 'actions', label: t('common.actions'), field: 'guid', align: 'right' },
])

const filteredRows = computed(() => {
  const q = filter.value?.toLowerCase()
  if (!q) return rows.value
  return rows.value.filter((r) => r.name.toLowerCase().includes(q))
})

function onConditionEnabledChange(value) {
  if (value) {
    if (!form.value.condition) {
      form.value.condition = {
        all: [{ field: 'resolution.height', op: 'gte', value: 2160 }],
      }
    }
  } else {
    form.value.condition = null
  }
}

async function load() {
  loading.value = true
  try {
    rows.value = await listOverlayTemplates()
  } catch (e) {
    $q.notify({ type: 'negative', message: e?.message || t('common.error') })
  } finally { loading.value = false }
}

function openCreate() {
  editMode.value = false
  form.value = _emptyForm()
  conditionEnabled.value = false
  previewSrc.value = null
  previewError.value = null
  showDialog.value = true
}

function openEdit(row) {
  editMode.value = true
  form.value = {
    ...row,
    condition: row.condition ? structuredClone(row.condition) : null,
    elements: row.elements ? structuredClone(row.elements) : [],
  }
  conditionEnabled.value = !!row.condition
  previewSrc.value = null
  previewError.value = null
  showDialog.value = true
}

async function save() {
  const payload = {
    name: form.value.name,
    description: form.value.description || null,
    media_scope: form.value.media_scope,
    target: form.value.target,
    condition: conditionEnabled.value ? form.value.condition || null : null,
    elements: form.value.elements || [],
    z_order: Number(form.value.z_order) || 0,
    enabled: form.value.enabled,
  }
  try {
    if (editMode.value) {
      await updateOverlayTemplate(form.value.guid, payload)
    } else {
      await createOverlayTemplate(payload)
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
    await updateOverlayTemplate(row.guid, { enabled: value })
    row.enabled = value
  } catch (e) {
    $q.notify({ type: 'negative', message: e?.response?.data?.detail || e.message })
  }
}

async function rerender(row) {
  try {
    await rerenderOverlayTemplate(row.guid)
    $q.notify({ type: 'positive', message: t('adminOverlays.rerenderQueued') })
  } catch (e) {
    $q.notify({ type: 'negative', message: e?.response?.data?.detail || e.message })
  }
}

function refreshPreview() {
  previewError.value = null
  if (!previewMediaGuid.value || !/^[0-9a-f-]{36}$/i.test(previewMediaGuid.value)) {
    previewError.value = t('adminOverlays.previewGuidInvalid')
    previewSrc.value = null
    return
  }
  // Bust the browser cache so saves are visible on the next refresh.
  previewSrc.value = `${overlayPreviewUrl(previewMediaGuid.value, form.value.target)}&_=${Date.now()}`
}

function onPreviewError() {
  previewError.value = t('adminOverlays.previewFailed')
  previewSrc.value = null
}

function confirmDelete(row) {
  $q.dialog({
    title: t('adminOverlays.deleteConfirmTitle'),
    message: t('adminOverlays.deleteConfirm', { name: row.name }),
    ok: { label: t('common.delete'), color: 'negative' },
    cancel: true,
    dark: true,
  }).onOk(async () => {
    try {
      await deleteOverlayTemplate(row.guid)
      await load()
    } catch (e) {
      $q.notify({ type: 'negative', message: e?.response?.data?.detail || e.message })
    }
  })
}

onMounted(load)
</script>

<style scoped>
.preview-frame {
  background: rgba(255,255,255,0.04);
  border: 1px dashed rgba(255,255,255,0.2);
  min-height: 320px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 4px;
}
</style>
