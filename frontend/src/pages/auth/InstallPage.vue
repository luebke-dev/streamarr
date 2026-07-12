<template>
  <q-page class="flex flex-center login-page" :style="backgroundStyle">
    <div v-if="backgroundTitle" class="bg-title-overlay">
      {{ backgroundTitle }}
    </div>

    <div class="install-wrapper q-pa-md">
      <div class="text-center q-mb-lg">
        <q-icon name="mdi-rocket-launch-outline" size="4rem" color="primary" />
        <h4 class="q-mt-md q-mb-none text-white">{{ $t('installPage.title') }}</h4>
        <p class="text-grey-5">{{ $t('installPage.subtitle') }}</p>
      </div>

      <!-- Loading -->
      <div v-if="checkingStatus" class="text-center q-py-xl">
        <q-spinner-dots size="3rem" color="primary" />
        <p class="q-mt-md text-grey-4">{{ $t('installPage.checkingStatus') }}</p>
      </div>

      <!-- Already installed -->
      <q-card v-else-if="alreadyInstalled" dark class="login-card q-pa-lg">
        <q-card-section class="text-center">
          <q-icon name="mdi-check-circle" size="3rem" color="positive" />
          <h5 class="q-mt-md q-mb-sm text-positive">{{ $t('installPage.alreadyInstalled') }}</h5>
          <p class="text-grey-4">{{ $t('installPage.alreadyInstalledHint') }}</p>
          <q-btn
            color="primary"
            :label="$t('installPage.goToLogin')"
            @click="$router.push('/auth/login')"
            class="q-mt-md"
            icon="mdi-login"
            unelevated
          />
        </q-card-section>
      </q-card>

      <!-- Install form -->
      <q-card v-else dark class="login-card q-pa-lg">
        <q-card-section>
          <FormBanner v-if="error" :message="error" />

          <q-stepper
            v-model="step"
            vertical
            flat
            color="primary"
            dark
            animated
            class="install-stepper"
          >
            <!-- Step 1: Admin -->
            <q-step
              :name="1"
              :title="$t('installPage.step1Title')"
              :caption="$t('installPage.step1Caption')"
              icon="mdi-account-star"
              :done="step > 1"
            >
              <div class="q-gutter-md">
                <div class="row q-col-gutter-md">
                  <q-input
                    v-model="form.first_name"
                    :label="$t('installPage.firstName')"
                    outlined
                    dark
                    dense
                    :rules="[(val) => !!val || $t('installPage.firstNameRequired')]"
                    class="col-12 col-sm"
                  >
                    <template v-slot:prepend>
                      <q-icon name="mdi-account" />
                    </template>
                  </q-input>
                  <q-input
                    v-model="form.last_name"
                    :label="$t('installPage.lastName')"
                    outlined
                    dark
                    dense
                    :rules="[(val) => !!val || $t('installPage.lastNameRequired')]"
                    class="col-12 col-sm"
                  >
                    <template v-slot:prepend>
                      <q-icon name="mdi-account-outline" />
                    </template>
                  </q-input>
                </div>

                <q-input
                  v-model="form.email"
                  type="email"
                  :label="$t('installPage.email')"
                  outlined
                  dark
                  dense
                  :rules="[
                    (val) => !!val || $t('installPage.emailRequired'),
                    (val) => isValidEmail(val) || $t('installPage.emailInvalid'),
                  ]"
                >
                  <template v-slot:prepend>
                    <q-icon name="mdi-at" />
                  </template>
                </q-input>

                <PasswordPairField
                  v-model="form.password"
                  v-model:confirm="form.password_confirm"
                  :password-label="$t('installPage.password')"
                  :confirm-label="$t('installPage.confirmPassword')"
                  :dark="true"
                  dense
                  require-complexity
                  :messages="{
                    required: $t('installPage.passwordRequired'),
                    minLength: $t('installPage.passwordMinLength'),
                    complexity: $t('installPage.passwordComplexity'),
                    confirmRequired: $t('installPage.confirmPasswordRequired'),
                    mismatch: $t('installPage.passwordsMustMatch'),
                  }"
                />
              </div>

              <q-stepper-navigation>
                <q-btn
                  unelevated
                  @click="validateStep1"
                  color="primary"
                  :label="$t('installPage.continue')"
                  icon-right="mdi-arrow-right"
                />
              </q-stepper-navigation>
            </q-step>

            <!-- Step 2: Site -->
            <q-step
              :name="2"
              :title="$t('installPage.step2Title')"
              :caption="$t('installPage.step2Caption')"
              icon="mdi-web"
              :done="step > 2"
            >
              <div class="q-gutter-md">
                <q-input
                  v-model="form.site_name"
                  :label="$t('installPage.siteName')"
                  outlined
                  dark
                  dense
                  :hint="$t('installPage.siteNameHint')"
                >
                  <template v-slot:prepend>
                    <q-icon name="mdi-web" />
                  </template>
                </q-input>

                <q-select
                  v-model="form.locale"
                  :options="localeOptions"
                  :label="$t('installPage.language')"
                  outlined
                  dark
                  dense
                  emit-value
                  map-options
                  :hint="$t('installPage.languageHint')"
                  popup-content-class="bg-grey-10 text-white"
                >
                  <template v-slot:prepend>
                    <q-icon name="mdi-translate" />
                  </template>
                </q-select>
              </div>

              <q-stepper-navigation>
                <q-btn
                  unelevated
                  @click="step = 3"
                  color="primary"
                  :label="$t('installPage.continue')"
                  icon-right="mdi-arrow-right"
                />
                <q-btn
                  flat
                  @click="step = 1"
                  color="primary"
                  :label="$t('installPage.back')"
                  icon="mdi-arrow-left"
                  class="q-ml-sm"
                />
              </q-stepper-navigation>
            </q-step>

            <!-- Step 3: Confirm -->
            <q-step
              :name="3"
              :title="$t('installPage.step3Title')"
              :caption="$t('installPage.step3Caption')"
              icon="mdi-check-all"
            >
              <div class="q-gutter-md">
                <FormBanner
                  type="info"
                  icon="mdi-information"
                  :message="$t('installPage.confirmationInfo')"
                  no-margin
                />

                <q-list dark separator class="summary-list rounded-borders">
                  <q-item>
                    <q-item-section avatar>
                      <q-icon name="mdi-account" color="primary" />
                    </q-item-section>
                    <q-item-section>
                      <q-item-label>{{ $t('installPage.adminAccount') }}</q-item-label>
                      <q-item-label caption class="text-grey-5">
                        {{ form.first_name }} {{ form.last_name }}
                      </q-item-label>
                    </q-item-section>
                  </q-item>

                  <q-item>
                    <q-item-section avatar>
                      <q-icon name="mdi-email" color="primary" />
                    </q-item-section>
                    <q-item-section>
                      <q-item-label>{{ $t('installPage.email') }}</q-item-label>
                      <q-item-label caption class="text-grey-5">{{ form.email }}</q-item-label>
                    </q-item-section>
                  </q-item>

                  <q-item>
                    <q-item-section avatar>
                      <q-icon name="mdi-web" color="primary" />
                    </q-item-section>
                    <q-item-section>
                      <q-item-label>{{ $t('installPage.siteName') }}</q-item-label>
                      <q-item-label caption class="text-grey-5">{{ form.site_name }}</q-item-label>
                    </q-item-section>
                  </q-item>

                  <q-item>
                    <q-item-section avatar>
                      <q-icon name="mdi-translate" color="primary" />
                    </q-item-section>
                    <q-item-section>
                      <q-item-label>{{ $t('installPage.language') }}</q-item-label>
                      <q-item-label caption class="text-grey-5">
                        {{ getLocaleLabel(form.locale) }}
                      </q-item-label>
                    </q-item-section>
                  </q-item>
                </q-list>
              </div>

              <FormBanner v-if="error" :message="error" class="q-mt-md" no-margin />

              <q-stepper-navigation>
                <q-btn
                  unelevated
                  @click="handleInstall"
                  color="primary"
                  :label="$t('installPage.completeSetup')"
                  icon="mdi-check"
                  :loading="loading"
                />
                <q-btn
                  flat
                  @click="step = 2"
                  color="primary"
                  :label="$t('installPage.back')"
                  icon="mdi-arrow-left"
                  class="q-ml-sm"
                  :disable="loading"
                />
              </q-stepper-navigation>
            </q-step>
          </q-stepper>
        </q-card-section>
      </q-card>
    </div>
  </q-page>
</template>

<script>
import { defineComponent, ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { getInstallStatus, setupInstall } from 'src/services/authService'
import { logger } from 'src/utils/logger'
import { useBackgroundRotation } from 'src/composables/useBackgroundRotation'
import PasswordPairField from 'src/components/PasswordPairField.vue'
import FormBanner from 'src/components/FormBanner.vue'

export default defineComponent({
  name: 'InstallPage',
  components: { PasswordPairField, FormBanner },
  setup() {
    const router = useRouter()
    const { t } = useI18n()
    const { backgroundStyle, backgroundTitle } = useBackgroundRotation()

    const checkingStatus = ref(true)
    const alreadyInstalled = ref(false)
    const loading = ref(false)
    const error = ref('')
    const step = ref(1)

    const form = ref({
      first_name: '',
      last_name: '',
      email: '',
      password: '',
      password_confirm: '',
      site_name: 'pyrate.media',
      locale: 'de-DE',
    })

    const localeOptions = [
      { value: 'de-DE', label: 'Deutsch (Deutschland)' },
      { value: 'en-US', label: 'English (United States)' },
    ]

    const isValidEmail = (val) => {
      const emailPattern = /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/
      return emailPattern.test(val)
    }

    const getLocaleLabel = (locale) => {
      const option = localeOptions.find((o) => o.value === locale)
      return option ? option.label : locale
    }

    const validateStep1 = () => {
      if (!form.value.first_name || !form.value.last_name) return
      if (!form.value.email || !isValidEmail(form.value.email)) return
      if (!form.value.password || form.value.password.length < 8) return
      if (!/(?=.*[a-z])(?=.*[A-Z])(?=.*\d)/.test(form.value.password)) return
      if (form.value.password !== form.value.password_confirm) return
      step.value = 2
    }

    const checkInstallStatus = async () => {
      try {
        checkingStatus.value = true
        const data = await getInstallStatus()
        alreadyInstalled.value = data.installed
      } catch (err) {
        logger.error('Error checking install status:', err)
        alreadyInstalled.value = false
      } finally {
        checkingStatus.value = false
      }
    }

    const handleInstall = async () => {
      try {
        loading.value = true
        error.value = ''

        const data = await setupInstall({
          email: form.value.email,
          password: form.value.password,
          first_name: form.value.first_name,
          last_name: form.value.last_name,
          site_name: form.value.site_name,
          locale: form.value.locale,
        })

        if (data.success) {
          router.push('/auth/login')
        }
      } catch (err) {
        logger.error('Installation error:', err)
        error.value = err.response?.data?.detail || err.message || t('installPage.error')
      } finally {
        loading.value = false
      }
    }

    onMounted(() => {
      checkInstallStatus()
    })

    return {
      backgroundStyle,
      backgroundTitle,
      checkingStatus,
      alreadyInstalled,
      loading,
      error,
      step,
      form,
      localeOptions,
      isValidEmail,
      getLocaleLabel,
      validateStep1,
      handleInstall,
    }
  },
})
</script>

<style lang="scss" scoped>
@import 'src/css/auth-layout';

.install-wrapper {
  width: 100%;
  max-width: 720px;
}

.login-card {
  border-radius: 12px;
  overflow: hidden;
}

.summary-list {
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.08);
}

/* Stepper sits inside the auth card already; strip its own background
   so it doesn't read as a nested card. */
.install-stepper {
  background: transparent !important;
}

:deep(.install-stepper .q-stepper__step-inner) {
  padding-left: 32px;
}
</style>
