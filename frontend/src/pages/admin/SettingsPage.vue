<template>
  <q-page class="settings-page q-pa-md">
    <div class="row items-center q-mb-lg">
      <div class="col">
        <h4 class="text-h4 text-white q-ma-none">{{ $t('adminSettings.title') }}</h4>
        <p class="text-grey-4 q-ma-none q-mt-xs">{{ $t('adminSettings.subtitle') }}</p>
      </div>
    </div>

    <div class="row q-col-gutter-md">
      <!-- System Settings Card -->
      <div class="col-12 col-md-6">
        <q-card class="settings-card">
          <q-card-section>
            <div class="text-h6 q-mb-md">
              <q-icon name="mdi-cog" class="q-mr-sm" />
              {{ $t('adminSettings.system.title') }}
            </div>
            <p class="text-grey-6 q-mb-md">
              {{ $t('adminSettings.system.description') }}
            </p>

            <q-input
              v-model="siteName"
              :label="$t('adminSettings.system.siteName')"
              :hint="$t('adminSettings.system.siteNameHint')"
              outlined
              dense
              class="q-mb-md"
              :disable="saving"
            >
              <template v-slot:append>
                <q-btn
                  flat
                  dense
                  round
                  icon="mdi-content-save"
                  @click="updateSystemSettings"
                  :disable="saving || !siteName"
                  :loading="saving"
                />
              </template>
            </q-input>
          </q-card-section>
        </q-card>
      </div>

      <!-- OIDC Settings Card -->
      <div class="col-12">
        <q-card class="settings-card">
          <q-card-section>
            <div class="text-h6 q-mb-md">
              <q-icon name="mdi-shield-account" class="q-mr-sm" />
              OIDC
            </div>

            <q-form @submit="saveOidcSettings" class="q-gutter-md">
              <div class="row q-col-gutter-md">
                <div class="col-12 col-md-4">
                  <q-toggle
                    v-model="oidcSettings.enabled"
                    :label="$t('adminSettings.oidc.enable')"
                    color="primary"
                    :disable="saving"
                  />
                </div>
                <div class="col-12 col-md-4">
                  <q-toggle
                    v-model="oidcSettings.local_auth_enabled"
                    :label="$t('adminSettings.oidc.allowLocalLogin')"
                    color="primary"
                    :disable="saving"
                  />
                </div>
                <div class="col-12 col-md-4">
                  <q-toggle
                    v-model="oidcSettings.auto_register_users"
                    :label="$t('adminSettings.oidc.autoRegisterUsers')"
                    color="primary"
                    :disable="saving"
                  />
                </div>
              </div>

              <div class="row q-col-gutter-md">
                <div class="col-12 col-md-6">
                  <q-input
                    v-model="oidcSettings.client_id"
                    label="Client ID"
                    outlined
                    dense
                    :disable="saving"
                  />
                </div>
                <div class="col-12 col-md-6">
                  <q-input
                    v-model="oidcSettings.client_secret"
                    :label="
                      oidcSettings.client_secret_configured
                        ? 'Client Secret (gesetzt, leer lassen zum Beibehalten)'
                        : 'Client Secret'
                    "
                    type="password"
                    outlined
                    dense
                    :disable="saving"
                  />
                </div>
              </div>

              <q-input
                v-model="oidcSettings.server_metadata_url"
                label="Discovery URL"
                placeholder="https://idp.example.com/.well-known/openid-configuration"
                outlined
                dense
                :disable="saving"
              />

              <div class="row q-col-gutter-md">
                <div class="col-12 col-md-6">
                  <q-input
                    v-model="oidcSettings.redirect_uri"
                    label="Redirect URI"
                    outlined
                    dense
                    :disable="saving"
                  />
                </div>
                <div class="col-12 col-md-6">
                  <q-input
                    v-model="oidcSettings.post_logout_redirect_uri"
                    label="Post Logout Redirect URI"
                    outlined
                    dense
                    :disable="saving"
                  />
                </div>
              </div>

              <q-input
                v-model="oidcScopes"
                label="Scopes"
                :hint="$t('adminSettings.oidc.scopesHint')"
                outlined
                dense
                :disable="saving"
              />

              <div class="row justify-end">
                <q-btn
                  type="submit"
                  color="primary"
                  icon="mdi-content-save"
                  :label="$t('adminSettings.oidc.save')"
                  :loading="saving"
                  :disable="saving"
                />
              </div>
            </q-form>
          </q-card-section>
        </q-card>
      </div>

      <!-- Subscription Settings Card -->
      <div class="col-12 col-md-6">
        <q-card class="settings-card">
          <q-card-section>
            <div class="text-h6 q-mb-md">
              <q-icon name="mdi-credit-card" class="q-mr-sm" />
              {{ $t('adminSettings.subscriptions.title') }}
            </div>
            <p class="text-grey-6 q-mb-md">
              {{ $t('adminSettings.subscriptions.description') }}
            </p>

            <q-toggle
              v-model="subscriptionsEnabled"
              :label="$t('adminSettings.subscriptions.enableSubscriptions')"
              color="primary"
              @update:model-value="updateSubscriptionSettings"
              :disable="saving"
            />

            <q-banner v-if="!subscriptionsEnabled" class="bg-grey-9 q-mt-md" rounded>
              <template v-slot:avatar>
                <q-icon name="mdi-information" color="info" />
              </template>
              {{ $t('adminSettings.subscriptions.disabledInfo') }}
            </q-banner>
          </q-card-section>
        </q-card>
      </div>

      <!-- Invite System Settings Card -->
      <div class="col-12 col-md-6">
        <q-card class="settings-card">
          <q-card-section>
            <div class="text-h6 q-mb-md">
              <q-icon name="mdi-account-multiple-plus" class="q-mr-sm" />
              {{ $t('adminSettings.invites.title') }}
            </div>
            <p class="text-grey-6 q-mb-md">
              {{ $t('adminSettings.invites.description') }}
            </p>

            <q-toggle
              v-model="invitesEnabled"
              :label="$t('adminSettings.invites.enableInvites')"
              color="primary"
              @update:model-value="updateInviteSettings"
              :disable="saving"
            />

            <q-banner v-if="!invitesEnabled" class="bg-grey-9 q-mt-md" rounded>
              <template v-slot:avatar>
                <q-icon name="mdi-information" color="info" />
              </template>
              {{ $t('adminSettings.invites.disabledInfo') }}
            </q-banner>
          </q-card-section>
        </q-card>
      </div>
      <!-- Favorites Settings Card -->
      <div class="col-12 col-md-6">
        <q-card class="settings-card">
          <q-card-section>
            <div class="text-h6 q-mb-md">
              <q-icon name="mdi-heart" class="q-mr-sm" />
              {{ $t('adminSettings.favorites.title') }}
            </div>
            <p class="text-grey-6 q-mb-md">
              {{ $t('adminSettings.favorites.description') }}
            </p>

            <q-toggle
              v-model="favoritesPermanent"
              :label="$t('adminSettings.favorites.permanent')"
              color="primary"
              @update:model-value="updateFavoritesSettings"
              :disable="saving"
            />

            <q-banner v-if="favoritesPermanent" class="bg-grey-9 q-mt-md" rounded>
              <template v-slot:avatar>
                <q-icon name="mdi-information" color="info" />
              </template>
              {{ $t('adminSettings.favorites.permanentInfo') }}
            </q-banner>
          </q-card-section>
        </q-card>
      </div>

      <!-- Favorites Automation Card -->
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

            <div class="row q-col-gutter-md q-mt-sm">
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

      <!-- Friends Settings Card -->
      <div class="col-12 col-md-6">
        <q-card class="settings-card">
          <q-card-section>
            <div class="text-h6 q-mb-md">
              <q-icon name="mdi-account-group" class="q-mr-sm" />
              {{ $t('adminSettings.friends.title') }}
            </div>
            <p class="text-grey-6 q-mb-md">
              {{ $t('adminSettings.friends.description') }}
            </p>

            <q-toggle
              v-model="friendsEnabled"
              :label="$t('adminSettings.friends.enableFriends')"
              color="primary"
              @update:model-value="updateFriendsSettings"
              :disable="saving"
            />

            <q-banner v-if="!friendsEnabled" class="bg-grey-9 q-mt-md" rounded>
              <template v-slot:avatar>
                <q-icon name="mdi-information" color="info" />
              </template>
              {{ $t('adminSettings.friends.disabledInfo') }}
            </q-banner>
          </q-card-section>
        </q-card>
      </div>

      <!-- Global Permission Defaults Card -->
      <div class="col-12">
        <q-card class="settings-card">
          <q-card-section>
            <div class="text-h6 q-mb-md">
              <q-icon name="mdi-shield-lock" class="q-mr-sm" />
              {{ $t('adminSettings.permissions.title') }}
            </div>
            <p class="text-grey-6 q-mb-md">
              {{ $t('adminSettings.permissions.description') }}
            </p>

            <q-form @submit="savePermissionDefaults" class="q-gutter-md">
              <!-- Library Access -->
              <div class="text-subtitle2">{{ $t('adminGroups.libraryAccess') }}</div>
              <q-select
                v-model="permDefaults.allowed_libraries"
                :options="libraryOptions"
                :label="$t('adminGroups.allowedLibraries')"
                outlined
                dense
                multiple
                use-chips
                :disable="saving"
              />

              <!-- Streaming Limits -->
              <div class="text-subtitle2 q-mt-md">{{ $t('adminGroups.streamingLimits') }}</div>
              <div class="row q-col-gutter-md">
                <div class="col-12 col-md-4">
                  <q-input
                    v-model.number="permDefaults.max_concurrent_streams"
                    :label="$t('adminGroups.maxConcurrentStreams')"
                    outlined
                    dense
                    type="number"
                    min="0"
                    :disable="saving"
                  />
                </div>
                <div class="col-12 col-md-4">
                  <q-input
                    v-model.number="permDefaults.max_game_streams"
                    :label="$t('adminGroups.maxGameStreams')"
                    outlined
                    dense
                    type="number"
                    min="0"
                    :disable="saving"
                  />
                </div>
                <div class="col-12 col-md-4">
                  <q-input
                    v-model.number="permDefaults.max_concurrent_transcodings"
                    :label="$t('adminGroups.maxConcurrentTranscodings')"
                    outlined
                    dense
                    type="number"
                    min="0"
                    :disable="saving"
                  />
                </div>
              </div>

              <!-- Quality Limits -->
              <div class="text-subtitle2 q-mt-md">{{ $t('adminGroups.qualityLimits') }}</div>
              <div class="row q-col-gutter-md">
                <div class="col-12 col-md-6">
                  <q-select
                    v-model="permDefaults.max_video_quality"
                    :options="videoQualityOptions"
                    :label="$t('adminGroups.maxVideoQuality')"
                    outlined
                    dense
                    emit-value
                    map-options
                    :disable="saving"
                  />
                </div>
                <div class="col-12 col-md-6">
                  <q-select
                    v-model="permDefaults.max_audio_quality"
                    :options="audioQualityOptions"
                    :label="$t('adminGroups.maxAudioQuality')"
                    outlined
                    dense
                    emit-value
                    map-options
                    :disable="saving"
                  />
                </div>
              </div>

              <q-btn
                type="submit"
                color="primary"
                :label="$t('adminSettings.permissions.save')"
                :loading="saving"
                class="q-mt-md"
              />
            </q-form>
          </q-card-section>
        </q-card>
      </div>

      <!-- Backup and Restore Card -->
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
    </div>
  </q-page>
</template>

<script setup>
import { computed, ref, onMounted } from 'vue'
import { useQuasar } from 'quasar'
import { useSettingsStore } from 'stores/settings'
import { useI18n } from 'vue-i18n'
import { logger } from 'src/utils/logger'
import {
  getFavoritesSettings,
  saveFavoritesSettings,
  getAutomationSettings,
  saveAutomationSettings,
  getOidcSettings,
  saveOidcSettings as saveOidcSettingsApi,
  getPermissionDefaults,
  savePermissionDefaults as savePermissionDefaultsApi,
  getSettingsBackup,
  getDatabaseBackup,
  restoreDatabaseBackup as restoreDatabaseBackupApi,
  restoreSettingsBackup as restoreSettingsBackupApi,
} from 'src/services/systemAdminService'
import {
  LIBRARY_OPTIONS,
  VIDEO_QUALITY_OPTIONS,
  buildAudioQualityOptions,
} from 'src/utils/userEditOptions'
const { t } = useI18n()
const $q = useQuasar()
const settingsStore = useSettingsStore()

const saving = ref(false)
const siteName = ref('pyrate.media')
const subscriptionsEnabled = ref(false)
const invitesEnabled = ref(true)
const friendsEnabled = ref(true)
const favoritesPermanent = ref(false)
const savingAutomation = ref(false)
const automation = ref({
  favorites_autodownload_enabled: false,
  upgrades_enabled: false,
  rss_sync_enabled: false,
  rss_min_interval_minutes: 15,
  upgrade_scan_batch_size: 25,
  max_concurrent_upgrade_downloads: 3,
})
const oidcSettings = ref({
  enabled: false,
  client_id: '',
  client_secret: '',
  client_secret_configured: false,
  server_metadata_url: '',
  redirect_uri: 'http://localhost:8000/api/auth/callback',
  post_logout_redirect_uri: 'http://localhost:8000',
  scopes: ['openid', 'profile', 'email'],
  auto_register_users: true,
  local_auth_enabled: true,
})
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

const permDefaults = ref({
  allowed_libraries: ['movies', 'series', 'games', 'books', 'music'],
  max_concurrent_streams: 3,
  max_game_streams: 1,
  max_video_quality: 'uhd',
  max_audio_quality: 'lossless',
  max_concurrent_transcodings: 2,
})

const libraryOptions = LIBRARY_OPTIONS

const videoQualityOptions = VIDEO_QUALITY_OPTIONS

const audioQualityOptions = buildAudioQualityOptions(t)

const oidcScopes = computed({
  get: () => (oidcSettings.value.scopes || []).join(' '),
  set: (value) => {
    oidcSettings.value.scopes = value.split(/\s+/).filter(Boolean)
  },
})

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

const loadSettings = async () => {
  try {
    await settingsStore.fetchSiteName()
    await settingsStore.fetchSubscriptionSettings()
    await settingsStore.fetchInviteSettings()
    await settingsStore.fetchFriendsSettings()

    siteName.value = settingsStore.getSiteName
    subscriptionsEnabled.value = settingsStore.subscriptionsEnabled
    invitesEnabled.value = settingsStore.invitesEnabled
    friendsEnabled.value = settingsStore.friendsEnabled

    try {
      const favData = await getFavoritesSettings()
      favoritesPermanent.value = favData.favorites_permanent
    } catch (error) {
      logger.error('Failed to load favorites settings:', error)
    }

    try {
      const autoData = await getAutomationSettings()
      automation.value = { ...automation.value, ...autoData }
    } catch (error) {
      logger.error('Failed to load automation settings:', error)
    }

    try {
      const oidcData = await getOidcSettings()
      oidcSettings.value = {
        ...oidcSettings.value,
        ...oidcData,
        client_secret: '',
      }
    } catch (error) {
      logger.error('Failed to load OIDC settings:', error)
    }
  } catch (error) {
    logger.error('Failed to load settings:', error)
  }

  try {
    const data = await getPermissionDefaults()
    permDefaults.value = data
  } catch (error) {
    logger.error('Failed to load permission defaults:', error)
  }
}

const updateFavoritesSettings = async () => {
  saving.value = true
  try {
    await saveFavoritesSettings({
      favorites_permanent: favoritesPermanent.value,
    })
  } catch (error) {
    logger.error('Failed to update favorites settings:', error)
    favoritesPermanent.value = !favoritesPermanent.value
  } finally {
    saving.value = false
  }
}

// Minimum allowed value for each numeric automation field. Used both for the
// per-input validation rules and the guard in updateAutomationSettings so we
// never PUT NaN/empty/out-of-range values to the scheduler.
const AUTOMATION_NUMERIC_MINIMUMS = {
  rss_min_interval_minutes: 1,
  upgrade_scan_batch_size: 1,
  max_concurrent_upgrade_downloads: 1,
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

const saveOidcSettings = async () => {
  saving.value = true
  try {
    const payload = { ...oidcSettings.value }
    delete payload.client_secret_configured
    if (!payload.client_secret) {
      delete payload.client_secret
    }
    const data = await saveOidcSettingsApi(payload)
    oidcSettings.value = {
      ...oidcSettings.value,
      ...data,
      client_secret: '',
    }
  } catch (error) {
    logger.error('Failed to save OIDC settings:', error)
  } finally {
    saving.value = false
  }
}

const updateFriendsSettings = async () => {
  saving.value = true
  try {
    await settingsStore.updateFriendsSettings(friendsEnabled.value)
  } catch (error) {
    logger.error('Failed to update friends settings:', error)
    friendsEnabled.value = settingsStore.friendsEnabled
  } finally {
    saving.value = false
  }
}

const savePermissionDefaults = async () => {
  saving.value = true
  try {
    const data = await savePermissionDefaultsApi(permDefaults.value)
    permDefaults.value = data
  } catch (error) {
    logger.error('Failed to save permission defaults:', error)
  } finally {
    saving.value = false
  }
}

const updateSystemSettings = async () => {
  saving.value = true
  try {
    await settingsStore.updateSiteName(siteName.value)
  } catch (error) {
    logger.error('Failed to update system settings:', error)
    // Revert the change
    siteName.value = settingsStore.getSiteName
  } finally {
    saving.value = false
  }
}

const updateSubscriptionSettings = async () => {
  saving.value = true
  try {
    await settingsStore.updateSubscriptionSettings(subscriptionsEnabled.value)
  } catch (error) {
    logger.error('Failed to update subscription settings:', error)
    // Revert the toggle
    subscriptionsEnabled.value = settingsStore.subscriptionsEnabled
  } finally {
    saving.value = false
  }
}

const updateInviteSettings = async () => {
  saving.value = true
  try {
    await settingsStore.updateInviteSettings(invitesEnabled.value)
  } catch (error) {
    logger.error('Failed to update invite settings:', error)
    // Revert the toggle
    invitesEnabled.value = settingsStore.invitesEnabled
  } finally {
    saving.value = false
  }
}

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
    await loadSettings()
  } catch (error) {
    logger.error('Failed to restore settings backup:', error)
    restoreError.value = error.response?.data?.detail || error.message
  } finally {
    restoreLoading.value = null
  }
}

onMounted(() => {
  loadSettings()
})
</script>

<style lang="scss" scoped>
.settings-page {
  max-width: 1200px;
  margin: 0 auto;
}

.settings-card {
  background: rgba(255, 255, 255, 0.05);
  backdrop-filter: blur(10px);
  border: 1px solid rgba(255, 255, 255, 0.1);
}
</style>
