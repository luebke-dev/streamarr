<template>
  <q-card flat bordered>
    <q-card-section>
      <div class="text-h6 q-mb-md">
        <q-icon name="mdi-download" class="q-mr-sm" color="indigo" />
        {{ $t('adminUserPage.downloads') }}
      </div>

      <div v-if="loading" class="text-center q-pa-lg">
        <q-spinner size="30px" color="primary" />
      </div>

      <div v-else-if="downloads.length === 0" class="text-center q-pa-lg text-grey">
        {{ $t('adminUserPage.noDownloads') }}
      </div>

      <q-table
        v-else
        flat
        bordered
        dark
        :rows="downloads"
        :columns="columns"
        row-key="guid"
        :rows-per-page-options="[10, 25, 50]"
      >
        <template #body-cell-display_title="props">
          <q-td :props="props">
            <router-link
              v-if="props.row.media_item_guid"
              :to="`/libraries/${props.row.media_item_guid}`"
              class="text-primary"
              style="text-decoration: none"
            >
              {{ props.row.display_title }}
            </router-link>
            <span v-else>{{ props.row.display_title }}</span>
          </q-td>
        </template>

        <template #body-cell-status="props">
          <q-td :props="props">
            <q-chip :color="getStatusColor(props.value)" text-color="white" size="sm" dense>
              {{
                $t(
                  `adminUserPage.downloadStatuses.${(props.value || '').toLowerCase()}`,
                  props.value,
                )
              }}
            </q-chip>
          </q-td>
        </template>

        <template #body-cell-progress="props">
          <q-td :props="props">
            <div v-if="props.value !== null" class="row items-center no-wrap">
              <q-linear-progress
                :value="props.value / 100"
                :color="props.value >= 100 ? 'positive' : 'primary'"
                class="col q-mr-sm"
                size="8px"
                rounded
              />
              <span class="text-caption">{{ props.value.toFixed(1) }}%</span>
            </div>
            <span v-else class="text-grey">-</span>
          </q-td>
        </template>

        <template #body-cell-created_at="props">
          <q-td :props="props">
            {{ props.value ? new Date(props.value).toLocaleString() : '-' }}
          </q-td>
        </template>
      </q-table>
    </q-card-section>
  </q-card>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

defineProps({
  downloads: { type: Array, required: true },
  loading: { type: Boolean, default: false },
})

const { t } = useI18n()

const columns = computed(() => [
  {
    name: 'display_title',
    label: t('adminUserPage.downloadTitle'),
    field: 'display_title',
    align: 'left',
    sortable: true,
  },
  {
    name: 'status',
    label: t('adminUserPage.downloadStatus'),
    field: 'status',
    align: 'left',
    sortable: true,
  },
  {
    name: 'progress',
    label: t('adminUserPage.downloadProgress'),
    field: 'progress',
    align: 'left',
    sortable: true,
  },
  {
    name: 'created_at',
    label: t('adminUserPage.downloadCreated'),
    field: 'created_at',
    align: 'left',
    sortable: true,
  },
])

const getStatusColor = (status) => {
  const colors = {
    queued: 'grey',
    downloading: 'blue',
    paused: 'orange',
    completed: 'green',
    failed: 'red',
    imported: 'teal',
  }
  return colors[(status || '').toLowerCase()] || 'grey'
}
</script>
