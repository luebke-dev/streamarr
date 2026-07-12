<template>
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
</template>

<script setup>
import { computed, ref, onMounted } from 'vue'
import { logger } from 'src/utils/logger'
import {
  getOidcSettings,
  saveOidcSettings as saveOidcSettingsApi,
} from 'src/services/systemAdminService'

const saving = ref(false)
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

const oidcScopes = computed({
  get: () => (oidcSettings.value.scopes || []).join(' '),
  set: (value) => {
    oidcSettings.value.scopes = value.split(/\s+/).filter(Boolean)
  },
})

const loadOidcSettings = async () => {
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

onMounted(loadOidcSettings)

defineExpose({ reload: loadOidcSettings })
</script>

<style lang="scss" scoped>
.settings-card {
  background: rgba(255, 255, 255, 0.05);
  backdrop-filter: blur(10px);
  border: 1px solid rgba(255, 255, 255, 0.1);
}
</style>
