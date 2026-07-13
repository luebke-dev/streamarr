<template>
  <q-page class="flex flex-center login-page" :style="backgroundStyle">
    <div v-if="backgroundTitle" class="bg-title-overlay">
      {{ backgroundTitle }}
    </div>
    <div class="login-wrapper q-pa-md">
      <div class="text-center q-mb-xl">
        <q-icon name="mdi-television-play" size="4rem" color="primary" />
        <h4 class="q-mt-md q-mb-none text-white">{{ $t('auth.loginTitle') }}</h4>
        <p class="text-grey-5">{{ $t('auth.loginSubtitle') }}</p>
      </div>

      <q-card dark class="login-card">
        <q-card-section class="no-padding">
          <div class="login-columns">
            <!-- Login Form (left) -->
            <div class="form-column q-pa-xl">
              <FormBanner v-if="error" :message="error" />

              <!-- Local Login Form -->
              <q-form
                v-if="authStore.localAuthEnabled !== false"
                @submit="handleLocalLogin"
                class="q-gutter-y-md"
              >
                <q-input
                  v-show="showServerUrl"
                  v-model="serverUrl"
                  type="url"
                  :label="$t('auth.serverAddressLabel')"
                  outlined
                  dark
                  dense
                  :disable="loading"
                  :rules="
                    showServerUrl
                      ? [
                          (val) => !!val || $t('auth.serverAddressRequired'),
                          (val) => isValidUrl(val) || $t('auth.serverAddressInvalid'),
                        ]
                      : []
                  "
                  placeholder="https://streamarr.example.com"
                >
                  <template v-slot:prepend>
                    <q-icon name="mdi-server" />
                  </template>
                </q-input>

                <q-input
                  v-model="email"
                  type="email"
                  :label="$t('auth.emailLabel')"
                  outlined
                  dark
                  dense
                  :disable="loading"
                  :rules="[(val) => !!val || $t('auth.emailRequired')]"
                >
                  <template v-slot:prepend>
                    <q-icon name="mdi-at" />
                  </template>
                </q-input>

                <q-input
                  v-model="password"
                  type="password"
                  :label="$t('auth.passwordLabel')"
                  outlined
                  dark
                  dense
                  :disable="loading"
                  :rules="[(val) => !!val || $t('auth.passwordRequired')]"
                >
                  <template v-slot:prepend>
                    <q-icon name="mdi-lock" />
                  </template>
                </q-input>

                <q-btn
                  type="submit"
                  color="primary"
                  size="lg"
                  class="full-width"
                  :loading="loading"
                  :disable="loading"
                  icon="mdi-login"
                  :label="$t('auth.loginButton')"
                />

                <div v-if="!showServerUrl" class="text-center">
                  <q-btn
                    flat
                    dense
                    size="sm"
                    color="grey-5"
                    icon="mdi-server-network"
                    :label="$t('auth.useOtherServer')"
                    :disable="loading"
                    @click="showServerUrl = true"
                  />
                </div>
              </q-form>

              <!-- OIDC Login (if enabled) -->
              <div v-if="authStore.oidcEnabled" class="q-mt-lg">
                <q-separator dark class="q-my-md" />

                <q-btn
                  @click="handleOidcLogin"
                  color="secondary"
                  size="lg"
                  class="full-width"
                  :loading="oidcLoading"
                  :disable="oidcLoading"
                  icon="mdi-login"
                  :label="$t('auth.oidcLoginButton')"
                  outline
                />

                <div class="text-center q-mt-md">
                  <p class="text-grey-4 text-caption">
                    {{ $t('auth.oidcRedirectNote') }}
                  </p>
                </div>
              </div>
            </div>

            <!-- Divider -->
            <q-separator dark class="col-divider" />

            <!-- QR Code (right) -->
            <div class="qr-column flex flex-center q-pa-xl">
              <div class="text-center">
                <div class="qr-container q-mb-lg">
                  <canvas ref="qrCanvas" />
                </div>
                <p class="text-grey-4 text-caption" style="max-width: 220px; margin: 0 auto">
                  {{ $t('auth.deviceQrSubtitle') }}
                </p>
              </div>
            </div>
          </div>
        </q-card-section>
      </q-card>

      <div class="text-center q-mt-lg q-gutter-md bottom-links">
        <q-btn
          v-if="authStore.localAuthEnabled !== false"
          flat
          color="grey-4"
          icon="mdi-account-plus"
          :label="$t('auth.registerLink')"
          @click="$router.push('/register')"
        />
        <q-btn
          v-if="authStore.localAuthEnabled !== false"
          flat
          color="grey-4"
          icon="mdi-lock-question"
          :label="$t('auth.forgotPassword')"
          @click="$router.push('/auth/forgot-password')"
        />
      </div>
    </div>
  </q-page>
</template>

<script>
import { defineComponent, ref, onMounted, onUnmounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from 'src/stores/auth'
import { useI18n } from 'vue-i18n'
import axios from 'axios'
import { useBackgroundRotation } from 'src/composables/useBackgroundRotation'
import { getServerUrl, setServerUrl } from 'src/utils/authStorage'
import { logger } from 'src/utils/logger'
import { sanitizeRedirect } from 'src/utils/redirect'
import FormBanner from 'src/components/FormBanner.vue'

export default defineComponent({
  name: 'LoginPage',
  components: { FormBanner },
  setup() {
    const router = useRouter()
    const route = useRoute()
    const authStore = useAuthStore()
    const { t } = useI18n()

    const loading = ref(false)
    const oidcLoading = ref(false)
    const error = ref('')
    const serverUrl = ref(getServerUrl())
    const serverUrlLocked = ref(false)
    const serverUrlSource = ref(null) // 'origin' | 'qr'
    // Show the server URL field only when there's no known server yet
    const showServerUrl = ref(!serverUrl.value)
    const email = ref('')
    const password = ref('')
    const qrCanvas = ref(null)
    const deviceId = ref('')
    const claimsInterval = ref(null)

    const { backgroundStyle, backgroundTitle } = useBackgroundRotation()

    const lockServerUrl = (url, source = 'manual') => {
      const normalized = url.replace(/\/+$/, '')
      serverUrl.value = normalized
      serverUrlLocked.value = true
      serverUrlSource.value = source
      showServerUrl.value = false
      setServerUrl(normalized)
    }

    const isValidUrl = (val, { requireHttps = false } = {}) => {
      try {
        const url = new URL(val)
        if (requireHttps) return url.protocol === 'https:'
        return url.protocol === 'https:' || url.protocol === 'http:'
      } catch {
        return false
      }
    }

    const handleLocalLogin = async () => {
      try {
        loading.value = true
        error.value = ''

        // Save server URL – axios interceptor picks it up automatically on the next request
        lockServerUrl(serverUrl.value)

        await authStore.localLogin(email.value, password.value)

        const redirect = sanitizeRedirect(route.query.redirect)
        router.push(redirect)
      } catch (err) {
        logger.error('Local login error:', err)
        error.value = err.response?.data?.detail || err.message || t('auth.loginFailed')
      } finally {
        loading.value = false
      }
    }

    const handleOidcLogin = async () => {
      try {
        oidcLoading.value = true
        error.value = ''

        await authStore.login(route.query.redirect || '/')
      } catch (err) {
        logger.error('OIDC login error:', err)
        error.value = err.message || t('auth.oidcLoginFailed')
      } finally {
        oidcLoading.value = false
      }
    }

    const renderQrCode = async (id) => {
      if (!qrCanvas.value || !id) return
      try {
        const { default: QRCode } = await import('qrcode')
        await QRCode.toCanvas(qrCanvas.value, id, {
          width: 200,
          margin: 1,
          color: {
            dark: '#ffffff',
            light: '#1a1a1a',
          },
        })
      } catch (e) {
        logger.error('QR code generation failed:', e)
      }
    }

    onMounted(async () => {
      // Initialize auth store to check OIDC availability
      await authStore.initialize()

      // Check if user is already authenticated
      if (authStore.isAuthenticated) {
        const redirect = sanitizeRedirect(route.query.redirect)
        router.push(redirect)
        return
      }

      // Check for error in query params
      if (route.query.error) {
        error.value = route.query.error_description || route.query.error
      }

      deviceId.value = authStore.deviceId
      await renderQrCode(deviceId.value)

      // ── 1. Probe current origin ──────────────────────────────────────────
      // If the page is served from the same host as the backend, detect and
      // lock the server URL automatically (no need for manual entry or QR scan).
      const probeCurrentOrigin = async () => {
        try {
          const res = await axios.get(`${window.location.origin}/api/auth/status`, {
            timeout: 3000,
            // Accept only JSON – if the SPA serves its own index.html the
            // content-type will be text/html, which we treat as "no backend".
            headers: { Accept: 'application/json' },
          })
          // Verify the response is actually JSON (not the SPA's index.html)
          const ct = res.headers?.['content-type'] || ''
          if (ct.includes('application/json') && !serverUrlLocked.value) {
            lockServerUrl(window.location.origin, 'origin')
          }
        } catch (e) {
          // HTTP error responses from the real backend carry JSON content-type
          const ct = e.response?.headers?.['content-type'] || ''
          if (e.response && ct.includes('application/json') && !serverUrlLocked.value) {
            lockServerUrl(window.location.origin, 'origin')
          }
          // Otherwise: network error, timeout, or SPA HTML → no backend here
        }
      }
      probeCurrentOrigin()

      // ── 2. Claims polling (QR-code path) ────────────────────────────────
      // Polls api.streamarr.media to discover the server URL after a QR scan on
      // an already-authenticated device. Always runs in parallel and can
      // override the origin-probe result (explicit user action via QR).
      const pollClaims = async () => {
        try {
          const res = await axios.get(`https://api.streamarr.media/v1/claims/${deviceId.value}`)
          const claimedUrl = res.data?.server_url
          if (claimedUrl) {
            // The claims service is an external, untrusted source: only adopt a
            // valid https origin as the API base. Refusing http:// blocks a
            // credential downgrade to plaintext and an unvalidated/attacker
            // host from silently receiving the next email+password POST.
            if (!isValidUrl(claimedUrl, { requireHttps: true })) {
              logger.warn('Ignoring invalid server_url from claims poll')
              return
            }
            clearInterval(claimsInterval.value)
            claimsInterval.value = null
            lockServerUrl(claimedUrl, 'qr')
          }
        } catch {
          // Server not ready yet – keep polling
        }
      }

      claimsInterval.value = setInterval(pollClaims, 5000)
    })

    onUnmounted(() => {
      if (claimsInterval.value) {
        clearInterval(claimsInterval.value)
        claimsInterval.value = null
      }
    })

    return {
      loading,
      oidcLoading,
      error,
      serverUrl,
      serverUrlLocked,
      serverUrlSource,
      showServerUrl,
      email,
      password,
      qrCanvas,
      deviceId,
      authStore,
      backgroundStyle,
      backgroundTitle,
      handleLocalLogin,
      handleOidcLogin,
      isValidUrl,
    }
  },
})
</script>

<style lang="scss" scoped>
@import 'src/css/auth-layout';

.login-wrapper {
  width: 100%;
  max-width: 860px;
}

.login-card {
  border-radius: 12px;
  overflow: hidden;
}

.login-columns {
  display: flex;
  flex-direction: row;
  align-items: stretch;
}

.form-column {
  flex: 1 1 0;
  min-width: 0;
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.col-divider {
  /* vertical by default on wide screens */
  width: 1px;
  min-width: 1px;
  height: auto;
  align-self: stretch;
}

.qr-column {
  background: rgba(255, 255, 255, 0.02);
  min-width: 260px;
  width: 280px;
  flex-shrink: 0;
}

@media (max-width: 599px) {
  .login-columns {
    flex-direction: column;
  }

  .col-divider {
    width: auto;
    min-width: 0;
    height: 1px;
    min-height: 1px;
    align-self: stretch;
  }

  .qr-column {
    width: 100%;
    min-width: 0;
  }

  .bottom-links {
    margin-bottom: 48px;
  }
}

.qr-container canvas {
  display: block;
  width: 200px !important;
  height: 200px !important;
}

.qr-container {
  display: inline-block;
  border-radius: 10px;
  overflow: hidden;
  line-height: 0;
  padding: 12px;
  background: #1a1a1a;
  border: 1px solid rgba(255, 255, 255, 0.1);
}
</style>
