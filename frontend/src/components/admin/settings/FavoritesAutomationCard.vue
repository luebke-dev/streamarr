<template>
  <div class="col-12 col-md-6">
    <q-card class="settings-card">
      <q-card-section>
        <div class="text-h6 q-mb-md">
          <q-icon name="mdi-robot" class="q-mr-sm" />
          {{ $t('adminSettings.automation.title') }}
        </div>
        <p class="text-grey-6 q-mb-md">
          {{ $t('adminSettings.automation.description') }}
        </p>

        <q-toggle
          v-model="automation.favorites_autodownload_enabled"
          :label="$t('adminSettings.automation.autodownload')"
          color="primary"
          @update:model-value="updateAutomationSettings"
          :disable="savingAutomation"
        />
        <q-toggle
          v-model="automation.upgrades_enabled"
          :label="$t('adminSettings.automation.upgrades')"
          color="primary"
          class="block q-mt-sm"
          @update:model-value="updateAutomationSettings"
          :disable="savingAutomation"
        />
        <q-toggle
          v-model="automation.rss_sync_enabled"
          :label="$t('adminSettings.automation.rssSync')"
          color="primary"
          class="block q-mt-sm"
          @update:model-value="updateAutomationSettings"
          :disable="savingAutomation"
        />
        <q-toggle
          v-model="automation.realtime_library_monitor"
          :label="$t('adminSettings.automation.realtimeLibraryMonitor')"
          color="primary"
          class="block q-mt-sm"
          @update:model-value="updateAutomationSettings"
          :disable="savingAutomation"
        />

        <div class="row q-col-gutter-md q-mt-sm">
          <q-input
            class="col-12 col-sm-4"
            v-model.number="automation.library_scan_interval_hours"
            type="number"
            min="1"
            max="168"
            dense
            :label="$t('adminSettings.automation.libraryScanInterval')"
            :rules="[automationNumberRule(1)]"
            @blur="updateAutomationSettings"
            :disable="savingAutomation"
          />
          <q-input
            class="col-12 col-sm-4"
            v-model.number="automation.rss_min_interval_minutes"
            type="number"
            min="1"
            dense
            :label="$t('adminSettings.automation.rssInterval')"
            :rules="[automationNumberRule(1)]"
            @blur="updateAutomationSettings"
            :disable="savingAutomation"
          />
          <q-input
            class="col-12 col-sm-4"
            v-model.number="automation.upgrade_scan_batch_size"
            type="number"
            min="1"
            dense
            :label="$t('adminSettings.automation.batchSize')"
            :rules="[automationNumberRule(1)]"
            @blur="updateAutomationSettings"
            :disable="savingAutomation"
          />
          <q-input
            class="col-12 col-sm-4"
            v-model.number="automation.max_concurrent_upgrade_downloads"
            type="number"
            min="1"
            dense
            :label="$t('adminSettings.automation.maxConcurrent')"
            :rules="[automationNumberRule(1)]"
            @blur="updateAutomationSettings"
            :disable="savingAutomation"
          />
        </div>

        <q-banner class="bg-grey-9 q-mt-md" rounded>
          <template v-slot:avatar>
            <q-icon name="mdi-information" color="info" />
          </template>
          {{ $t('adminSettings.automation.info') }}
        </q-banner>
      </q-card-section>
    </q-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import { logger } from 'src/utils/logger'
import {
  getAutomationSettings,
  saveAutomationSettings,
} from 'src/services/systemAdminService'

const { t } = useI18n()
const $q = useQuasar()

const savingAutomation = ref(false)
const automation = ref({
  favorites_autodownload_enabled: false,
  upgrades_enabled: false,
  rss_sync_enabled: false,
  rss_min_interval_minutes: 15,
  upgrade_scan_batch_size: 25,
  max_concurrent_upgrade_downloads: 3,
  library_scan_interval_hours: 12,
  realtime_library_monitor: true,
})

// Minimum allowed value for each numeric automation field. Used both for the
// per-input validation rules and the guard in updateAutomationSettings so we
// never PUT NaN/empty/out-of-range values to the scheduler.
const AUTOMATION_NUMERIC_MINIMUMS = {
  rss_min_interval_minutes: 1,
  upgrade_scan_batch_size: 1,
  max_concurrent_upgrade_downloads: 1,
  library_scan_interval_hours: 1,
}

const automationNumberRule = (min) => (val) => {
  const num = Number(val)
  return (
    (val !== null && val !== '' && Number.isFinite(num) && num >= min) ||
    t('adminSettings.automation.minValue', `Must be a number of at least ${min}`)
  )
}

const hasInvalidAutomationNumbers = () =>
  Object.entries(AUTOMATION_NUMERIC_MINIMUMS).some(([field, min]) => {
    const num = Number(automation.value[field])
    return automation.value[field] === '' || !Number.isFinite(num) || num < min
  })

const updateAutomationSettings = async () => {
  if (hasInvalidAutomationNumbers()) {
    $q.notify({
      type: 'negative',
      message: t(
        'adminSettings.automation.invalidNumeric',
        'Please enter a valid number (1 or greater) for all automation intervals.',
      ),
    })
    // Restore known-good values from the server so a later save can proceed.
    await reloadAutomationSettings()
    return
  }
  savingAutomation.value = true
  try {
    const data = await saveAutomationSettings(automation.value)
    automation.value = { ...automation.value, ...data }
  } catch (error) {
    logger.error('Failed to update automation settings:', error)
    $q.notify({
      type: 'negative',
      message: t('adminSettings.automation.saveError', 'Failed to save automation settings'),
    })
  } finally {
    savingAutomation.value = false
  }
}

const reloadAutomationSettings = async () => {
  try {
    const autoData = await getAutomationSettings()
    automation.value = { ...automation.value, ...autoData }
  } catch (error) {
    logger.error('Failed to reload automation settings:', error)
  }
}

const loadAutomationSettings = async () => {
  try {
    const autoData = await getAutomationSettings()
    automation.value = { ...automation.value, ...autoData }
  } catch (error) {
    logger.error('Failed to load automation settings:', error)
  }
}

onMounted(loadAutomationSettings)

defineExpose({ reload: loadAutomationSettings })
</script>

<style lang="scss" scoped>
.settings-card {
  background: rgba(255, 255, 255, 0.05);
  backdrop-filter: blur(10px);
  border: 1px solid rgba(255, 255, 255, 0.1);
}
</style>
