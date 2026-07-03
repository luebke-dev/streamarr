<template>
  <q-page class="q-pa-md">
    <div class="text-h4 q-mb-md">{{ $t('adminVouchers.title') }}</div>
    <div class="text-subtitle1 text-grey-7 q-mb-lg">{{ $t('adminVouchers.subtitle') }}</div>

    <q-card flat bordered>
      <q-card-section>
        <div class="row q-col-gutter-md q-mb-md items-center">
          <div class="col-12 col-md-6">
            <q-input
              v-model="search"
              :label="$t('common.search')"
              outlined
              dark
              dense
              clearable
            >
              <template v-slot:prepend>
                <q-icon name="mdi-magnify" />
              </template>
            </q-input>
          </div>
          <div class="col-12 col-md-6 text-right">
            <q-btn
              color="secondary"
              icon="mdi-download"
              :label="$t('adminVouchers.exportCsv')"
              class="q-mr-sm"
              :loading="exporting"
              @click="exportCsv"
            />
            <q-btn
              color="primary"
              icon="mdi-tray-plus"
              :label="$t('adminVouchers.batchCreate')"
              class="q-mr-sm"
              @click="openBatchDialog"
            />
            <q-btn
              color="primary"
              icon="mdi-plus"
              :label="$t('adminVouchers.createVoucher')"
              @click="openCreateDialog"
            />
          </div>
        </div>

        <q-table
          flat
          bordered
          dark
          :rows="filteredVouchers"
          :columns="columns"
          :loading="loading"
          row-key="guid"
          binary-state-sort
          :rows-per-page-options="[10, 25, 50, 100]"
          :no-data-label="$t('adminVouchers.noVouchers')"
        >
          <template v-slot:body-cell-code="props">
            <q-td :props="props">
              <code class="text-weight-medium">{{ props.row.code }}</code>
              <div v-if="props.row.note" class="text-caption text-grey-7">{{ props.row.note }}</div>
            </q-td>
          </template>

          <template v-slot:body-cell-package="props">
            <q-td :props="props">
              <q-chip dense size="sm" color="blue" text-color="white">
                <q-icon name="mdi-package-variant-closed" size="xs" class="q-mr-xs" />
                {{ props.row.package_name || props.row.package_id }}
              </q-chip>
            </q-td>
          </template>

          <template v-slot:body-cell-uses="props">
            <q-td :props="props">
              {{ props.row.current_uses }} / {{ props.row.max_uses }}
            </q-td>
          </template>

          <template v-slot:body-cell-expires="props">
            <q-td :props="props">
              {{ props.row.expires_at ? formatDate(props.row.expires_at) : '—' }}
            </q-td>
          </template>

          <template v-slot:body-cell-is_active="props">
            <q-td :props="props">
              <q-toggle
                :model-value="props.row.is_active"
                color="positive"
                @update:model-value="(val) => toggleActive(props.row, val)"
              />
            </q-td>
          </template>

          <template v-slot:body-cell-actions="props">
            <q-td :props="props">
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

    <!-- Create single voucher dialog -->
    <q-dialog v-model="showCreateDialog" persistent>
      <q-card style="min-width: 480px" dark>
        <q-card-section>
          <div class="text-h6">{{ $t('adminVouchers.createVoucher') }}</div>
        </q-card-section>
        <q-card-section class="q-pt-none q-gutter-md">
          <q-select
            v-model="form.package_id"
            :options="packageOptions"
            :label="$t('adminVouchers.package')"
            outlined
            dark
            dense
            emit-value
            map-options
          />
          <q-input
            v-model.number="form.duration_days"
            type="number"
            :label="$t('adminVouchers.duration')"
            :hint="$t('adminVouchers.durationHint')"
            outlined
            dark
            dense
          />
          <q-input
            v-model.number="form.max_uses"
            type="number"
            :label="$t('adminVouchers.uses')"
            :hint="$t('adminVouchers.usesHint')"
            outlined
            dark
            dense
          />
          <q-input
            v-model="form.expires_at"
            type="date"
            :label="$t('adminVouchers.expiresAt')"
            :hint="$t('adminVouchers.expiresAtHint')"
            outlined
            dark
            dense
          />
          <q-input
            v-model="form.code"
            :label="$t('adminVouchers.customCode')"
            :hint="$t('adminVouchers.customCodeHint')"
            outlined
            dark
            dense
          />
          <q-input
            v-model="form.note"
            :label="$t('adminVouchers.note')"
            :hint="$t('adminVouchers.noteHint')"
            outlined
            dark
            dense
            type="textarea"
            autogrow
          />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat :label="$t('common.cancel')" @click="showCreateDialog = false" />
          <q-btn
            color="primary"
            :label="$t('common.save')"
            :loading="saving"
            @click="createVoucher"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Batch dialog -->
    <q-dialog v-model="showBatchDialog" persistent>
      <q-card style="min-width: 480px" dark>
        <q-card-section>
          <div class="text-h6">{{ $t('adminVouchers.batchCreate') }}</div>
        </q-card-section>
        <q-card-section class="q-pt-none q-gutter-md">
          <q-select
            v-model="batchForm.package_id"
            :options="packageOptions"
            :label="$t('adminVouchers.package')"
            outlined
            dark
            dense
            emit-value
            map-options
          />
          <q-input
            v-model.number="batchForm.count"
            type="number"
            :label="$t('adminVouchers.count')"
            :hint="$t('adminVouchers.countHint')"
            outlined
            dark
            dense
          />
          <q-input
            v-model.number="batchForm.duration_days"
            type="number"
            :label="$t('adminVouchers.duration')"
            :hint="$t('adminVouchers.durationHint')"
            outlined
            dark
            dense
          />
          <q-input
            v-model.number="batchForm.max_uses"
            type="number"
            :label="$t('adminVouchers.uses')"
            :hint="$t('adminVouchers.usesHint')"
            outlined
            dark
            dense
          />
          <q-input
            v-model="batchForm.expires_at"
            type="date"
            :label="$t('adminVouchers.expiresAt')"
            :hint="$t('adminVouchers.expiresAtHint')"
            outlined
            dark
            dense
          />
          <q-input
            v-model="batchForm.prefix"
            :label="$t('adminVouchers.prefix')"
            :hint="$t('adminVouchers.prefixHint')"
            outlined
            dark
            dense
          />
          <q-input
            v-model="batchForm.note"
            :label="$t('adminVouchers.note')"
            :hint="$t('adminVouchers.noteHint')"
            outlined
            dark
            dense
            type="textarea"
            autogrow
          />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat :label="$t('common.cancel')" @click="showBatchDialog = false" />
          <q-btn
            color="primary"
            :label="$t('common.save')"
            :loading="saving"
            @click="batchCreate"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <ConfirmDeleteDialog
      v-model="showDeleteDialog"
      :message="confirmDeleteMessage"
      :loading="deleting"
      @confirm="deleteVoucher"
    />
  </q-page>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuasar } from 'quasar'
import { api } from 'boot/axios'
import { logger } from 'src/utils/logger'
import ConfirmDeleteDialog from 'src/components/ConfirmDeleteDialog.vue'

const { t } = useI18n()
const $q = useQuasar()

const vouchers = ref([])
const packages = ref([])
const loading = ref(false)
const saving = ref(false)
const exporting = ref(false)
const deleting = ref(false)
const search = ref('')
const showCreateDialog = ref(false)
const showBatchDialog = ref(false)
const showDeleteDialog = ref(false)
const selectedVoucher = ref(null)

const form = ref(emptyForm())
const batchForm = ref(emptyBatchForm())

function emptyForm() {
  return {
    package_id: null,
    duration_days: 30,
    max_uses: 1,
    expires_at: '',
    code: '',
    note: '',
  }
}

function emptyBatchForm() {
  return {
    package_id: null,
    count: 10,
    duration_days: 30,
    max_uses: 1,
    expires_at: '',
    prefix: '',
    note: '',
  }
}

const columns = computed(() => [
  { name: 'code', required: true, label: t('adminVouchers.code'), align: 'left', field: 'code', sortable: true },
  { name: 'package', label: t('adminVouchers.package'), align: 'left', field: 'package_id' },
  { name: 'duration', label: t('adminVouchers.duration'), align: 'left', field: 'duration_days', sortable: true },
  { name: 'uses', label: t('adminVouchers.uses'), align: 'left', field: 'current_uses' },
  { name: 'expires', label: t('adminVouchers.expiresAt'), align: 'left', field: 'expires_at', sortable: true },
  { name: 'is_active', label: t('adminVouchers.status'), align: 'center', field: 'is_active', sortable: true },
  { name: 'actions', label: t('common.actions'), align: 'center', field: 'actions' },
])

const packageOptions = computed(() =>
  packages.value.map((p) => ({ label: p.name, value: p.guid })),
)

const filteredVouchers = computed(() => {
  if (!search.value) return vouchers.value
  const s = search.value.toLowerCase()
  return vouchers.value.filter(
    (v) =>
      v.code.toLowerCase().includes(s) ||
      (v.note && v.note.toLowerCase().includes(s)) ||
      (v.package_name && v.package_name.toLowerCase().includes(s)),
  )
})

const confirmDeleteMessage = computed(() =>
  t('adminVouchers.confirmDelete', { code: selectedVoucher.value?.code || '' }),
)

function formatDate(iso) {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleDateString()
  } catch {
    return iso
  }
}

async function loadData() {
  loading.value = true
  try {
    const [vRes, pRes] = await Promise.all([
      api.get('/api/vouchers'),
      api.get('/api/subscriptions/packages', { params: { active_only: false } }),
    ])
    vouchers.value = vRes.data || []
    packages.value = pRes.data || []
  } catch (err) {
    logger.error('Failed to load vouchers:', err)
    $q.notify({ type: 'negative', message: t('adminVouchers.loadError') })
  } finally {
    loading.value = false
  }
}

function openCreateDialog() {
  form.value = emptyForm()
  if (packages.value.length > 0) form.value.package_id = packages.value[0].guid
  showCreateDialog.value = true
}

function openBatchDialog() {
  batchForm.value = emptyBatchForm()
  if (packages.value.length > 0) batchForm.value.package_id = packages.value[0].guid
  showBatchDialog.value = true
}

function buildPayload(src) {
  const payload = { ...src }
  if (!payload.expires_at) delete payload.expires_at
  else payload.expires_at = new Date(payload.expires_at).toISOString()
  if (!payload.code) delete payload.code
  if (!payload.note) delete payload.note
  if (!payload.prefix) delete payload.prefix
  return payload
}

async function createVoucher() {
  saving.value = true
  try {
    await api.post('/api/vouchers', buildPayload(form.value))
    showCreateDialog.value = false
    await loadData()
    $q.notify({ type: 'positive', message: t('adminVouchers.createSuccess') })
  } catch (err) {
    logger.error('Failed to create voucher:', err)
    $q.notify({ type: 'negative', message: t('adminVouchers.saveError') })
  } finally {
    saving.value = false
  }
}

async function batchCreate() {
  saving.value = true
  try {
    const res = await api.post('/api/vouchers/batch', buildPayload(batchForm.value))
    showBatchDialog.value = false
    await loadData()
    const count = Array.isArray(res.data) ? res.data.length : batchForm.value.count
    $q.notify({ type: 'positive', message: t('adminVouchers.batchSuccess', { count }) })
  } catch (err) {
    logger.error('Failed to batch create vouchers:', err)
    $q.notify({ type: 'negative', message: t('adminVouchers.saveError') })
  } finally {
    saving.value = false
  }
}

async function toggleActive(voucher, value) {
  try {
    await api.patch(`/api/vouchers/${voucher.guid}`, { is_active: value })
    voucher.is_active = value
    $q.notify({ type: 'positive', message: t('adminVouchers.toggleSuccess') })
  } catch (err) {
    logger.error('Failed to toggle voucher:', err)
    $q.notify({ type: 'negative', message: t('adminVouchers.toggleError') })
  }
}

function confirmDelete(voucher) {
  selectedVoucher.value = voucher
  showDeleteDialog.value = true
}

async function deleteVoucher() {
  if (!selectedVoucher.value) return
  deleting.value = true
  try {
    await api.delete(`/api/vouchers/${selectedVoucher.value.guid}`)
    showDeleteDialog.value = false
    selectedVoucher.value = null
    await loadData()
    $q.notify({ type: 'positive', message: t('adminVouchers.deleteSuccess') })
  } catch (err) {
    logger.error('Failed to delete voucher:', err)
    $q.notify({ type: 'negative', message: t('adminVouchers.deleteError') })
  } finally {
    deleting.value = false
  }
}

async function exportCsv() {
  exporting.value = true
  try {
    const res = await api.get('/api/vouchers/export.csv', { responseType: 'blob' })
    const url = window.URL.createObjectURL(new Blob([res.data], { type: 'text/csv' }))
    const link = document.createElement('a')
    link.href = url
    link.setAttribute('download', `vouchers-${new Date().toISOString().slice(0, 10)}.csv`)
    document.body.appendChild(link)
    link.click()
    link.remove()
    window.URL.revokeObjectURL(url)
  } catch (err) {
    logger.error('Failed to export vouchers:', err)
    $q.notify({ type: 'negative', message: t('adminVouchers.exportError') })
  } finally {
    exporting.value = false
  }
}

onMounted(loadData)
</script>
