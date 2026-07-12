<template>
  <div class="col-12">
    <q-card class="settings-card">
      <q-card-section>
        <div class="text-h6 q-mb-md">
          <q-icon name="mdi-backup-restore" class="q-mr-sm" />
          {{ $t('adminSettings.backups.title') }}
        </div>
        <p class="text-grey-6 q-mb-md">
          {{ $t('adminSettings.backups.description') }}
        </p>

        <div class="row q-col-gutter-md">
          <div class="col-12 col-md-5">
            <div class="text-subtitle2 q-mb-sm">
              {{ $t('adminSettings.backups.exportTitle') }}
            </div>
            <div class="row q-col-gutter-sm q-mb-md">
              <div class="col-12 col-sm-6">
                <q-btn
                  color="primary"
                  icon="mdi-cog-transfer"
                  :label="$t('adminSettings.backups.exportSettings')"
                  :loading="backupLoading === 'settings'"
                  class="full-width"
                  no-caps
                  @click="exportSettingsBackup"
                />
              </div>
              <div class="col-12 col-sm-6">
                <q-btn
                  color="primary"
                  icon="mdi-database-export"
                  :label="$t('adminSettings.backups.exportDatabase')"
                  :loading="backupLoading === 'database'"
                  class="full-width"
                  no-caps
                  @click="exportDatabaseBackup"
                />
              </div>
            </div>
            <q-input
              v-model="backupPayloadText"
              type="textarea"
              :label="$t('adminSettings.backups.exportOutput')"
              outlined
              autogrow
              readonly
            />
          </div>

          <div class="col-12 col-md-7">
            <div class="text-subtitle2 q-mb-sm">
              {{ $t('adminSettings.backups.restoreTitle') }}
            </div>
            <q-input
              v-model="restorePayloadText"
              type="textarea"
              :label="$t('adminSettings.backups.restorePayload')"
              outlined
              autogrow
              class="q-mb-md"
            />
            <div class="row q-col-gutter-md">
              <div class="col-12 col-sm-4">
                <q-toggle
                  v-model="restoreDryRun"
                  :label="$t('adminSettings.backups.dryRun')"
                  color="primary"
                />
              </div>
              <div class="col-12 col-sm-4">
                <q-toggle
                  v-model="restoreSkipRedacted"
                  :label="$t('adminSettings.backups.skipRedacted')"
                  color="primary"
                />
              </div>
              <div class="col-12 col-sm-4">
                <q-toggle
                  v-model="restoreDeleteMissingRows"
                  :label="$t('adminSettings.backups.deleteMissingRows')"
                  color="negative"
                />
              </div>
            </div>
            <q-input
              v-model="restoreDeleteMissingTablesText"
              :label="$t('adminSettings.backups.deleteMissingTables')"
              :hint="$t('adminSettings.backups.deleteMissingTablesHint')"
              outlined
              dense
              class="q-mt-sm"
              :disable="!restoreDeleteMissingRows"
            />
            <q-input
              v-if="restoreRequiresConfirmation"
              v-model="restoreConfirmation"
              :label="$t('adminSettings.backups.destructiveConfirmation')"
              :hint="$t('adminSettings.backups.destructiveConfirmationHint')"
              outlined
              dense
              color="negative"
              class="q-mt-md"
            />
            <q-banner
              v-if="restoreDryRun"
              rounded
              class="bg-blue-grey-9 text-white q-mt-md"
            >
              <template v-slot:avatar>
                <q-icon name="mdi-shield-check" color="info" />
              </template>
              {{ $t('adminSettings.backups.dryRunInfo') }}
            </q-banner>
            <q-banner
              v-else-if="restoreDeleteMissingRows"
              rounded
              class="bg-negative text-white q-mt-md"
            >
              <template v-slot:avatar>
                <q-icon name="mdi-alert" color="white" />
              </template>
              {{ $t('adminSettings.backups.destructiveInfo') }}
            </q-banner>
            <div class="row q-gutter-sm q-mt-md">
              <q-btn
                color="primary"
                icon="mdi-database-import"
                :label="$t('adminSettings.backups.restoreDatabase')"
                :loading="restoreLoading === 'database'"
                :disable="restoreDatabaseDisabled"
                no-caps
                @click="restoreDatabaseBackup"
              />
              <q-btn
                flat
                color="primary"
                icon="mdi-cog-transfer"
                :label="$t('adminSettings.backups.restoreSettings')"
                :loading="restoreLoading === 'settings'"
                :disable="restoreSettingsDisabled"
                no-caps
                @click="restoreSettingsBackup"
              />
            </div>
            <q-banner
              v-if="restoreError"
              rounded
              class="bg-negative text-white q-mt-md"
            >
              {{ restoreError }}
            </q-banner>
            <q-list v-if="restoreResult" dense bordered class="q-mt-md">
              <q-item>
                <q-item-section>
                  <q-item-label>{{ $t('adminSettings.backups.restoreResult') }}</q-item-label>
                  <q-item-label caption>
                    {{ restoreResultSummary }}
                  </q-item-label>
                </q-item-section>
              </q-item>
              <q-item v-if="restoreResult.errors?.length">
                <q-item-section>
                  <q-item-label>{{ $t('adminSettings.backups.restoreErrors') }}</q-item-label>
                  <q-item-label
                    v-for="error in restoreResult.errors"
                    :key="error"
                    caption
                  >
                    {{ error }}
                  </q-item-label>
                </q-item-section>
              </q-item>
            </q-list>
          </div>
        </div>
      </q-card-section>
    </q-card>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { logger } from 'src/utils/logger'
import {
  getSettingsBackup,
  getDatabaseBackup,
  restoreDatabaseBackup as restoreDatabaseBackupApi,
  restoreSettingsBackup as restoreSettingsBackupApi,
} from 'src/services/systemAdminService'

const props = defineProps({
  // Called after a successful settings restore to reload the rest of the page,
  // mirroring the parent's loadSettings() call in the original component.
  reloadSettings: {
    type: Function,
    default: () => Promise.resolve(),
  },
})

const { t } = useI18n()

const backupLoading = ref(null)
const backupPayloadText = ref('')
const restorePayloadText = ref('')
const restoreDryRun = ref(true)
const restoreSkipRedacted = ref(true)
const restoreDeleteMissingRows = ref(false)
const restoreDeleteMissingTablesText = ref('')
const restoreConfirmation = ref('')
const restoreLoading = ref(null)
const restoreResult = ref(null)
const restoreError = ref('')

const restoreRequiresConfirmation = computed(
  () => restoreDeleteMissingRows.value && !restoreDryRun.value,
)

const restoreDatabaseDisabled = computed(
  () =>
    restoreLoading.value !== null ||
    !restorePayloadText.value.trim() ||
    (restoreRequiresConfirmation.value &&
      restoreConfirmation.value !== 'DELETE_MISSING_ROWS'),
)

const restoreSettingsDisabled = computed(
  () => restoreLoading.value !== null || !restorePayloadText.value.trim(),
)

const restoreResultSummary = computed(() => {
  if (!restoreResult.value) return ''
  if ('restored_rows' in restoreResult.value) {
    return t('adminSettings.backups.databaseRestoreSummary', restoreResult.value)
  }
  return t('adminSettings.backups.settingsRestoreSummary', restoreResult.value)
})

const formatBackupPayload = (payload) => JSON.stringify(payload, null, 2)

const parseRestorePayload = () => {
  const payload = JSON.parse(restorePayloadText.value)
  return payload && typeof payload === 'object' ? payload : {}
}

const restoreDeleteMissingTables = () =>
  restoreDeleteMissingTablesText.value
    .split(',')
    .map((table) => table.trim())
    .filter(Boolean)

const exportSettingsBackup = async () => {
  backupLoading.value = 'settings'
  try {
    const data = await getSettingsBackup()
    backupPayloadText.value = formatBackupPayload(data)
  } catch (error) {
    logger.error('Failed to export settings backup:', error)
  } finally {
    backupLoading.value = null
  }
}

const exportDatabaseBackup = async () => {
  backupLoading.value = 'database'
  try {
    const data = await getDatabaseBackup()
    backupPayloadText.value = formatBackupPayload(data)
  } catch (error) {
    logger.error('Failed to export database backup:', error)
  } finally {
    backupLoading.value = null
  }
}

const restoreDatabaseBackup = async () => {
  restoreLoading.value = 'database'
  restoreResult.value = null
  restoreError.value = ''
  try {
    const payload = parseRestorePayload()
    const data = await restoreDatabaseBackupApi({
      tables: payload.tables || payload,
      dry_run: restoreDryRun.value,
      skip_redacted: restoreSkipRedacted.value,
      delete_missing_rows: restoreDeleteMissingRows.value,
      delete_missing_tables: restoreDeleteMissingRows.value ? restoreDeleteMissingTables() : [],
      destructive_confirmation: restoreConfirmation.value || null,
    })
    restoreResult.value = data
  } catch (error) {
    logger.error('Failed to restore database backup:', error)
    restoreError.value = error.response?.data?.detail || error.message
  } finally {
    restoreLoading.value = null
  }
}

const restoreSettingsBackup = async () => {
  restoreLoading.value = 'settings'
  restoreResult.value = null
  restoreError.value = ''
  try {
    const payload = parseRestorePayload()
    const data = await restoreSettingsBackupApi({
      settings: payload.settings || payload,
      skip_redacted: restoreSkipRedacted.value,
    })
    restoreResult.value = data
    await props.reloadSettings()
  } catch (error) {
    logger.error('Failed to restore settings backup:', error)
    restoreError.value = error.response?.data?.detail || error.message
  } finally {
    restoreLoading.value = null
  }
}
</script>

<style lang="scss" scoped>
.settings-card {
  background: rgba(255, 255, 255, 0.05);
  backdrop-filter: blur(10px);
  border: 1px solid rgba(255, 255, 255, 0.1);
}
</style>
