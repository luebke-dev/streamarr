<template>
  <q-page class="q-pa-md">
    <div class="text-h4 q-mb-md">{{ $t('adminIndexers.title') }}</div>
    <div class="text-subtitle1 text-grey-7 q-mb-lg">{{ $t('adminIndexers.subtitle') }}</div>

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
              :label="$t('adminIndexers.addIndexer')"
              @click="$router.push('/admin/indexers/create')"
              unelevated
            />
          </div>
        </div>

        <q-table
          flat
          bordered
          dark
          ref="tableRef"
          :rows="filteredRows"
          :columns="columns"
          row-key="guid"
          v-model:pagination="pagination"
          :loading="loading"
          binary-state-sort
          :rows-per-page-options="[10, 25, 50, 100]"
        >
          <template v-slot:body-cell-type="props">
            <q-td :props="props">
              <q-chip :label="props.value" size="sm" color="primary" text-color="white" />
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
                @click="$router.push(`/admin/indexers/${props.row.guid}/edit`)"
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
            {{ editMode ? $t('adminIndexers.editIndexer') : $t('adminIndexers.addIndexer') }}
          </div>
        </q-card-section>

        <q-card-section class="q-pt-none">
          <q-form @submit="saveIndexer" class="q-gutter-md">
            <!-- Label Field (always present) -->
            <q-input
              outlined
              dark
              dense
              v-model="indexerForm.label"
              :label="$t('adminIndexers.fields.label')"
              hint="A descriptive name for this indexer"
              lazy-rules
              :rules="[(val) => (val && val.length > 0) || 'Please enter a label']"
            >
              <template v-slot:prepend>
                <q-icon name="mdi-label" />
              </template>
            </q-input>

            <!-- Indexer Type Selection -->
            <q-select
              outlined
              dark
              dense
              v-model="selectedIndexerType"
              :options="indexerTypeOptions"
              label="Indexer Type *"
              hint="Select the indexer type"
              option-value="domain"
              option-label="name"
              emit-value
              map-options
              :loading="loadingTypes"
              :disable="editMode"
              lazy-rules
              :rules="[(val) => val || 'Please select an indexer type']"
              @update:model-value="onIndexerTypeChange"
            >
              <template v-slot:prepend>
                <q-icon name="mdi-database-search" />
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
            <div v-if="selectedIndexerType && currentConfigSchema">
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
                  v-model="indexerForm.config[fieldName]"
                  :label="getFieldLabel(fieldName)"
                  :hint="fieldSchema.description"
                  :type="fieldSchema.format === 'uri' ? 'url' : 'text'"
                  :rules="getFieldRules(fieldName, fieldSchema)"
                >
                  <template v-slot:prepend>
                    <q-icon :name="getFieldIcon(fieldName)" />
                  </template>
                </q-input>

                <!-- Password fields -->
                <q-input
                  v-else-if="fieldSchema.type === 'string' && fieldSchema.format === 'password'"
                  outlined
                  dark
                  dense
                  v-model="indexerForm.config[fieldName]"
                  :label="getFieldLabel(fieldName)"
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
                  v-model.number="indexerForm.config[fieldName]"
                  :label="getFieldLabel(fieldName)"
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
                  v-model="indexerForm.config[fieldName]"
                  :label="getFieldLabel(fieldName)"
                  :hint="fieldSchema.description"
                  color="primary"
                />
              </div>
            </div>
          </q-form>
        </q-card-section>

        <q-card-actions align="right">
          <q-btn flat :label="$t('common.cancel')" @click="closeAddDialog" />
          <q-btn
            flat
            :label="$t('common.save')"
            color="primary"
            @click="saveIndexer"
            :loading="saving"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Delete Confirmation Dialog -->
    <ConfirmDeleteDialog
      v-model="showDeleteDialog"
      :message="$t('adminIndexers.deleteConfirm')"
      :loading="deleting"
      @confirm="deleteIndexer"
    />
  </q-page>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from 'boot/axios'
import { logger } from 'src/utils/logger'
import ConfirmDeleteDialog from 'src/components/ConfirmDeleteDialog.vue'
const { t } = useI18n()

// State
const loading = ref(false)
const saving = ref(false)
const deleting = ref(false)
const loadingTypes = ref(false)
const rows = ref([])
const filter = ref('')
const showAddDialog = ref(false)
const showDeleteDialog = ref(false)
const editMode = ref(false)
const indexerToDelete = ref(null)

// Indexer types from plugins
const indexerTypeOptions = ref([])
const selectedIndexerType = ref(null)
const currentConfigSchema = ref(null)

// Form
const indexerForm = ref({
  label: '',
  plugin_type: '',
  config: {},
})

// Pagination
const pagination = ref({
  page: 1,
  rowsPerPage: 10,
})

// Table columns
const columns = [
  {
    name: 'label',
    required: true,
    label: t('adminIndexers.fields.label'),
    align: 'left',
    field: 'label',
    sortable: true,
  },
  {
    name: 'type',
    align: 'left',
    label: t('adminIndexers.fields.type'),
    field: 'type',
    sortable: true,
  },
  {
    name: 'host',
    align: 'left',
    label: t('common.host'),
    field: 'host',
    sortable: true,
  },
  {
    name: 'created_at',
    align: 'left',
    label: t('adminIndexers.fields.createdAt'),
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
]

// Computed
const filteredRows = computed(() => {
  if (!filter.value) return rows.value
  const searchTerm = filter.value.toLowerCase()
  return rows.value.filter(
    (row) =>
      row.label?.toLowerCase().includes(searchTerm) ||
      row.type?.toLowerCase().includes(searchTerm) ||
      row.host?.toLowerCase().includes(searchTerm),
  )
})

// Methods
async function loadIndexers() {
  loading.value = true
  try {
    const response = await api.get('/api/indexers')
    rows.value = response.data
  } catch (error) {
    logger.error('Error loading indexers:', error)
  } finally {
    loading.value = false
  }
}

async function loadIndexerTypes() {
  loadingTypes.value = true
  try {
    const response = await api.get('/api/indexers/types')
    indexerTypeOptions.value = response.data
  } catch (error) {
    logger.error('Error loading indexer types:', error)
  } finally {
    loadingTypes.value = false
  }
}

async function onIndexerTypeChange() {
  if (!selectedIndexerType.value) {
    currentConfigSchema.value = null
    return
  }

  try {
    const response = await api.get(`/api/plugins/${selectedIndexerType.value}/schema`)
    currentConfigSchema.value = response.data

    // Initialize config with default values
    indexerForm.value.config = {}
    if (currentConfigSchema.value?.properties) {
      Object.entries(currentConfigSchema.value.properties).forEach(([key, schema]) => {
        if (schema.default !== undefined) {
          indexerForm.value.config[key] = schema.default
        }
      })
    }
  } catch (error) {
    logger.error('Error loading indexer schema:', error)
  }
}

function getFieldLabel(fieldName) {
  // Convert snake_case to Title Case
  return fieldName
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ')
}

function getFieldIcon(fieldName) {
  const lowerName = fieldName.toLowerCase()
  if (lowerName.includes('url') || lowerName.includes('host') || lowerName.includes('base_url'))
    return 'mdi-link'
  if (lowerName.includes('api') || lowerName.includes('key')) return 'mdi-key'
  if (lowerName.includes('user') || lowerName.includes('username')) return 'mdi-account'
  if (lowerName.includes('pass')) return 'mdi-lock'
  if (lowerName.includes('port')) return 'mdi-ethernet'
  if (lowerName.includes('path')) return 'mdi-folder'
  return 'mdi-cog'
}

function getFieldRules(fieldName, fieldSchema) {
  const rules = []

  // Check if field is required
  if (currentConfigSchema.value?.required?.includes(fieldName)) {
    rules.push((val) => !!val || `${getFieldLabel(fieldName)} is required`)
  }

  // Add type-specific validation
  if (fieldSchema.format === 'uri') {
    rules.push((val) => {
      if (!val) return true
      try {
        new URL(val)
        return true
      } catch {
        return 'Please enter a valid URL'
      }
    })
  }

  if (fieldSchema.type === 'integer' || fieldSchema.type === 'number') {
    if (fieldSchema.minimum !== undefined) {
      rules.push((val) => val >= fieldSchema.minimum || `Must be at least ${fieldSchema.minimum}`)
    }
    if (fieldSchema.maximum !== undefined) {
      rules.push((val) => val <= fieldSchema.maximum || `Must be at most ${fieldSchema.maximum}`)
    }
  }

  return rules
}

function closeAddDialog() {
  showAddDialog.value = false
  indexerForm.value = {
    label: '',
    plugin_type: '',
    config: {},
    enabled: true,
  }
  selectedIndexerType.value = null
  currentConfigSchema.value = null
}

async function validateIndexerConfig() {
  if (!selectedIndexerType.value || !indexerForm.value.config) {
    return { valid: false, errors: ['No configuration to validate'] }
  }

  try {
    const response = await api.post('/api/indexers/validate', {
      plugin_type: selectedIndexerType.value,
      config: indexerForm.value.config,
    })
    return response.data
  } catch (error) {
    logger.error('Error validating indexer config:', error)
    return {
      valid: false,
      errors: [error.response?.data?.detail || error.message || 'Validation failed'],
    }
  }
}

async function saveIndexer() {
  saving.value = true
  try {
    // Validate configuration before saving
    const validation = await validateIndexerConfig()
    if (!validation.valid) {
      saving.value = false
      return
    }

    const payload = {
      label: indexerForm.value.label,
      plugin_type: selectedIndexerType.value,
      config: indexerForm.value.config,
      enabled: indexerForm.value.enabled,
    }

    if (editMode.value) {
      await api.put(`/api/indexers/${indexerForm.value.guid}`, payload)
    } else {
      await api.post('/api/indexers', payload)
    }

    closeAddDialog()
    await loadIndexers()
  } catch (error) {
    logger.error('Error saving indexer:', error)
  } finally {
    saving.value = false
  }
}

function confirmDelete(indexer) {
  indexerToDelete.value = indexer
  showDeleteDialog.value = true
}

async function deleteIndexer() {
  deleting.value = true
  try {
    await api.delete(`/api/indexers/${indexerToDelete.value.guid}`)
    showDeleteDialog.value = false
    indexerToDelete.value = null
    await loadIndexers()
  } catch (error) {
    logger.error('Error deleting indexer:', error)
  } finally {
    deleting.value = false
  }
}

// Lifecycle
onMounted(async () => {
  await loadIndexers()
  await loadIndexerTypes()
})
</script>
