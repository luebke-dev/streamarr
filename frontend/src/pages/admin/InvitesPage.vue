<template>
  <q-page class="q-pa-md">
    <div class="row items-center justify-between q-mb-md">
      <div class="text-h4">{{ $t('adminInvites.title') }}</div>
      <div class="row q-gutter-sm">
        <q-btn
          color="secondary"
          icon="mdi-broom"
          :label="$t('adminInvites.cleanupExpired')"
          no-caps
          @click="cleanupExpired"
        />
        <q-btn
          color="primary"
          icon="mdi-plus"
          :label="$t('adminInvites.createInvite')"
          no-caps
          @click="showAddDialog = true"
        />
      </div>
    </div>

    <q-card flat bordered>
      <q-card-section>
        <div class="row q-col-gutter-md q-mb-md">
          <div class="col-12 col-md-6">
            <q-input
              v-model="filter"
              :label="$t('adminInvites.search')"
              outlined
              dark
              dense
              clearable
              debounce="300"
            >
              <template v-slot:prepend><q-icon name="mdi-magnify" /></template>
            </q-input>
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
          :filter="filter"
          binary-state-sort
          @request="onRequest"
        >
          <template v-slot:body-cell-actions="props">
            <q-td :props="props">
              <q-btn
                size="sm"
                color="primary"
                round
                dense
                icon="mdi-pencil"
                @click="editInvite(props.row)"
                class="q-mr-xs"
              />
              <q-btn
                size="sm"
                color="negative"
                round
                dense
                icon="mdi-delete"
                @click="confirmDelete(props.row)"
              />
              <q-btn
                size="sm"
                color="info"
                round
                dense
                icon="mdi-content-copy"
                @click="copyInviteLink(props.row)"
                class="q-ml-xs"
              />
            </q-td>
          </template>

          <template v-slot:body-cell-is_active="props">
            <q-td :props="props">
              <q-icon
                :name="props.value ? 'mdi-check-circle' : 'mdi-cancel'"
                :color="props.value ? 'positive' : 'negative'"
              />
            </q-td>
          </template>

          <template v-slot:body-cell-is_used="props">
            <q-td :props="props">
              <q-icon
                :name="props.value ? 'mdi-check-circle' : 'mdi-cancel'"
                :color="props.value ? 'positive' : 'grey'"
              />
            </q-td>
          </template>

          <template v-slot:body-cell-created_by_name="props">
            <q-td :props="props">
              <router-link
                v-if="props.row.created_by"
                :to="`/admin/users/${props.row.created_by.guid}`"
                class="text-primary cursor-pointer"
                style="text-decoration: none"
              >
                {{ props.row.created_by.first_name }} {{ props.row.created_by.last_name }}
              </router-link>
              <span v-else class="text-grey">{{ $t('adminInvites.system') }}</span>
            </q-td>
          </template>

          <template v-slot:body-cell-used_by_name="props">
            <q-td :props="props">
              <router-link
                v-if="props.row.used_by"
                :to="`/admin/users/${props.row.used_by.guid}`"
                class="text-primary cursor-pointer"
                style="text-decoration: none"
              >
                {{ props.row.used_by.first_name }} {{ props.row.used_by.last_name }}
              </router-link>
              <span v-else class="text-grey">-</span>
            </q-td>
          </template>

          <template v-slot:body-cell-expires_at="props">
            <q-td :props="props">
              <span :class="{ 'text-negative': isExpired(props.value) }">
                {{ formatDate(props.value) }}
              </span>
            </q-td>
          </template>

          <template v-slot:body-cell-usage="props">
            <q-td :props="props">
              {{ props.row.current_uses || 0 }} / {{ props.row.max_uses || '∞' }}
            </q-td>
          </template>
        </q-table>
      </q-card-section>
    </q-card>

    <!-- Invite Add/Edit Dialog -->
    <q-dialog v-model="showAddDialog" persistent>
      <q-card dark style="min-width: 400px">
        <q-card-section>
          <div class="text-h6">
            {{ editMode ? $t('adminInvites.editInvite') : $t('adminInvites.createNewInvite') }}
          </div>
        </q-card-section>

        <q-card-section class="q-pt-none">
          <q-form @submit="saveInvite" class="q-gutter-md">
            <q-input
              outlined
              dark
              dense
              v-model="inviteForm.description"
              :label="$t('adminInvites.description')"
              :hint="$t('adminInvites.descriptionHint')"
            />

            <q-input
              outlined
              dark
              dense
              v-model="inviteForm.expires_at"
              :label="$t('adminInvites.expiresAt')"
              type="datetime-local"
              :hint="$t('adminInvites.expiresAtHint')"
            />

            <q-input
              outlined
              dark
              dense
              v-model.number="inviteForm.max_uses"
              :label="$t('adminInvites.maxUses')"
              type="number"
              min="1"
              :hint="$t('adminInvites.maxUsesHint')"
            />

            <q-toggle v-model="inviteForm.is_active" :label="$t('adminInvites.active')" />
          </q-form>
        </q-card-section>

        <q-card-actions align="right" class="text-primary">
          <q-btn flat :label="$t('adminInvites.cancel')" @click="cancelEdit" />
          <q-btn flat :label="$t('adminInvites.save')" @click="saveInvite" :loading="saving" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Invite Delete Confirmation Dialog -->
    <ConfirmDeleteDialog
      v-model="showDeleteDialog"
      :message="$t('adminInvites.deleteConfirm')"
      :loading="deleting"
      @confirm="deleteInvite"
    />
  </q-page>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { api } from 'boot/axios'
import { useClipboard } from 'src/composables/useClipboard'
import { useI18n } from 'vue-i18n'
import { useQuasar } from 'quasar'
import { useAdminCrudList } from 'src/composables/useAdminCrudList'
import { formatDate as formatDateRaw } from 'src/composables/useMediaFormatters'
import { logger } from 'src/utils/logger'
import ConfirmDeleteDialog from 'src/components/ConfirmDeleteDialog.vue'
const { t } = useI18n()
const $q = useQuasar()

const saving = ref(false)

const {
  tableRef,
  rows,
  filter,
  loading,
  pagination,
  onRequest,
  refresh,
  showDeleteDialog,
  itemToDelete: selectedInvite,
  deleting,
  confirmDelete,
  performDelete: deleteInvite,
} = useAdminCrudList({
  fetchPage: async ({ page, rowsPerPage, sortBy, descending, filter }) => {
    const response = await api.get('/api/invites', {
      params: {
        page,
        size: rowsPerPage,
        sort_by: sortBy,
        sort_desc: descending,
        search: filter,
      },
    })
    return { items: response.data.items, total: response.data.total }
  },
  deleteItem: (invite) => api.delete(`/api/invites/${invite.guid}`),
  errorContext: 'invites',
})

// Dialog states
const showAddDialog = ref(false)
const editMode = ref(false)

// Form data
const inviteForm = ref({
  description: '',
  expires_at: '',
  max_uses: null,
  is_active: true,
})

const columns = [
  {
    name: 'created_by_name',
    align: 'left',
    label: t('adminInvites.colCreatedBy'),
    field: (row) =>
      row.created_by
        ? `${row.created_by.first_name} ${row.created_by.last_name}`
        : t('adminInvites.system'),
    sortable: false,
  },
  {
    name: 'used_by_name',
    align: 'left',
    label: t('adminInvites.colUsedBy'),
    field: (row) => (row.used_by ? `${row.used_by.first_name} ${row.used_by.last_name}` : '-'),
    sortable: false,
  },
  {
    name: 'expires_at',
    align: 'left',
    label: t('adminInvites.colExpiresAt'),
    field: 'expires_at',
    sortable: true,
  },
  {
    name: 'usage',
    align: 'center',
    label: t('adminInvites.colUsage'),
    field: 'usage',
    sortable: false,
  },
  {
    name: 'is_active',
    align: 'center',
    label: t('adminInvites.colActive'),
    field: 'is_active',
    sortable: true,
  },
  {
    name: 'is_used',
    align: 'center',
    label: t('adminInvites.colUsed'),
    field: 'is_used',
    sortable: true,
  },
  {
    name: 'actions',
    align: 'center',
    label: t('adminInvites.colActions'),
    field: 'actions',
    sortable: false,
  },
]

const saveInvite = async () => {
  saving.value = true

  try {
    const inviteData = {
      description: inviteForm.value.description || null,
      expires_at: inviteForm.value.expires_at || null,
      max_uses: inviteForm.value.max_uses || null,
      is_active: inviteForm.value.is_active,
    }

    if (editMode.value) {
      await api.put(`/api/invites/${selectedInvite.value.guid}`, inviteData)
    } else {
      await api.post('/api/invites', inviteData)
    }

    showAddDialog.value = false
    refresh()
  } catch (err) {
    logger.error('Failed to save invite', err)
    const fallback = editMode.value
      ? t('adminInvites.errorUpdate')
      : t('adminInvites.errorCreate')
    $q.notify({
      type: 'negative',
      message: err?.response?.data?.detail || fallback,
    })
  }

  saving.value = false
}

const editInvite = (invite) => {
  selectedInvite.value = invite
  editMode.value = true
  inviteForm.value = {
    description: invite.description || '',
    expires_at: invite.expires_at ? new Date(invite.expires_at).toISOString().slice(0, 16) : '',
    max_uses: invite.max_uses,
    is_active: invite.is_active,
  }
  showAddDialog.value = true
}

const { copy } = useClipboard()

const copyInviteLink = async (invite) => {
  const inviteUrl = `${window.location.origin}/register?invite=${invite.token}`
  await copy(inviteUrl)
}

const cleanupExpired = async () => {
  try {
    await api.post('/api/invites/cleanup')
    refresh()
    $q.notify({ type: 'positive', message: t('adminInvites.successCleanup') })
  } catch (err) {
    logger.error('Failed to clean up expired invites', err)
    $q.notify({
      type: 'negative',
      message: err?.response?.data?.detail || t('adminInvites.errorCleanup'),
    })
  }
}

const cancelEdit = () => {
  showAddDialog.value = false
  editMode.value = false
  selectedInvite.value = null
  inviteForm.value = {
    description: '',
    expires_at: '',
    max_uses: null,
    is_active: true,
  }
}

// Utility functions
const formatDate = (dateString) => formatDateRaw(dateString, { fallback: '-' })

const isExpired = (dateString) => {
  if (!dateString) return false
  return new Date(dateString) < new Date()
}

// Initialize
onMounted(() => {
  refresh()
})
</script>
