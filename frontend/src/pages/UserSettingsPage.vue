<template>
  <q-page class="q-pa-md">
    <div style="max-width: 900px; margin: 0 auto">
      <!-- Header -->
      <div class="row items-center q-mb-lg">
        <div class="col">
          <div class="text-h4 text-weight-bold">
            <q-icon name="mdi-cog" class="q-mr-sm" />
            {{ $t('settings.title') }}
          </div>
          <div class="text-subtitle1 text-grey-6 q-mt-xs">
            {{ $t('settings.subtitle') }}
          </div>
        </div>
      </div>

      <!-- Profile Section -->
      <div class="row q-col-gutter-md q-mb-lg">
        <!-- Profile Information -->
        <div class="col-12 col-md-8">
          <q-card flat bordered>
            <q-card-section>
              <div class="text-h6 q-mb-md">
                <q-icon name="mdi-account-edit" class="q-mr-sm" />
                {{ $t('settings.personalInfo') }}
              </div>

              <q-form @submit="updateProfile" class="q-gutter-md">
                <div class="row q-col-gutter-md">
                  <div class="col-12 col-sm-6">
                    <q-input
                      v-model="profileForm.first_name"
                      :label="$t('settings.firstName')"
                      outlined
                      dense
                      :loading="updating"
                      :disable="updating"
                      :rules="[(val) => !!val || $t('settings.firstNameRequired')]"
                    >
                      <template v-slot:prepend>
                        <q-icon name="mdi-account" />
                      </template>
                    </q-input>
                  </div>

                  <div class="col-12 col-sm-6">
                    <q-input
                      v-model="profileForm.last_name"
                      :label="$t('settings.lastName')"
                      outlined
                      dense
                      :loading="updating"
                      :disable="updating"
                      :rules="[(val) => !!val || $t('settings.lastNameRequired')]"
                    >
                      <template v-slot:prepend>
                        <q-icon name="mdi-account" />
                      </template>
                    </q-input>
                  </div>
                </div>

                <q-input
                  v-model="profileForm.email"
                  :label="$t('settings.email')"
                  type="email"
                  outlined
                  dense
                  :loading="updating"
                  :disable="updating || isOIDCUser"
                  :rules="[(val) => !!val || $t('settings.emailRequired')]"
                  :hint="isOIDCUser ? $t('settings.emailReadonly') : ''"
                >
                  <template v-slot:prepend>
                    <q-icon name="mdi-email" />
                  </template>
                </q-input>

                <q-input
                  v-model="profileForm.preferred_username"
                  :label="$t('settings.username')"
                  outlined
                  dense
                  :loading="updating"
                  :disable="updating"
                  :hint="$t('settings.usernameHint')"
                >
                  <template v-slot:prepend>
                    <q-icon name="mdi-at" />
                  </template>
                </q-input>

                <div class="row q-gutter-sm q-mt-md">
                  <q-btn
                    type="submit"
                    color="primary"
                    :label="$t('settings.updateProfile')"
                    :loading="updating"
                    :disable="updating || !hasProfileChanges"
                    icon="mdi-content-save"
                    unelevated
                  />
                  <q-btn
                    flat
                    :label="$t('common.reset')"
                    color="grey-7"
                    @click="resetProfileForm"
                    :disable="updating"
                  />
                </div>
              </q-form>
            </q-card-section>
          </q-card>
        </div>

        <!-- Account Info Sidebar -->
        <div class="col-12 col-md-4">
          <q-card flat bordered>
            <q-card-section>
              <div class="text-h6 q-mb-md">
                <q-icon name="mdi-information" class="q-mr-sm" />
                {{ $t('settings.accountInfo') }}
              </div>

              <q-list dense>
                <q-item>
                  <q-item-section>
                    <q-item-label caption>{{ $t('settings.userId') }}</q-item-label>
                    <q-item-label class="text-caption text-grey-7 q-mt-xs">
                      {{ userInfo.guid || '-' }}
                    </q-item-label>
                  </q-item-section>
                </q-item>

                <q-item>
                  <q-item-section>
                    <q-item-label caption>{{ $t('settings.accountStatus') }}</q-item-label>
                    <q-item-label class="q-mt-xs">
                      <q-badge
                        :color="userInfo.is_active ? 'green' : 'grey'"
                        :label="
                          userInfo.is_active ? $t('settings.active') : $t('settings.inactive')
                        "
                      />
                    </q-item-label>
                  </q-item-section>
                </q-item>

                <q-item v-if="userInfo.is_superuser">
                  <q-item-section>
                    <q-item-label caption>{{ $t('settings.administrator') }}</q-item-label>
                    <q-item-label class="q-mt-xs">
                      <q-badge color="primary" :label="$t('settings.adminRights')" />
                    </q-item-label>
                  </q-item-section>
                </q-item>

                <q-item v-if="userInfo.oidc_sub">
                  <q-item-section>
                    <q-item-label caption>{{ $t('settings.authentication') }}</q-item-label>
                    <q-item-label class="q-mt-xs">
                      <q-badge color="blue" :label="$t('settings.oidcProvider')" />
                    </q-item-label>
                  </q-item-section>
                </q-item>

                <q-item>
                  <q-item-section>
                    <q-item-label caption>{{ $t('settings.registeredSince') }}</q-item-label>
                    <q-item-label class="q-mt-xs">
                      {{ formatDate(userInfo.created_at) }}
                    </q-item-label>
                  </q-item-section>
                </q-item>
              </q-list>
            </q-card-section>
          </q-card>
        </div>
      </div>

      <!-- Language Section -->
      <div class="q-mb-lg">
        <q-card flat bordered>
          <q-card-section>
            <div class="text-h6 q-mb-sm">
              <q-icon name="mdi-translate" class="q-mr-sm" />
              {{ $t('settings.language') }}
            </div>
            <div class="text-body2 text-grey-6 q-mb-lg">
              {{ $t('settings.languageDescription') }}
            </div>

            <div class="q-gutter-md">
              <!-- UI Language -->
              <div>
                <div class="text-subtitle2 q-mb-sm">
                  <q-icon name="mdi-web" class="q-mr-xs" />
                  {{ $t('settings.uiLanguage') }}
                </div>
                <q-select
                  v-model="selectedUiLanguage"
                  :options="availableUiLanguages"
                  option-value="value"
                  option-label="label"
                  emit-value
                  map-options
                  outlined
                  dense
                  :loading="updatingLanguages"
                  @update:model-value="updateLanguageSettings"
                >
                  <template v-slot:prepend>
                    <q-icon name="mdi-web" />
                  </template>
                  <template v-slot:selected-item="scope">
                    <div class="row items-center q-gutter-sm">
                      <span class="text-h6">{{ scope.opt.flag }}</span>
                      <span>{{ scope.opt.label }}</span>
                    </div>
                  </template>
                  <template v-slot:option="scope">
                    <q-item v-bind="scope.itemProps">
                      <q-item-section avatar>
                        <span class="text-h6">{{ scope.opt.flag }}</span>
                      </q-item-section>
                      <q-item-section>
                        <q-item-label>{{ scope.opt.label }}</q-item-label>
                      </q-item-section>
                    </q-item>
                  </template>
                </q-select>
              </div>

              <!-- Audio Languages -->
              <div>
                <div class="text-subtitle2 q-mb-sm">
                  <q-icon name="mdi-volume-high" class="q-mr-xs" />
                  {{ $t('settings.audioLanguages') }}
                </div>
                <LanguagePrioritySelector
                  v-model="selectedAudioLanguages"
                  :options="availableMediaLanguages"
                  :hint="$t('settings.audioLanguagesHint')"
                  :loading="updatingLanguages"
                  prepend-icon="mdi-volume-high"
                  @change="updateLanguageSettings"
                />
              </div>

              <!-- Subtitle Language -->
              <div>
                <div class="text-subtitle2 q-mb-sm">
                  <q-icon name="mdi-closed-caption" class="q-mr-xs" />
                  {{ $t('settings.subtitleLanguage') }}
                </div>
                <q-select
                  v-model="selectedSubtitleLanguage"
                  :options="availableSubtitleLanguages"
                  option-value="value"
                  option-label="label"
                  emit-value
                  map-options
                  outlined
                  dense
                  clearable
                  :loading="updatingLanguages"
                  @update:model-value="updateLanguageSettings"
                >
                  <template v-slot:prepend>
                    <q-icon name="mdi-closed-caption" />
                  </template>
                  <template v-slot:selected-item="scope">
                    <div class="row items-center q-gutter-sm">
                      <span class="text-h6">{{ scope.opt.flag }}</span>
                      <span>{{ scope.opt.label }}</span>
                    </div>
                  </template>
                  <template v-slot:option="scope">
                    <q-item v-bind="scope.itemProps">
                      <q-item-section avatar>
                        <span class="text-h6">{{ scope.opt.flag }}</span>
                      </q-item-section>
                      <q-item-section>
                        <q-item-label>{{ scope.opt.label }}</q-item-label>
                      </q-item-section>
                    </q-item>
                  </template>
                </q-select>
                <div class="text-caption text-grey-6 q-mt-xs q-ml-sm">
                  {{ $t('settings.subtitleHint') }}
                </div>
              </div>
            </div>
          </q-card-section>
        </q-card>
      </div>

      <!-- Parental Control Section -->
      <div class="q-mb-lg">
        <q-card flat bordered>
          <q-card-section>
            <div class="text-h6 q-mb-sm">
              <q-icon name="mdi-shield-account" class="q-mr-sm" />
              {{ $t('settings.parentalControl', 'Parental control') }}
            </div>
            <div class="text-body2 text-grey-6 q-mb-md">
              {{
                $t(
                  'settings.parentalControlDescription',
                  'Hide and block movies / shows whose age rating is above this threshold. Unrated media is always visible.',
                )
              }}
            </div>
            <q-select
              v-model="selectedParentalMaxAge"
              :options="parentalAgeOptions"
              option-value="value"
              option-label="label"
              emit-value
              map-options
              outlined
              dense
              :loading="updatingParental"
              @update:model-value="updateParentalControl"
            >
              <template v-slot:prepend>
                <q-icon name="mdi-shield-account" />
              </template>
            </q-select>
          </q-card-section>
        </q-card>
      </div>

      <!-- Playback Preferences Section -->
      <PlaybackSection />

      <!-- Gaming Preferences Section -->
      <GamingSection />

      <!-- Devices Section -->
      <DevicesSection @current-device-removed="onCurrentDeviceRemoved" />

      <!-- Security Section -->
      <div class="q-mb-lg">
        <q-card flat bordered class="q-mb-md">
          <q-card-section>
            <div class="text-h6 q-mb-md">
              <q-icon name="mdi-lock" class="q-mr-sm" />
              {{ $t('settings.changePassword') }}
            </div>

            <div class="text-body2 text-grey-6 q-mb-md">
              {{ $t('settings.changePasswordDescription') }}
            </div>

            <FormBanner
              v-if="isOIDCUser"
              type="info"
              :message="$t('settings.oidcPasswordInfo')"
              no-margin
              class="q-mb-md"
            />

            <q-form v-else @submit="changePassword" class="q-gutter-md">
              <q-input
                v-model="passwordForm.currentPassword"
                :type="showCurrentPassword ? 'text' : 'password'"
                :label="$t('settings.currentPassword')"
                outlined
                :rules="[(val) => !!val || $t('settings.currentPasswordRequired')]"
              >
                <template v-slot:append>
                  <q-icon
                    :name="showCurrentPassword ? 'mdi-eye-off' : 'mdi-eye'"
                    class="cursor-pointer"
                    @click="showCurrentPassword = !showCurrentPassword"
                  />
                </template>
              </q-input>

              <q-input
                v-model="passwordForm.newPassword"
                :type="showNewPassword ? 'text' : 'password'"
                :label="$t('settings.newPassword')"
                outlined
                :rules="[
                  (val) => !!val || $t('settings.newPasswordRequired'),
                  (val) => val.length >= 8 || $t('settings.passwordMinLength'),
                ]"
              >
                <template v-slot:append>
                  <q-icon
                    :name="showNewPassword ? 'mdi-eye-off' : 'mdi-eye'"
                    class="cursor-pointer"
                    @click="showNewPassword = !showNewPassword"
                  />
                </template>
              </q-input>

              <q-input
                v-model="passwordForm.confirmPassword"
                :type="showNewPassword ? 'text' : 'password'"
                :label="$t('settings.confirmPassword')"
                outlined
                :rules="[
                  (val) => !!val || $t('settings.confirmPasswordRequired'),
                  (val) => val === passwordForm.newPassword || $t('settings.passwordMismatch'),
                ]"
              />

              <q-btn
                type="submit"
                color="primary"
                icon="mdi-lock-reset"
                :label="$t('settings.changePasswordBtn')"
                :loading="changingPassword"
              />
            </q-form>
          </q-card-section>
        </q-card>

        <!-- Danger Zone -->
        <q-card flat bordered class="border-negative">
          <q-card-section class="bg-negative text-white">
            <div class="text-h6">
              <q-icon name="mdi-alert" class="q-mr-sm" />
              {{ $t('settings.dangerZone') }}
            </div>
          </q-card-section>
          <q-card-section>
            <div class="text-body2 text-grey-7 q-mb-md">
              {{ $t('settings.dangerZoneDescription') }}
            </div>
            <q-btn
              outline
              color="negative"
              icon="mdi-delete-forever"
              :label="$t('settings.deleteAccount')"
              @click="confirmDeleteAccount"
            />
          </q-card-section>
        </q-card>
      </div>

      <!-- Connection Section (desktop app only) -->
      <div v-if="isDesktop" class="q-mb-lg">
        <q-card flat bordered>
          <q-card-section>
            <div class="text-h6 q-mb-md">
              <q-icon name="mdi-server-network" class="q-mr-sm" />
              {{ $t('settings.serverConnection') }}
            </div>
            <p class="text-body2 text-grey-6 q-mb-md">
              {{ $t('settings.serverConnectionHint') }}
            </p>
            <q-input
              v-model="desktopServerUrl"
              :label="$t('settings.serverUrl')"
              outlined
              placeholder="http://localhost:8000"
              class="q-mb-md"
            >
              <template v-slot:prepend>
                <q-icon name="mdi-web" />
              </template>
            </q-input>
            <q-btn
              color="primary"
              icon="mdi-content-save"
              :label="$t('settings.saveAndReconnect')"
              @click="saveDesktopServerUrl"
            />
          </q-card-section>
        </q-card>
      </div>
    </div>
  </q-page>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { Dialog } from 'quasar'
import { useI18n } from 'vue-i18n'
import { loadLocale } from 'src/i18n'
import { useAuthStore } from 'src/stores/auth'
import { useSettingsStore } from 'src/stores/settings'
import * as settingsService from 'src/services/settingsService'
import { getServerUrl, setServerUrl } from 'src/utils/authStorage'
import { isDesktopApp, reloadDesktopWindow } from 'src/utils/desktopPlatform'
import { logger } from 'src/utils/logger'
import FormBanner from 'src/components/FormBanner.vue'
import LanguagePrioritySelector from 'src/components/LanguagePrioritySelector.vue'
import DevicesSection from 'src/components/user-settings/DevicesSection.vue'
import PlaybackSection from 'src/components/user-settings/PlaybackSection.vue'
import GamingSection from 'src/components/user-settings/GamingSection.vue'
import { MEDIA_LANGUAGES, SUBTITLE_LANGUAGES, UI_LANGUAGES } from 'src/utils/mediaLanguages'

const { t, locale, setLocaleMessage, availableLocales } = useI18n({ useScope: 'global' })
const authStore = useAuthStore()
const settingsStore = useSettingsStore()

const isDesktop = isDesktopApp()
const desktopServerUrl = ref(isDesktop ? getServerUrl('http://localhost:8000') : '')

// State
const userInfo = ref({})
const updating = ref(false)
const updatingLanguages = ref(false)
const originalProfileData = ref({})

// Password change state
const changingPassword = ref(false)
const showCurrentPassword = ref(false)
const showNewPassword = ref(false)
const passwordForm = ref({
  currentPassword: '',
  newPassword: '',
  confirmPassword: '',
})

// Devices state — handled by DevicesSection component
// Playback preferences — handled by PlaybackSection component
// Gaming preferences — handled by GamingSection component

// Language settings
const selectedUiLanguage = ref('en-US')
const selectedAudioLanguages = ref(['en'])
const selectedSubtitleLanguage = ref(null)
const selectedParentalMaxAge = ref(null)
const updatingParental = ref(false)

const parentalAgeOptions = [
  { value: null, label: 'No limit' },
  { value: 0, label: 'Everyone (0+)' },
  { value: 6, label: 'Ages 6+' },
  { value: 12, label: 'Ages 12+' },
  { value: 16, label: 'Ages 16+' },
  { value: 18, label: 'Adults only (18+)' },
]

const availableUiLanguages = UI_LANGUAGES
const availableMediaLanguages = MEDIA_LANGUAGES
const availableSubtitleLanguages = SUBTITLE_LANGUAGES

// Profile form

const profileForm = ref({
  first_name: '',
  last_name: '',
  email: '',
  preferred_username: '',
})

// Computed
const isOIDCUser = computed(() => {
  return !!userInfo.value.oidc_sub
})

const hasProfileChanges = computed(() => {
  return (
    profileForm.value.first_name !== originalProfileData.value.first_name ||
    profileForm.value.last_name !== originalProfileData.value.last_name ||
    profileForm.value.email !== originalProfileData.value.email ||
    profileForm.value.preferred_username !== originalProfileData.value.preferred_username
  )
})

// Language methods
async function updateLanguageSettings() {
  updatingLanguages.value = true
  try {
    await authStore.updateLanguageSettings({
      ui_language: selectedUiLanguage.value,
      audio_languages: selectedAudioLanguages.value,
      subtitle_language: selectedSubtitleLanguage.value,
    })

    if (settingsStore.availableLanguages.some((l) => l.value === selectedUiLanguage.value)) {
      settingsStore.setLanguage(selectedUiLanguage.value)
      const target = selectedUiLanguage.value
      if (!availableLocales.includes(target)) {
        const loaded = await loadLocale(target)
        if (loaded) setLocaleMessage(target, loaded)
      }
      locale.value = target
    }
  } catch (error) {
    logger.error('Failed to update language settings:', error)
  } finally {
    updatingLanguages.value = false
  }
}

async function updateParentalControl(value) {
  updatingParental.value = true
  try {
    await settingsService.updateParentalControl(value)
  } catch (error) {
    logger.error('Failed to update parental control:', error)
  } finally {
    updatingParental.value = false
  }
}

// Playback / Gaming preferences — handled by PlaybackSection / GamingSection components

// Change password
async function changePassword() {
  changingPassword.value = true
  try {
    await settingsService.changeUserPassword(userInfo.value.guid, {
      current_password: passwordForm.value.currentPassword,
      new_password: passwordForm.value.newPassword,
    })

    // Reset form
    passwordForm.value = { currentPassword: '', newPassword: '', confirmPassword: '' }
    showCurrentPassword.value = false
    showNewPassword.value = false
  } catch (error) {
    logger.error('Error changing password:', error)
  } finally {
    changingPassword.value = false
  }
}

// Methods
async function loadUserInfo() {
  try {
    const data = await settingsService.getCurrentUser()
    userInfo.value = data

    // Initialize profile form
    profileForm.value = {
      first_name: data.first_name || '',
      last_name: data.last_name || '',
      email: data.email || '',
      preferred_username: data.preferred_username || '',
    }

    // Store original data for comparison
    originalProfileData.value = { ...profileForm.value }

    // Load language settings from user data
    selectedUiLanguage.value = data.ui_language || 'en-US'
    selectedAudioLanguages.value =
      data.audio_languages || (data.audio_language ? [data.audio_language] : ['en'])
    selectedSubtitleLanguage.value = data.subtitle_language || null

    try {
      const parentalData = await settingsService.getParentalControl()
      selectedParentalMaxAge.value = parentalData?.parental_max_age ?? null
    } catch (err) {
      logger.warn('Failed to load parental-control setting:', err)
    }

    // Playback / Gaming preferences are loaded by their own section components
  } catch (error) {
    logger.error('Failed to load user info:', error)
  }
}

async function updateProfile() {
  updating.value = true

  try {
    const data = await settingsService.updateCurrentUser(profileForm.value)

    // Update stores
    authStore.user = data
    originalProfileData.value = { ...profileForm.value }
  } catch (error) {
    logger.error('Failed to update profile:', error)
  } finally {
    updating.value = false
  }
}

function resetProfileForm() {
  profileForm.value = { ...originalProfileData.value }
}

// Device management — delegated to DevicesSection component
function onCurrentDeviceRemoved() {
  setTimeout(() => {
    authStore.logout()
  }, 2000)
}

function formatDate(dateString) {
  if (!dateString) return t('settings.never')
  const date = new Date(dateString)
  return date.toLocaleString(locale.value, {
    dateStyle: 'medium',
    timeStyle: 'short',
  })
}

function confirmDeleteAccount() {
  Dialog.create({
    title: t('settings.deleteAccountTitle'),
    message: t('settings.deleteAccountMessage'),
    cancel: {
      flat: true,
      label: t('common.cancel'),
    },
    ok: {
      flat: true,
      label: t('settings.deleteAccountConfirm'),
      color: 'negative',
    },
    persistent: true,
  }).onOk(() => {})
}

// Lifecycle
onMounted(() => {
  loadUserInfo()
})

function saveDesktopServerUrl() {
  const url = desktopServerUrl.value.replace(/\/$/, '')
  if (!url.startsWith('http://') && !url.startsWith('https://')) {
    return
  }
  setServerUrl(url)
  reloadDesktopWindow()
}
</script>

<style scoped>
.device-card {
  transition: all 0.3s ease;
}

.device-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
}

.border-negative {
  border: 1px solid var(--q-negative);
}
</style>
