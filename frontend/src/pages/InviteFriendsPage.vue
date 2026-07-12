<template>
  <q-page class="invite-page q-pa-md">
    <div class="row items-center q-mb-lg">
      <div class="col">
        <h1 class="text-h4 q-mb-none">{{ $t('invite.title') }}</h1>
        <p class="text-subtitle1 text-grey-6 q-mb-none">{{ $t('invite.subtitle') }}</p>
      </div>
    </div>

    <div class="row justify-end q-mb-md">
      <q-btn
        color="primary"
        icon="mdi-link-plus"
        :label="$t('invite.createButton')"
        :loading="creating"
        @click="createInvite"
        unelevated
      />
    </div>

    <q-card flat bordered>
      <q-table
        :rows="invites"
        :columns="columns"
        row-key="guid"
        :loading="loading"
        :no-data-label="$t('invite.noInvites')"
        flat
        bordered
        dark
        :pagination="{ rowsPerPage: 20 }"
        hide-pagination
      >
        <template v-slot:body-cell-link="props">
          <q-td :props="props">
            <div class="row items-center no-wrap">
              <code class="invite-link-text ellipsis q-mr-sm">{{ getInviteLink(props.row) }}</code>
              <q-btn
                flat
                round
                dense
                size="sm"
                icon="mdi-content-copy"
                color="grey-7"
                @click="copyInviteLinkForInvite(props.row)"
              >
                <q-tooltip>{{ $t('invite.copyLink') }}</q-tooltip>
              </q-btn>
            </div>
          </q-td>
        </template>

        <template v-slot:body-cell-status="props">
          <q-td :props="props">
            <q-chip :color="getStatusColor(props.row)" text-color="white" size="sm" dense>
              {{ getStatusLabel(props.row) }}
            </q-chip>
          </q-td>
        </template>

        <template v-slot:body-cell-usedBy="props">
          <q-td :props="props">
            <template v-if="props.row.used_by">
              <div class="row items-center no-wrap">
                <q-icon name="mdi-account-check" color="positive" class="q-mr-xs" />
                <span>{{
                  props.row.used_by.preferred_username ||
                  props.row.used_by.email ||
                  props.row.used_by.first_name
                }}</span>
              </div>
            </template>
            <span v-else class="text-grey-5">&mdash;</span>
          </q-td>
        </template>

        <template v-slot:body-cell-createdAt="props">
          <q-td :props="props">{{ formatDate(props.row.created_at) }}</q-td>
        </template>

        <template v-slot:body-cell-expiresAt="props">
          <q-td :props="props">{{ formatDate(props.row.expires_at) }}</q-td>
        </template>

        <template v-slot:body-cell-actions="props">
          <q-td :props="props" auto-width>
            <q-btn
              flat
              round
              dense
              icon="mdi-delete-outline"
              color="negative"
              @click="confirmDeleteInvite(props.row)"
            >
              <q-tooltip>{{ $t('invite.delete') }}</q-tooltip>
            </q-btn>
          </q-td>
        </template>
      </q-table>
    </q-card>

    <!-- Delete Invite Dialog -->
    <q-dialog v-model="showDeleteDialog" persistent>
      <q-card dark>
        <q-card-section class="row items-center">
          <q-avatar icon="mdi-alert" color="negative" text-color="white" />
          <span class="q-ml-sm">{{ $t('invite.deleteConfirm') }}</span>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat :label="$t('common.cancel')" @click="showDeleteDialog = false" />
          <q-btn
            flat
            :label="$t('common.delete')"
            color="negative"
            @click="deleteInvite"
            :loading="deleting"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script>
import { defineComponent, ref, computed, onMounted } from 'vue'
import { useClipboard } from 'src/composables/useClipboard'
import { useI18n } from 'vue-i18n'
import { useQuasar } from 'quasar'
import {
  getInvites,
  createInvite as createInviteApi,
  deleteInvite as deleteInviteApi,
} from 'src/services/socialService'
import { logger } from 'src/utils/logger'

export default defineComponent({
  name: 'InviteFriendsPage',
  setup() {
    const { t } = useI18n()
    const { copy } = useClipboard()
    const $q = useQuasar()
    const notifyError = (err, context) => {
      logger.warn(`InviteFriendsPage: ${context} failed`, err)
      $q.notify({ type: 'negative', message: t('common.actionFailed') })
    }

    const loading = ref(false)
    const creating = ref(false)
    const deleting = ref(false)
    const invites = ref([])
    const showDeleteDialog = ref(false)
    const selectedInvite = ref(null)

    const columns = computed(() => [
      {
        name: 'link',
        label: t('invite.link'),
        field: 'token',
        align: 'left',
        sortable: false,
        style: 'max-width: 350px',
      },
      {
        name: 'status',
        label: t('invite.statusLabel'),
        field: 'is_used',
        align: 'center',
        sortable: true,
      },
      {
        name: 'usedBy',
        label: t('invite.usedBy'),
        field: 'used_by',
        align: 'left',
        sortable: false,
      },
      {
        name: 'createdAt',
        label: t('invite.createdAt'),
        field: 'created_at',
        align: 'left',
        sortable: true,
      },
      {
        name: 'expiresAt',
        label: t('invite.expiresAt'),
        field: 'expires_at',
        align: 'left',
        sortable: true,
      },
      { name: 'actions', label: '', field: 'guid', align: 'right', sortable: false },
    ])

    const getInviteLink = (invite) => `${window.location.origin}/register?invite=${invite.token}`
    const formatDate = (d) => (d ? new Date(d).toLocaleString() : '-')
    const isExpired = (invite) => new Date(invite.expires_at) < new Date()

    const getStatusColor = (invite) => {
      if (invite.is_used || invite.current_uses > 0) return 'positive'
      if (!invite.is_active) return 'grey'
      if (isExpired(invite)) return 'negative'
      return 'primary'
    }

    const getStatusLabel = (invite) => {
      if (invite.is_used || invite.current_uses > 0) return t('invite.status.accepted')
      if (!invite.is_active) return t('invite.status.inactive')
      if (isExpired(invite)) return t('invite.status.expired')
      return t('invite.status.pending')
    }

    const loadInvites = async () => {
      loading.value = true
      try {
        const data = await getInvites()
        invites.value = Array.isArray(data) ? data : data.items || []
      } catch (err) {
        notifyError(err, 'loadInvites')
      } finally {
        loading.value = false
      }
    }

    const createInvite = async () => {
      creating.value = true
      try {
        const data = await createInviteApi({ expiry_hours: 168, max_uses: 1 })
        const link = `${window.location.origin}/register?invite=${data.token}`
        await copy(link)
        await loadInvites()
      } catch (err) {
        notifyError(err, 'createInvite')
      } finally {
        creating.value = false
      }
    }

    const copyInviteLinkForInvite = async (invite) => {
      await copy(getInviteLink(invite))
    }

    const confirmDeleteInvite = (invite) => {
      selectedInvite.value = invite
      showDeleteDialog.value = true
    }

    const deleteInvite = async () => {
      if (!selectedInvite.value) return
      deleting.value = true
      try {
        await deleteInviteApi(selectedInvite.value.guid)
        showDeleteDialog.value = false
        await loadInvites()
      } catch (err) {
        notifyError(err, 'deleteInvite')
      } finally {
        deleting.value = false
      }
    }

    onMounted(() => {
      loadInvites()
    })

    return {
      loading,
      creating,
      deleting,
      invites,
      columns,
      showDeleteDialog,
      getInviteLink,
      formatDate,
      getStatusColor,
      getStatusLabel,
      createInvite,
      copyInviteLinkForInvite,
      confirmDeleteInvite,
      deleteInvite,
    }
  },
})
</script>

<style scoped>
.invite-page {
  max-width: 1000px;
  margin: 0 auto;
}

.invite-link-text {
  font-size: 0.8rem;
  max-width: 280px;
  display: inline-block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: middle;
}
</style>
