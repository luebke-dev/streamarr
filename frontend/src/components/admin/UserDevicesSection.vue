<template>
  <q-card flat bordered>
    <q-card-section>
      <div class="text-h6 q-mb-md">
        <q-icon name="mdi-devices" class="q-mr-sm" color="cyan" />
        {{ $t('adminUserPage.devices') }}
      </div>

      <div v-if="loading" class="text-center q-pa-lg">
        <q-spinner size="30px" color="primary" />
      </div>

      <div v-else-if="devices.length === 0" class="text-center q-pa-lg text-grey">
        {{ $t('adminUserPage.noDevices') }}
      </div>

      <q-table
        v-else
        flat
        bordered
        dark
        :rows="devices"
        :columns="columns"
        row-key="guid"
        :rows-per-page-options="[10, 25]"
      >
        <template #body-cell-name="props">
          <q-td :props="props">
            <div class="text-weight-medium">
              {{ props.row.name || props.row.browser || $t('adminUserPage.unknownDevice') }}
            </div>
            <div class="text-caption text-grey">{{ props.row.platform }}</div>
          </q-td>
        </template>

        <template #body-cell-status="props">
          <q-td :props="props">
            <q-badge
              :color="props.row.is_active ? 'positive' : 'negative'"
              :label="
                props.row.is_active ? $t('adminUserPage.active') : $t('adminUserPage.inactive')
              "
              class="q-mr-xs"
            />
            <q-badge
              v-if="props.row.is_trusted"
              color="info"
              :label="$t('adminUserPage.trusted')"
              class="q-mr-xs"
            />
            <q-badge
              v-if="props.row.is_playing"
              color="warning"
              text-color="dark"
              :label="$t('adminUserPage.playing')"
            />
          </q-td>
        </template>

        <template #body-cell-last_activity="props">
          <q-td :props="props">{{ formatDate(props.row.last_activity) }}</q-td>
        </template>

        <template #body-cell-last_ip="props">
          <q-td :props="props">
            <span class="text-mono">{{ props.row.last_ip_address || '-' }}</span>
          </q-td>
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
  devices: { type: Array, required: true },
  loading: { type: Boolean, default: false },
})

const { t, locale } = useI18n()

const columns = computed(() => [
  { name: 'name', label: t('adminUserPage.deviceName'), field: 'name', align: 'left' },
  { name: 'status', label: t('adminUserPage.deviceStatus'), field: 'is_active', align: 'left' },
  {
    name: 'last_activity',
    label: t('adminUserPage.deviceLastActivity'),
    field: 'last_activity',
    align: 'left',
  },
  {
    name: 'last_ip',
    label: t('adminUserPage.deviceLastIp'),
    field: 'last_ip_address',
    align: 'left',
  },
])

const formatDate = (dateString) =>
  formatDateRaw(dateString, { locale: locale.value, fallback: t('adminUserPage.unknown') })
</script>

<style scoped>
.text-mono {
  font-family: 'Courier New', monospace;
  font-size: 0.9em;
}
</style>
