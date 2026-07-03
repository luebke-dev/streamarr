<template>
  <q-page class="q-pa-md">
    <div class="text-h4 q-mb-md">{{ $t('adminDownloaders.title') }}</div>
    <div class="text-subtitle1 text-grey-7 q-mb-lg">{{ $t('adminDownloaders.subtitle') }}</div>

    <q-card flat bordered>
      <q-card-section>
        <div class="row q-col-gutter-md q-mb-md">
          <div class="col-12 col-md-6">
            <q-input v-model="filter" :label="$t('common.search')" outlined dark dense clearable>
              <template v-slot:prepend>
                <q-icon name="mdi-magnify" />
              </template>
            </q-input>
          </div>

          <div class="col-12 col-md-6 text-right">
            <q-btn
              color="primary"
              icon="mdi-plus"
              :label="$t('adminDownloaders.addDownloader')"
              @click="openAddDialog"
              unelevated
            />
          </div>
        </div>

        <q-table
          flat
          bordered
          dark
          ref="tableRef"
          :rows="rows"
          :columns="columns"
          row-key="guid"
          v-model:pagination="pagination"
          :loading="loading"
          binary-state-sort
          :rows-per-page-options="[10, 25, 50, 100]"
          @request="onRequest"
        >
          <template v-slot:body-cell-type="props">
            <q-td :props="props">
              <q-chip :label="props.value" size="sm" color="primary" text-color="white" />
            </q-td>
          </template>

          <template v-slot:body-cell-ssl="props">
            <q-td :props="props">
              <q-icon
                :name="props.value ? 'mdi-check-circle' : 'mdi-cancel'"
                :color="props.value ? 'positive' : 'negative'"
                size="sm"
              />
            </q-td>
          </template>

          <template v-slot:body-cell-verify_ssl="props">
            <q-td :props="props">
              <q-icon
                :name="props.value ? 'mdi-check-circle' : 'mdi-cancel'"
                :color="props.value ? 'positive' : 'negative'"
                size="sm"
              />
            </q-td>
          </template>

          <template v-slot:body-cell-actions="props">
            <q-td :props="props">
              <q-btn
                flat
                dense
                round
                icon="mdi-pencil"
                color="primary"
                size="sm"
                @click="editDownloader(props.row)"
              >
                <q-tooltip>{{ $t('common.edit') }}</q-tooltip>
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

    <!-- Add/Edit Dialog -->
    <q-dialog v-model="showAddDialog" persistent>
      <q-card dark style="min-width: 500px; max-width: 600px">
        <q-card-section>
          <div class="text-h6">
            {{
              editMode
                ? $t('adminDownloaders.editDownloader')
                : $t('adminDownloaders.addDownloader')
            }}
          </div>
        </q-card-section>

        <q-card-section class="q-pt-none">
          <q-form @submit="saveDownloader" class="q-gutter-md">
            <!-- Label Field (always present) -->
            <q-input
              outlined
              dark
              dense
              v-model="downloaderForm.label"
              :label="$t('adminDownloaders.fields.label')"
              :hint="$t('adminDownloaders.fields.labelHint')"
              lazy-rules
              :rules="[(val) => (val && val.length > 0) || 'Please enter a label']"
            >
              <template v-slot:prepend>
                <q-icon name="mdi-label" />
              </template>
            </q-input>

            <!-- Downloader Type Selection -->
            <q-select
              outlined
              dark
              dense
              v-model="selectedDownloaderType"
              :options="downloaderTypeOptions"
              :label="$t('adminDownloaders.fields.downloaderType')"
              :hint="$t('adminDownloaders.fields.downloaderTypeHint')"
              option-value="domain"
              option-label="name"
              emit-value
              map-options
              :loading="loadingTypes"
              :disable="editMode"
              lazy-rules
              :rules="[(val) => val || 'Please select a downloader type']"
              @update:model-value="onDownloaderTypeChange"
            >
              <template v-slot:prepend>
                <q-icon name="mdi-download" />
              </template>
              <template v-slot:option="scope">
                <q-item v-bind="scope.itemProps">
                  <q-item-section>
                    <q-item-label>{{ scope.opt.name }}</q-item-label>
                    <q-item-label caption>{{ scope.opt.description }}</q-item-label>
                  </q-item-section>
                </q-item>
              </template>
            </q-select>

            <!-- Dynamic Configuration Fields based on selected type's schema -->
            <div v-if="selectedDownloaderType && currentConfigSchema">
              <div
                v-for="(fieldSchema, fieldName) in currentConfigSchema.properties"
                :key="fieldName"
              >
                <!-- String fields (including URIs) -->
                <q-input
                  v-if="fieldSchema.type === 'string' && fieldSchema.format !== 'password'"
                  outlined
                  dark
                  dense
                  v-model="downloaderForm.config[fieldName]"
                  :label="getFieldLabel(fieldName, fieldSchema)"
                  :hint="fieldSchema.description"
                  :type="fieldSchema.format === 'uri' ? 'url' : 'text'"
                  :rules="getFieldRules(fieldName, fieldSchema)"
                >
                  <template v-slot:prepend>
                    <q-icon :name="getFieldIcon(fieldName, fieldSchema)" />
                  </template>
                </q-input>

                <!-- Password fields -->
                <q-input
                  v-else-if="fieldSchema.type === 'string' && fieldSchema.format === 'password'"
                  outlined
                  dark
                  dense
                  v-model="downloaderForm.config[fieldName]"
                  :label="getFieldLabel(fieldName, fieldSchema)"
                  :hint="fieldSchema.description"
                  type="password"
                  :rules="getFieldRules(fieldName, fieldSchema)"
                >
                  <template v-slot:prepend>
                    <q-icon name="mdi-key" />
                  </template>
                </q-input>

                <!-- Number fields -->
                <q-input
                  v-else-if="fieldSchema.type === 'number' || fieldSchema.type === 'integer'"
                  outlined
                  dark
                  dense
                  v-model.number="downloaderForm.config[fieldName]"
                  :label="getFieldLabel(fieldName, fieldSchema)"
                  :hint="fieldSchema.description"
                  type="number"
                  :rules="getFieldRules(fieldName, fieldSchema)"
                >
                  <template v-slot:prepend>
                    <q-icon name="mdi-numeric" />
                  </template>
                </q-input>

                <!-- Boolean fields -->
                <q-toggle
                  v-else-if="fieldSchema.type === 'boolean'"
                  v-model="downloaderForm.config[fieldName]"
                  :label="getFieldLabel(fieldName, fieldSchema)"
                />
              </div>
            </div>

            <!-- Legacy SSL fields (if not in schema) -->
            <div v-if="selectedDownloaderType && !hasSchemaField('ssl')">
              <q-toggle
                v-model="downloaderForm.ssl"
                :label="$t('adminDownloaders.fields.useSSL')"
              />
            </div>

            <div v-if="selectedDownloaderType && !hasSchemaField('verify_ssl')">
              <q-toggle
                v-model="downloaderForm.verify_ssl"
                :label="$t('adminDownloaders.fields.verifySSL')"
              />
            </div>
          </q-form>
        </q-card-section>

        <q-card-actions align="right" class="text-primary">
          <q-btn flat :label="$t('adminDownloaders.fields.cancel')" @click="cancelEdit" />
          <q-btn
            flat
            :label="$t('adminDownloaders.fields.save')"
            @click="saveDownloader"
            :loading="saving"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Delete Confirmation Dialog -->
    <ConfirmDeleteDialog
      v-model="showDeleteDialog"
      :message="$t('adminDownloaders.confirmDelete')"
      :loading="deleting"
      @confirm="deleteDownloader"
    />
  </q-page>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { api } from 'boot/axios'
import { useI18n } from 'vue-i18n'
import { useQuasar } from 'quasar'
import { logger } from 'src/utils/logger'
import { useAdminCrudList } from 'src/composables/useAdminCrudList'
import { useCachedClientPagination } from 'src/composables/useCachedClientPagination'
import ConfirmDeleteDialog from 'src/components/ConfirmDeleteDialog.vue'
const { t } = useI18n()
const $q = useQuasar()

const { paginate: paginateDownloaders, invalidate: invalidateDownloadersCache } =
  useCachedClientPagination({
    loadAll: async () => {
      const response = await api.get('/api/downloaders')
      return response.data
    },
    matchFilter: (row, needle) =>
      (row.label && row.label.toLowerCase().includes(needle)) ||
      (row.host && row.host.toLowerCase().includes(needle)) ||
      (row.type && row.type.toLowerCase().includes(needle)),
  })

const {
  tableRef,
  rows,
  filter,
  loading,
  pagination,
  onRequest,
  refresh,
  showDeleteDialog,
  deleting,
  confirmDelete,
  performDelete: deleteDownloader,
} = useAdminCrudList({
  fetchPage: paginateDownloaders,
  deleteItem: async (downloader) => {
    await api.delete(`/api/downloaders/${downloader.guid}`)
    invalidateDownloadersCache()
  },
  errorContext: 'downloaders',
})

const columns = computed(() => [
  {
    name: 'label',
    required: true,
    label: t('adminDownloaders.columns.label'),
    align: 'left',
    field: 'label',
    format: (val) => `${val}`,
    sortable: true,
  },
  {
    name: 'host',
    align: 'left',
    label: t('adminDownloaders.columns.host'),
    field: 'host',
    sortable: true,
  },
  {
    name: 'type',
    align: 'left',
    label: t('adminDownloaders.columns.type'),
    field: 'type',
    sortable: true,
  },
  {
    name: 'ssl',
    align: 'center',
    label: t('adminDownloaders.columns.ssl'),
    field: 'ssl',
    sortable: true,
  },
  {
    name: 'verify_ssl',
    align: 'center',
    label: t('adminDownloaders.columns.verifySSL'),
    field: 'verify_ssl',
    sortable: true,
  },
  {
    name: 'created_at',
    align: 'left',
    label: t('adminDownloaders.columns.created'),
    field: 'created_at',
    format: (val) => new Date(val).toLocaleDateString(),
    sortable: true,
  },
  {
    name: 'actions',
    align: 'center',
    label: t('common.actions'),
    field: 'actions',
  },
])

const saving = ref(false)
const loadingTypes = ref(false)
const showAddDialog = ref(false)
const editMode = ref(false)

const downloaderTypes = ref([])
const selectedDownloaderType = ref(null)

const downloaderForm = ref({
  label: '',
  config: {},
  ssl: false,
  verify_ssl: true,
})

const downloaderTypeOptions = computed(() => {
  return downloaderTypes.value.map((type) => ({
    domain: type.domain,
    name: type.name,
    description: type.description,
    config_schema: type.config_schema,
  }))
})

const currentConfigSchema = computed(() => {
  if (!selectedDownloaderType.value) return null
  const type = downloaderTypes.value.find((t) => t.domain === selectedDownloaderType.value)
  return type?.config_schema || null
})

// Load available downloader types
async function loadDownloaderTypes() {
  loadingTypes.value = true
  try {
    const response = await api.get('/api/downloaders/types')
    downloaderTypes.value = response.data
  } catch (error) {
    logger.error('Failed to load downloader types:', error)
    $q.notify({
      type: 'negative',
      message: error?.response?.data?.detail || t('adminDownloaders.errorLoadTypes'),
    })
  } finally {
    loadingTypes.value = false
  }
}

// Helper functions for dynamic field rendering
function getFieldLabel(fieldName) {
  // Convert snake_case to Title Case
  const label = fieldName
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ')

  const isRequired = currentConfigSchema.value?.required?.includes(fieldName)
  return isRequired ? `${label} *` : label
}

function getFieldIcon(fieldName, fieldSchema) {
  if (fieldSchema.format === 'uri') return 'mdi-link'
  if (fieldName.includes('url')) return 'mdi-link'
  if (fieldName.includes('host')) return 'mdi-server'
  if (fieldName.includes('port')) return 'mdi-ethernet'
  if (fieldName.includes('path')) return 'mdi-folder'
  if (fieldName.includes('key') || fieldName.includes('password')) return 'mdi-key'
  return 'mdi-form-textbox'
}

function getFieldRules(fieldName, fieldSchema) {
  const rules = []
  const isRequired = currentConfigSchema.value?.required?.includes(fieldName)

  if (isRequired) {
    rules.push(
      (val) =>
        (val !== null && val !== undefined && val !== '') ||
        `${getFieldLabel(fieldName, fieldSchema)} is required`,
    )
  }

  if (fieldSchema.minLength) {
    rules.push(
      (val) =>
        !val || val.length >= fieldSchema.minLength || `Minimum length is ${fieldSchema.minLength}`,
    )
  }

  if (fieldSchema.maxLength) {
    rules.push(
      (val) =>
        !val || val.length <= fieldSchema.maxLength || `Maximum length is ${fieldSchema.maxLength}`,
    )
  }

  if (fieldSchema.minimum !== undefined) {
    rules.push(
      (val) =>
        val === '' || val >= fieldSchema.minimum || `Minimum value is ${fieldSchema.minimum}`,
    )
  }

  if (fieldSchema.maximum !== undefined) {
    rules.push(
      (val) =>
        val === '' || val <= fieldSchema.maximum || `Maximum value is ${fieldSchema.maximum}`,
    )
  }

  return rules
}

function hasSchemaField(fieldName) {
  return currentConfigSchema.value?.properties?.[fieldName] !== undefined
}

function onDownloaderTypeChange() {
  // Reset config when type changes
  downloaderForm.value.config = {}

  // Initialize config with default values
  if (currentConfigSchema.value?.properties) {
    Object.entries(currentConfigSchema.value.properties).forEach(([key, schema]) => {
      if (schema.default !== undefined) {
        downloaderForm.value.config[key] = schema.default
      } else if (schema.type === 'boolean') {
        downloaderForm.value.config[key] = false
      } else if (schema.type === 'number' || schema.type === 'integer') {
        downloaderForm.value.config[key] = schema.minimum || 0
      } else {
        downloaderForm.value.config[key] = ''
      }
    })
  }
}

function openAddDialog() {
  editMode.value = false
  selectedDownloaderType.value = null
  downloaderForm.value = {
    label: '',
    config: {},
    ssl: false,
    verify_ssl: true,
  }
  showAddDialog.value = true
}

function editDownloader(downloader) {
  editMode.value = true
  selectedDownloaderType.value = downloader.type

  // Parse config if it's a string
  let config = {}
  if (typeof downloader.config === 'string') {
    try {
      config = JSON.parse(downloader.config)
    } catch (e) {
      logger.error('Failed to parse config:', e)
    }
  } else if (downloader.config) {
    config = { ...downloader.config }
  }

  downloaderForm.value = {
    guid: downloader.guid,
    label: downloader.label,
    config: config,
    ssl: downloader.ssl || false,
    verify_ssl: downloader.verify_ssl !== undefined ? downloader.verify_ssl : true,
  }

  showAddDialog.value = true
}

function cancelEdit() {
  showAddDialog.value = false
  editMode.value = false
  selectedDownloaderType.value = null
  downloaderForm.value = {
    label: '',
    config: {},
    ssl: false,
    verify_ssl: true,
  }
}

async function saveDownloader() {
  saving.value = true
  try {
    const payload = {
      label: downloaderForm.value.label,
      type: selectedDownloaderType.value,
      config: downloaderForm.value.config,
      ssl: downloaderForm.value.ssl,
      verify_ssl: downloaderForm.value.verify_ssl,
    }

    // For backward compatibility, also set host and api_key from config
    if (downloaderForm.value.config.base_url) {
      payload.host = downloaderForm.value.config.base_url
    }
    if (downloaderForm.value.config.api_key) {
      payload.api_key = downloaderForm.value.config.api_key
    }

    if (editMode.value) {
      await api.put(`/api/downloaders/${downloaderForm.value.guid}`, payload)
    } else {
      await api.post('/api/downloaders', payload)
    }

    invalidateDownloadersCache()
    refresh()
    cancelEdit()
  } catch (error) {
    logger.error('Error saving downloader:', error)
    $q.notify({
      type: 'negative',
      message: error?.response?.data?.detail || t('adminDownloaders.errorSave'),
    })
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  loadDownloaderTypes()
  refresh()
})
</script>
