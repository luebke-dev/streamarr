<template>
  <q-page class="flex flex-center login-page" :style="backgroundStyle">
    <div v-if="backgroundTitle" class="bg-title-overlay">
      {{ backgroundTitle }}
    </div>
    <div class="q-pa-md" style="max-width: 400px; width: 100%">
      <div class="text-center q-mb-xl">
        <q-icon name="mdi-lock-reset" size="4rem" color="primary" />
        <h4 class="q-mt-md q-mb-none text-white">{{ $t('resetPassword.title') }}</h4>
      </div>

      <q-card dark class="login-card q-pa-lg">
        <q-card-section>
          <!-- No token -->
          <div v-if="!token" class="text-center q-py-md">
            <q-icon name="mdi-alert-circle" size="3rem" color="negative" class="q-mb-md" />
            <p class="text-grey-3">{{ $t('resetPassword.invalidLink') }}</p>
            <q-btn
              flat
              color="primary"
              :label="$t('forgotPassword.backToLogin')"
              icon="mdi-arrow-left"
              @click="$router.push('/auth/login')"
            />
          </div>

          <!-- Success -->
          <div v-else-if="success" class="text-center q-py-md">
            <q-icon name="mdi-check-circle" size="3rem" color="positive" class="q-mb-md" />
            <p class="text-grey-3">{{ $t('resetPassword.successMessage') }}</p>
            <q-btn
              color="primary"
              :label="$t('auth.goToLogin') || 'Go to Login'"
              icon="mdi-login"
              @click="$router.push('/auth/login')"
              class="q-mt-md"
            />
          </div>

          <!-- Form -->
          <div v-else>
            <p class="text-grey-4 q-mb-lg">{{ $t('resetPassword.description') }}</p>

            <q-form @submit="handleSubmit" class="q-gutter-md">
              <PasswordPairField
                v-model="password"
                v-model:confirm="passwordConfirm"
                :password-label="$t('resetPassword.newPassword')"
                :confirm-label="$t('resetPassword.confirmPassword')"
                :messages="{
                  required: $t('auth.passwordRequired'),
                  minLength: $t('auth.passwordMinLength'),
                  mismatch: $t('resetPassword.passwordMismatch'),
                }"
              />

              <div v-if="error" class="text-negative text-center q-mb-sm">
                {{ error }}
              </div>

              <q-btn
                type="submit"
                color="primary"
                size="lg"
                class="full-width"
                :loading="loading"
                icon="mdi-lock-reset"
                :label="$t('resetPassword.submitButton')"
              />
            </q-form>
          </div>
        </q-card-section>
      </q-card>
    </div>
  </q-page>
</template>

<script setup>
import { ref } from 'vue'
import { useRoute } from 'vue-router'
import { resetPassword } from 'src/services/authService'
import { useBackgroundRotation } from 'src/composables/useBackgroundRotation'
import PasswordPairField from 'src/components/PasswordPairField.vue'
import { logger } from 'src/utils/logger'

const route = useRoute()
const { backgroundStyle, backgroundTitle } = useBackgroundRotation()

const token = ref(route.query.token || '')
const password = ref('')
const passwordConfirm = ref('')
const loading = ref(false)
const success = ref(false)
const error = ref('')

async function handleSubmit() {
  error.value = ''
  if (password.value !== passwordConfirm.value) return

  try {
    loading.value = true
    await resetPassword({
      token: token.value,
      password: password.value,
    })
    success.value = true
  } catch (err) {
    logger.error('Password reset failed', err)
    error.value = err.response?.data?.detail || 'Password reset failed. The link may have expired.'
  } finally {
    loading.value = false
  }
}
</script>

<style lang="scss" scoped>
@import 'src/css/auth-layout';
</style>
