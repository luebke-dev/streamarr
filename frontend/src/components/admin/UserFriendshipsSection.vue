<template>
  <q-card flat bordered>
    <q-card-section>
      <div class="text-h6 q-mb-md">
        <q-icon name="mdi-account-group" class="q-mr-sm" color="pink" />
        {{ $t('adminUserPage.friendships') }}
      </div>

      <div v-if="loading" class="text-center q-pa-lg">
        <q-spinner size="30px" color="primary" />
      </div>

      <div v-else-if="friendships.length === 0" class="text-center q-pa-lg text-grey">
        {{ $t('adminUserPage.noFriendships') }}
      </div>

      <q-table
        v-else
        flat
        bordered
        dark
        :rows="friendships"
        :columns="columns"
        row-key="guid"
        :rows-per-page-options="[10, 25]"
      >
        <template #body-cell-friend="props">
          <q-td :props="props">
            <div class="row items-center no-wrap q-gutter-sm">
              <q-avatar size="32px" color="primary" text-color="white">
                <img
                  v-if="getFriend(props.row).picture"
                  :src="getFriend(props.row).picture"
                  :alt="`${getFriend(props.row).first_name} ${getFriend(props.row).last_name}`"
                />
                <span v-else>{{ getFriend(props.row).first_name?.[0] || '?' }}</span>
              </q-avatar>
              <div>
                <div class="text-weight-medium">
                  {{ getFriend(props.row).first_name }} {{ getFriend(props.row).last_name }}
                </div>
                <div class="text-caption text-grey">{{ getFriend(props.row).email }}</div>
              </div>
            </div>
          </q-td>
        </template>

        <template #body-cell-status="props">
          <q-td :props="props">
            <q-badge :color="getStatusColor(props.row.status)" :label="props.row.status" />
          </q-td>
        </template>

        <template #body-cell-direction="props">
          <q-td :props="props">
            <q-badge
              outline
              :color="props.row.requester.guid === userGuid ? 'blue' : 'orange'"
              :label="
                props.row.requester.guid === userGuid
                  ? $t('adminUserPage.sent')
                  : $t('adminUserPage.received')
              "
            />
          </q-td>
        </template>
      </q-table>
    </q-card-section>
  </q-card>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const props = defineProps({
  friendships: { type: Array, required: true },
  loading: { type: Boolean, default: false },
  userGuid: { type: String, required: true },
})

const { t } = useI18n()

const columns = computed(() => [
  {
    name: 'friend',
    label: t('adminUserPage.friend'),
    field: 'guid',
    align: 'left',
    sortable: false,
  },
  { name: 'status', label: t('adminUserPage.friendshipStatus'), field: 'status', align: 'center' },
  {
    name: 'direction',
    label: t('adminUserPage.friendshipDirection'),
    field: 'guid',
    align: 'center',
    sortable: false,
  },
])

const getFriend = (row) => {
  return String(row.requester.guid) === String(props.userGuid) ? row.addressee : row.requester
}

const getStatusColor = (status) => {
  const colors = { accepted: 'positive', pending: 'warning', blocked: 'negative' }
  return colors[status] || 'grey'
}
</script>
