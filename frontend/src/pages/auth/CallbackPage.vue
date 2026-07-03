<template>
  <q-page class="flex flex-center">
    <div class="q-pa-md text-center" style="max-width: 400px; width: 100%">
      <div v-if="loading">
        <q-spinner-dots size="4rem" color="primary" />
        <h5 class="q-mt-lg q-mb-md">{{ $t('callback.processing') }}</h5>
        <p class="text-grey-6">
          {{ $t('callback.pleaseWait') }}
        </p>
      </div>

      <div v-else-if="error">
        <q-icon name="mdi-alert-circle" size="4rem" color="negative" />
        <h5 class="q-mt-lg q-mb-md text-negative">{{ $t('callback.loginFailed') }}</h5>
        <q-card class="q-pa-md q-mt-md">
          <q-card-section>
            <p class="text-body2">{{ error }}</p>
            <div class="q-mt-lg">
              <q-btn
                color="primary"
                :label="$t('callback.retry')"
                @click="retryLogin"
                class="q-mr-sm"
              />
              <q-btn
                flat
                color="grey-6"
                :label="$t('callback.backToHome')"
                @click="$router.push('/')"
              />
            </div>
          </q-card-section>
        </q-card>
      </div>

      <div v-else>
        <q-icon name="mdi-check-circle" size="4rem" color="positive" />
        <h5 class="q-mt-lg q-mb-md text-positive">{{ $t('callback.loginSuccess') }}</h5>
        <p class="text-grey-6">
          {{ $t('callback.redirecting') }}
        </p>
      </div>
    </div>
  </q-page>
</template>

<script>
import { defineComponent, ref, onMounted, onUnmounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from 'src/stores/auth'
import { useI18n } from 'vue-i18n'
import { logger } from 'src/utils/logger'
import { getServerUrl } from 'src/utils/authStorage'

export default defineComponent({
  name: 'CallbackPage',
  setup() {
    const router = useRouter()
    const route = useRoute()
    const authStore = useAuthStore()
    const { t } = useI18n()

    const loading = ref(true)
    const error = ref('')
    const redirectTimer = ref(null)

    const handleCallback = async () => {
      try {
        loading.value = true
        error.value = ''

        // Check for error in URL params
        if (route.query.error) {
          throw new Error(route.query.error_description || route.query.error)
        }

        // Compatibility path: older OIDC provider configs may still redirect
        // directly to the frontend /auth/callback with code/state. Hand that
        // authorization response to the backend callback, which verifies state
        // and exchanges the code for pyrate tokens.
        if (route.query.code && route.query.state && !window.location.hash.includes('access_token')) {
          const baseUrl = getServerUrl().replace(/\/+$/, '')
          const callbackUrl = new URL(`${baseUrl || window.location.origin}/api/auth/callback`)
          callbackUrl.search = window.location.search
          window.location.href = baseUrl
            ? callbackUrl.toString()
            : `${callbackUrl.pathname}${callbackUrl.search}`
          return
        }

        // Handle the OIDC callback
        await authStore.handleLoginCallback()

        // Show success notification

        // Redirect to intended page or home
        const redirectTo = route.query.return_to || route.query.state || '/'
        redirectTimer.value = setTimeout(() => {
          router.push(redirectTo)
        }, 1500)
      } catch (err) {
        logger.error('Callback error:', err)
        error.value = err.message || t('callback.unknownError')
      } finally {
        loading.value = false
      }
    }

    const retryLogin = () => {
      router.push('/auth/login')
    }

    onMounted(() => {
      handleCallback()
    })

    onUnmounted(() => {
      if (redirectTimer.value) clearTimeout(redirectTimer.value)
    })

    return {
      loading,
      error,
      retryLogin,
    }
  },
})
</script>

<style scoped>
.q-page {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  min-height: 100vh;
}
</style>
