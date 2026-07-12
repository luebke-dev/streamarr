<template>
  <q-page class="flex flex-center login-page" :style="backgroundStyle">
    <div v-if="backgroundTitle" class="bg-title-overlay">
      {{ backgroundTitle }}
    </div>
    <div class="q-pa-md" style="max-width: 800px; width: 100%">
      <div class="text-center q-mb-lg">
        <q-icon name="mdi-account-plus" size="4rem" color="primary" />
        <h4 class="q-mt-md q-mb-none text-white">{{ $t('registerPage.title') }}</h4>
        <p class="text-grey-5">{{ $t('registerPage.subtitle') }}</p>
      </div>

      <!-- Loading State -->
      <div v-if="validating" class="text-center q-py-xl">
        <q-spinner-dots size="3rem" color="primary" />
        <p class="q-mt-md text-grey-4">{{ $t('registerPage.validatingInvite') }}</p>
      </div>

      <!-- Invalid Invite -->
      <q-card v-else-if="inviteError" dark class="login-card q-pa-lg">
        <q-card-section class="text-center">
          <q-icon name="mdi-alert-circle" size="3rem" color="negative" />
          <h5 class="q-mt-md q-mb-sm text-negative">{{ $t('registerPage.invalidInvite') }}</h5>
          <p class="text-grey-4">{{ inviteError }}</p>
          <q-btn
            color="primary"
            :label="$t('registerPage.backToLogin')"
            @click="$router.push('/auth/login')"
            class="q-mt-md"
          />
        </q-card-section>
      </q-card>

      <!-- Check-your-email (registration succeeded, verification required) -->
      <q-card v-else-if="registeredEmail" dark class="login-card q-pa-lg">
        <q-card-section class="text-center">
          <q-icon name="mdi-email-check-outline" size="3rem" color="primary" />
          <h5 class="q-mt-md q-mb-sm text-white">{{ $t('registerPage.checkEmailTitle') }}</h5>
          <p class="text-grey-4">
            {{ $t('registerPage.checkEmailBody', { email: registeredEmail }) }}
          </p>
          <div class="row justify-center q-gutter-sm q-mt-md">
            <q-btn
              flat
              color="primary"
              :loading="resendLoading"
              :label="$t('registerPage.resendVerification')"
              @click="handleResend"
            />
            <q-btn
              color="primary"
              :label="$t('registerPage.backToLogin')"
              @click="$router.push('/auth/login')"
            />
          </div>
        </q-card-section>
      </q-card>

      <!-- Registration Form -->
      <q-card v-else dark class="login-card q-pa-lg">
        <q-card-section>
          <!-- Invite Info -->
          <FormBanner
            v-if="inviteInfo"
            type="success"
            icon="mdi-check-decagram"
            class="q-mb-lg"
            no-margin
          >
            <div>
              <strong>{{ $t('registerPage.invitedBy') }}</strong>
              <span v-if="inviteInfo.created_by">
                {{ inviteInfo.created_by.first_name }} {{ inviteInfo.created_by.last_name }}
              </span>
              <span v-else>{{ $t('registerPage.systemInvite') }}</span>
            </div>
            <div class="text-caption q-mt-xs">
              {{ $t('registerPage.expiresAt') }}: {{ formatDate(inviteInfo.expires_at) }}
            </div>
          </FormBanner>

          <!-- Error Banner -->
          <FormBanner v-if="error" :message="error" />

          <!-- Registration Form - Two Column Layout -->
          <q-form @submit="handleRegister">
            <div class="row q-col-gutter-lg">
              <!-- Left Column: Account Details -->
              <div class="col-12 col-sm-6">
                <div class="text-subtitle1 text-white q-mb-md">
                  <q-icon name="mdi-account" class="q-mr-sm" />
                  {{ $t('registerPage.accountDetails') }}
                </div>

                <div class="q-gutter-md">
                  <q-input
                    v-model="form.first_name"
                    :label="$t('registerPage.firstName')"
                    outlined
                    dark
                    :rules="[(val) => !!val || $t('registerPage.firstNameRequired')]"
                  />

                  <q-input
                    v-model="form.last_name"
                    :label="$t('registerPage.lastName')"
                    outlined
                    dark
                    :rules="[(val) => !!val || $t('registerPage.lastNameRequired')]"
                  />

                  <q-input
                    v-model="form.email"
                    type="email"
                    :label="$t('registerPage.email')"
                    outlined
                    dark
                    :rules="[
                      (val) => !!val || $t('registerPage.emailRequired'),
                      (val) => isValidEmail(val) || $t('registerPage.emailInvalid'),
                    ]"
                  />

                  <PasswordPairField
                    v-model="form.password"
                    v-model:confirm="form.password_confirm"
                    :password-label="$t('registerPage.password')"
                    :confirm-label="$t('registerPage.confirmPassword')"
                    :messages="{
                      required: $t('registerPage.passwordRequired'),
                      minLength: $t('registerPage.passwordMinLength'),
                      confirmRequired: $t('registerPage.confirmPasswordRequired'),
                      mismatch: $t('registerPage.passwordsMustMatch'),
                    }"
                  />
                </div>
              </div>

              <!-- Right Column: Display Name & Language -->
              <div class="col-12 col-sm-6">
                <div class="text-subtitle1 text-white q-mb-md">
                  <q-icon name="mdi-card-account-details" class="q-mr-sm" />
                  {{ $t('registerPage.profileSettings') }}
                </div>

                <div class="q-gutter-md">
                  <q-input
                    v-model="form.preferred_username"
                    :label="$t('registerPage.username')"
                    outlined
                    dark
                    :hint="$t('registerPage.usernameHint')"
                  />

                  <q-separator dark class="q-my-sm" />

                  <div class="text-subtitle2 text-white q-mb-xs">
                    <q-icon name="mdi-translate" class="q-mr-sm" />
                    {{ $t('registerPage.languageSettings') }}
                  </div>
                  <div class="text-caption text-grey-5 q-mb-sm">
                    {{ $t('registerPage.languageSettingsHint') }}
                  </div>

                  <q-select
                    v-model="form.ui_language"
                    :options="availableUiLanguages"
                    :label="$t('registerPage.uiLanguage')"
                    outlined
                    dark
                    emit-value
                    map-options
                    option-value="value"
                    option-label="label"
                  >
                    <template v-slot:option="scope">
                      <q-item v-bind="scope.itemProps">
                        <q-item-section avatar>
                          <span class="text-h6">{{ scope.opt.flag }}</span>
                        </q-item-section>
                        <q-item-section>{{ scope.opt.label }}</q-item-section>
                      </q-item>
                    </template>
                    <template v-slot:selected-item="scope">
                      <span v-if="scope.opt">{{ scope.opt.flag }} {{ scope.opt.label }}</span>
                    </template>
                  </q-select>

                  <q-select
                    v-model="form.audio_languages"
                    :options="availableMediaLanguages"
                    :label="$t('registerPage.audioLanguages')"
                    outlined
                    dark
                    emit-value
                    map-options
                    multiple
                    option-value="value"
                    option-label="label"
                  >
                    <template v-slot:option="scope">
                      <q-item v-bind="scope.itemProps">
                        <q-item-section avatar>
                          <span class="text-h6">{{ scope.opt.flag }}</span>
                        </q-item-section>
                        <q-item-section>{{ scope.opt.label }}</q-item-section>
                      </q-item>
                    </template>
                    <template v-slot:selected-item="scope">
                      <q-chip
                        dense
                        removable
                        @remove="removeAudioLanguage(scope.opt.value)"
                        class="q-ma-xs"
                      >
                        {{ scope.opt.flag }} {{ scope.opt.label }}
                      </q-chip>
                    </template>
                  </q-select>
                  <div class="text-caption text-grey-5 q-mt-xs">
                    {{ $t('registerPage.audioLanguagesHint') }}
                  </div>
                  <!-- Priority reorder list -->
                  <q-list v-if="form.audio_languages.length > 1" dense dark class="q-mt-sm">
                    <q-item
                      v-for="(lang, index) in form.audio_languages"
                      :key="lang"
                      dense
                      class="q-pa-none"
                    >
                      <q-item-section avatar style="min-width: 28px">
                        <q-badge color="primary" :label="index + 1" />
                      </q-item-section>
                      <q-item-section>
                        {{ getMediaLanguageLabel(lang) }}
                      </q-item-section>
                      <q-item-section side>
                        <div class="row no-wrap">
                          <q-btn
                            flat
                            dense
                            round
                            icon="mdi-arrow-up"
                            size="sm"
                            :disable="index === 0"
                            @click="moveAudioLanguage(index, -1)"
                          />
                          <q-btn
                            flat
                            dense
                            round
                            icon="mdi-arrow-down"
                            size="sm"
                            :disable="index === form.audio_languages.length - 1"
                            @click="moveAudioLanguage(index, 1)"
                          />
                        </div>
                      </q-item-section>
                    </q-item>
                  </q-list>

                  <q-select
                    v-model="form.subtitle_language"
                    :options="availableSubtitleLanguages"
                    :label="$t('registerPage.subtitleLanguage')"
                    outlined
                    dark
                    emit-value
                    map-options
                    option-value="value"
                    option-label="label"
                    clearable
                    :hint="$t('registerPage.subtitleHint')"
                  >
                    <template v-slot:option="scope">
                      <q-item v-bind="scope.itemProps">
                        <q-item-section avatar>
                          <span class="text-h6">{{ scope.opt.flag }}</span>
                        </q-item-section>
                        <q-item-section>{{ scope.opt.label }}</q-item-section>
                      </q-item>
                    </template>
                    <template v-slot:selected-item="scope">
                      <span v-if="scope.opt">{{ scope.opt.flag }} {{ scope.opt.label }}</span>
                    </template>
                  </q-select>
                </div>
              </div>
            </div>

            <q-btn
              type="submit"
              color="primary"
              size="lg"
              class="full-width q-mt-lg"
              :loading="loading"
              icon="mdi-account-plus"
              :label="$t('registerPage.createAccount')"
            />
          </q-form>
        </q-card-section>
      </q-card>

      <div class="text-center q-mt-lg">
        <q-btn
          flat
          color="grey-4"
          icon="mdi-login"
          :label="$t('registerPage.alreadyHaveAccount')"
          @click="$router.push('/auth/login')"
        />
      </div>
    </div>
  </q-page>
</template>

<script>
import { defineComponent, ref, onMounted } from 'vue'
import { useQuasar } from 'quasar'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useBackgroundRotation } from 'src/composables/useBackgroundRotation'
import * as authService from 'src/services/authService'
import {
  MEDIA_LANGUAGES,
  SUBTITLE_LANGUAGES,
  UI_LANGUAGES,
  getMediaLanguageLabel,
} from 'src/utils/mediaLanguages'
import { logger } from 'src/utils/logger'
import PasswordPairField from 'src/components/PasswordPairField.vue'
import FormBanner from 'src/components/FormBanner.vue'

export default defineComponent({
  name: 'RegisterPage',
  components: { PasswordPairField, FormBanner },
  setup() {
    const route = useRoute()
    const { t } = useI18n()
    const $q = useQuasar()

    const { backgroundStyle, backgroundTitle } = useBackgroundRotation()

    const validating = ref(true)
    const loading = ref(false)
    const error = ref('')
    const inviteError = ref('')
    const inviteToken = ref('')
    const inviteInfo = ref(null)
    // Set after a successful registration → shows the "check your email" panel.
    const registeredEmail = ref('')
    const resendLoading = ref(false)

    const form = ref({
      first_name: '',
      last_name: '',
      email: '',
      preferred_username: '',
      password: '',
      password_confirm: '',
      ui_language: 'en-US',
      audio_languages: ['en'],
      subtitle_language: null,
    })

    const availableUiLanguages = UI_LANGUAGES
    const availableMediaLanguages = MEDIA_LANGUAGES
    const availableSubtitleLanguages = SUBTITLE_LANGUAGES

    const removeAudioLanguage = (code) => {
      form.value.audio_languages = form.value.audio_languages.filter((l) => l !== code)
    }

    const moveAudioLanguage = (index, direction) => {
      const arr = [...form.value.audio_languages]
      const newIndex = index + direction
      if (newIndex < 0 || newIndex >= arr.length) return
      ;[arr[index], arr[newIndex]] = [arr[newIndex], arr[index]]
      form.value.audio_languages = arr
    }

    const isValidEmail = (email) => {
      const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
      return emailRegex.test(email)
    }

    const formatDate = (dateString) => {
      if (!dateString) return '-'
      return new Date(dateString).toLocaleString()
    }

    const validateInvite = async () => {
      // Get token from URL query or route params
      const token = route.query.invite || route.params.token

      if (!token) {
        inviteError.value = t('registerPage.noInviteToken')
        validating.value = false
        return
      }

      inviteToken.value = token

      try {
        inviteInfo.value = await authService.validateInvite(token)
      } catch (err) {
        logger.error('Invite validation error:', err)
        inviteError.value = err.response?.data?.detail || t('registerPage.inviteValidationFailed')
      } finally {
        validating.value = false
      }
    }

    const handleRegister = async () => {
      try {
        loading.value = true
        error.value = ''

        const response = await authService.registerWithInvite({
          invite_token: inviteToken.value,
          email: form.value.email,
          first_name: form.value.first_name,
          last_name: form.value.last_name,
          preferred_username: form.value.preferred_username || null,
          password: form.value.password,
          ui_language: form.value.ui_language,
          audio_languages: form.value.audio_languages,
          subtitle_language: form.value.subtitle_language,
        })

        // Registration is a hard email gate: no session is created. Show the
        // "check your email" panel instead of logging in.
        registeredEmail.value = response?.email || form.value.email
      } catch (err) {
        logger.error('Registration error:', err)
        error.value = err.response?.data?.detail || t('registerPage.registrationFailed')
      } finally {
        loading.value = false
      }
    }

    const handleResend = async () => {
      if (!registeredEmail.value) return
      try {
        resendLoading.value = true
        await authService.resendVerification(registeredEmail.value)
        $q.notify({ type: 'positive', message: t('registerPage.verificationResent') })
      } catch (err) {
        logger.error('Resend verification failed:', err)
        $q.notify({ type: 'negative', message: t('registerPage.registrationFailed') })
      } finally {
        resendLoading.value = false
      }
    }

    onMounted(async () => {
      validateInvite()
    })

    return {
      backgroundStyle,
      validating,
      loading,
      error,
      inviteError,
      inviteInfo,
      form,
      registeredEmail,
      resendLoading,
      isValidEmail,
      formatDate,
      handleRegister,
      handleResend,
      backgroundTitle,
      availableUiLanguages,
      availableMediaLanguages,
      availableSubtitleLanguages,
      getMediaLanguageLabel,
      removeAudioLanguage,
      moveAudioLanguage,
    }
  },
})
</script>

<style lang="scss" scoped>
@import 'src/css/auth-layout';
</style>
