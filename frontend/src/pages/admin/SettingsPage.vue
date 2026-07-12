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
      <OidcSettingsCard ref="oidcCardRef" />

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
      <FavoritesAutomationCard ref="automationCardRef" />

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
      <PermissionDefaultsCard ref="permCardRef" />

      <!-- Backup and Restore Card -->
      <BackupRestoreCard :reload-settings="reloadSettings" />
    </div>
  </q-page>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useSettingsStore } from 'stores/settings'
import { logger } from 'src/utils/logger'
import { getFavoritesSettings, saveFavoritesSettings } from 'src/services/systemAdminService'
import OidcSettingsCard from 'src/components/admin/settings/OidcSettingsCard.vue'
import PermissionDefaultsCard from 'src/components/admin/settings/PermissionDefaultsCard.vue'
import FavoritesAutomationCard from 'src/components/admin/settings/FavoritesAutomationCard.vue'
import BackupRestoreCard from 'src/components/admin/settings/BackupRestoreCard.vue'

const settingsStore = useSettingsStore()

const saving = ref(false)
const siteName = ref('pyrate.media')
const subscriptionsEnabled = ref(false)
const invitesEnabled = ref(true)
const friendsEnabled = ref(true)
const favoritesPermanent = ref(false)

const oidcCardRef = ref(null)
const automationCardRef = ref(null)
const permCardRef = ref(null)

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
  } catch (error) {
    logger.error('Failed to load settings:', error)
  }
}

// Reload the whole page after a settings restore, matching the original
// loadSettings() behavior that reloaded every card's data.
const reloadSettings = async () => {
  await loadSettings()
  await automationCardRef.value?.reload()
  await oidcCardRef.value?.reload()
  await permCardRef.value?.reload()
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
