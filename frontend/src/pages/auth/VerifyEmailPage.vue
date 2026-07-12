<template>
  <q-page class="verify-email-page flex flex-center">
    <q-card flat class="verify-card bg-dark text-white" style="max-width: 480px; width: 100%">
      <q-card-section class="text-center q-pa-lg">
        <!-- Loading -->
        <template v-if="loading">
          <q-spinner-dots size="48px" color="primary" class="q-mb-md" />
          <div class="text-h6">{{ $t('auth.verifyingEmail') || 'Verifying your email...' }}</div>
        </template>

        <!-- Success -->
        <template v-else-if="success">
          <q-icon name="mdi-check-circle" size="64px" color="positive" class="q-mb-md" />
          <div class="text-h6 q-mb-sm">{{ $t('auth.emailVerified') || 'Email verified!' }}</div>
          <div class="text-grey-5 q-mb-lg">
            {{ $t('auth.emailVerifiedDesc') || 'Your email address has been confirmed.' }}
          </div>
          <q-btn
            color="primary"
            :label="$t('auth.goToLogin') || 'Go to Login'"
            icon="mdi-login"
            @click="$router.push('/auth/login')"
          />
        </template>

        <!-- Error -->
        <template v-else>
          <q-icon name="mdi-alert-circle" size="64px" color="negative" class="q-mb-md" />
          <div class="text-h6 q-mb-sm">
            {{ $t('auth.verificationFailed') || 'Verification failed' }}
          </div>
          <div class="text-grey-5 q-mb-lg">{{ errorMessage }}</div>
          <q-btn
            color="primary"
            :label="$t('auth.goToLogin') || 'Go to Login'"
            icon="mdi-login"
            @click="$router.push('/auth/login')"
          />
        </template>
      </q-card-section>
    </q-card>
  </q-page>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { verifyEmail } from 'src/services/authService'
import { logger } from 'src/utils/logger'

const route = useRoute()

const loading = ref(true)
const success = ref(false)
const errorMessage = ref('')

onMounted(async () => {
  const token = route.query.token
  if (!token) {
    loading.value = false
    errorMessage.value = 'No verification token provided.'
    return
  }

  try {
    await verifyEmail(token)
    success.value = true
  } catch (err) {
    logger.error('Email verification failed', err)
    errorMessage.value =
      err.response?.data?.detail || 'The verification link is invalid or expired.'
  } finally {
    loading.value = false
  }
})
</script>

<style lang="scss" scoped>
.verify-email-page {
  min-height: 100vh;
  background: $dark;
}
</style>
