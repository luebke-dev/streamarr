<template>
  <q-card flat bordered>
    <q-card-section>
      <div class="text-h6 q-mb-md">
        <q-icon name="mdi-ticket-account" class="q-mr-sm" color="teal" />
        {{ $t('adminUserPage.invites') }}
      </div>

      <div v-if="loading" class="text-center q-pa-lg">
        <q-spinner size="30px" color="primary" />
      </div>

      <div v-else-if="invites.length === 0" class="text-center q-pa-lg text-grey">
        {{ $t('adminUserPage.noInvites') }}
      </div>

      <q-table
        v-else
        flat
        bordered
        dark
        :rows="invites"
        :columns="columns"
        row-key="guid"
        :rows-per-page-options="[10, 25]"
      >
        <template #body-cell-status="props">
          <q-td :props="props">
            <q-badge
              :color="props.row.is_active ? 'positive' : 'negative'"
              :label="
                props.row.is_active ? $t('adminUserPage.active') : $t('adminUserPage.inactive')
              "
            />
          </q-td>
        </template>

        <template #body-cell-uses="props">
          <q-td :props="props">{{ props.row.current_uses }} / {{ props.row.max_uses }}</q-td>
        </template>

        <template #body-cell-expires_at="props">
          <q-td :props="props">{{ formatDate(props.row.expires_at) }}</q-td>
        </template>

        <template #body-cell-created_at="props">
          <q-td :props="props">{{ formatDate(props.row.created_at) }}</q-td>
        </template>
      </q-table>
    </q-card-section>
  </q-card>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { formatDate as formatDateRaw } from 'src/composables/useMediaFormatters'

defineProps({
  invites: { type: Array, required: true },
  loading: { type: Boolean, default: false },
})

const { t, locale } = useI18n()

const columns = computed(() => [
  {
    name: 'description',
    label: t('adminUserPage.inviteDescription'),
    field: 'description',
    align: 'left',
  },
  { name: 'status', label: t('adminUserPage.inviteStatus'), field: 'is_active', align: 'center' },
  { name: 'uses', label: t('adminUserPage.inviteUses'), field: 'current_uses', align: 'center' },
  {
    name: 'expires_at',
    label: t('adminUserPage.inviteExpires'),
    field: 'expires_at',
    align: 'left',
  },
  {
    name: 'created_at',
    label: t('adminUserPage.inviteCreated'),
    field: 'created_at',
    align: 'left',
  },
])

const formatDate = (dateString) =>
  formatDateRaw(dateString, { locale: locale.value, fallback: t('adminUserPage.unknown') })
</script>
