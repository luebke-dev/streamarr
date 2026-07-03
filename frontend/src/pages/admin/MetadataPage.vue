<template>
  <q-page padding>
    <div class="q-pa-md">
      <div class="text-h4 q-mb-xs">{{ $t('admin.metadata.title') }}</div>
      <p class="text-subtitle1 text-grey-7 q-mb-lg">
        {{ $t('admin.metadata.description') }}
      </p>

      <q-card flat bordered v-if="loading">
        <q-card-section>
          <div class="row justify-center">
            <q-spinner color="primary" size="3em" />
          </div>
        </q-card-section>
      </q-card>

      <q-list v-else bordered separator class="rounded-borders">
        <q-expansion-item
          v-for="provider in providers"
          :key="provider.domain"
          :icon="provider.icon"
          :label="provider.name"
          :caption="provider.description"
          group="providers"
          @show="loadProviderConfig(provider.domain)"
        >
          <template v-slot:side>
            <q-chip v-if="provider.configured" color="positive" text-color="white" size="sm" dense>
              {{ $t('admin.metadata.configured') }}
            </q-chip>
            <q-chip
              v-else-if="provider.has_config"
              color="warning"
              text-color="white"
              size="sm"
              dense
            >
              {{ $t('admin.metadata.notConfigured') }}
            </q-chip>
            <q-chip v-else color="grey-6" text-color="white" size="sm" dense>
              {{ $t('admin.metadata.noConfigNeeded') }}
            </q-chip>
          </template>

          <q-card flat>
            <q-card-section v-if="providerLoading[provider.domain]">
              <div class="row justify-center q-pa-md">
                <q-spinner color="primary" size="2em" />
              </div>
            </q-card-section>

            <q-card-section v-else-if="provider.has_config">
              <div v-for="(field, fieldName) in provider.config_schema" :key="fieldName">
                <q-input
                  v-if="field.type === 'string'"
                  v-model="providerConfigs[provider.domain][fieldName]"
                  :label="field.label"
                  :hint="field.hint"
                  :placeholder="field.placeholder"
                  :required="field.required"
                  outlined
                  class="q-mb-md"
                />

                <q-input
                  v-else-if="field.type === 'password'"
                  v-model="providerConfigs[provider.domain][fieldName]"
                  :label="field.label"
                  :hint="field.hint"
                  :placeholder="field.placeholder"
                  :required="field.required"
                  :type="passwordVisible[provider.domain + '.' + fieldName] ? 'text' : 'password'"
                  outlined
                  class="q-mb-md"
                >
                  <template v-slot:append>
                    <q-icon
                      :name="
                        passwordVisible[provider.domain + '.' + fieldName]
                          ? 'mdi-eye-off'
                          : 'mdi-eye'
                      "
                      class="cursor-pointer"
                      @click="
                        passwordVisible[provider.domain + '.' + fieldName] =
                          !passwordVisible[provider.domain + '.' + fieldName]
                      "
                    />
                  </template>
                </q-input>

                <q-input
                  v-else-if="field.type === 'number'"
                  v-model.number="providerConfigs[provider.domain][fieldName]"
                  :label="field.label"
                  :hint="field.hint"
                  type="number"
                  :min="field.min"
                  :max="field.max"
                  outlined
                  class="q-mb-md"
                />

                <q-checkbox
                  v-else-if="field.type === 'boolean'"
                  v-model="providerConfigs[provider.domain][fieldName]"
                  :label="field.label"
                  class="q-mb-md"
                />

                <FormBanner
                  v-if="field.info_text && field.info_link"
                  type="info"
                  no-margin
                  class="q-mb-md"
                >
                  {{ field.info_text }}
                  <a
                    :href="field.info_link"
                    target="_blank"
                    rel="noopener noreferrer"
                    class="text-white"
                    style="text-decoration: underline"
                  >
                    {{ field.info_link.replace('https://', '') }}
                  </a>
                </FormBanner>
              </div>

              <!-- Status messages -->
              <FormBanner
                v-if="providerErrors[provider.domain]"
                :message="providerErrors[provider.domain]"
                no-margin
                class="q-mb-md"
              />

              <FormBanner
                v-if="providerSuccess[provider.domain]"
                type="success"
                :message="providerSuccess[provider.domain]"
                no-margin
                class="q-mb-md"
              />
            </q-card-section>

            <q-card-section v-else>
              <p class="text-grey-7">{{ $t('admin.metadata.noConfigNeeded') }}</p>
            </q-card-section>

            <q-card-actions align="right" class="q-pa-md">
              <q-btn
                flat
                :label="$t('admin.metadata.testConnection')"
                @click="testConnection(provider.domain)"
                color="primary"
                :loading="providerTesting[provider.domain]"
                icon="mdi-connection"
              />
              <q-btn
                v-if="provider.has_config"
                unelevated
                :label="$t('common.save')"
                @click="saveConfig(provider.domain)"
                color="primary"
                :loading="providerSaving[provider.domain]"
                icon="mdi-content-save"
              />
            </q-card-actions>
          </q-card>
        </q-expansion-item>
      </q-list>
    </div>
  </q-page>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { api } from 'boot/axios'
import { useI18n } from 'vue-i18n'
import { logger } from 'src/utils/logger'
import FormBanner from 'src/components/FormBanner.vue'

const { t } = useI18n()

const loading = ref(true)
const providers = ref([])
const providerConfigs = reactive({})
const providerLoading = reactive({})
const providerSaving = reactive({})
const providerTesting = reactive({})
const providerErrors = reactive({})
const providerSuccess = reactive({})
const passwordVisible = reactive({})

const loadProviders = async () => {
  try {
    const response = await api.get('/api/metadata/providers')
    providers.value = response.data
    for (const p of providers.value) {
      providerConfigs[p.domain] = {}
    }
  } catch (error) {
    logger.error('Failed to load metadata providers:', error)
  }
}

const loadProviderConfig = async (domain) => {
  if (providerLoading[domain]) return
  providerLoading[domain] = true
  try {
    const response = await api.get(`/api/metadata/providers/${domain}/config`)
    providerConfigs[domain] = response.data.config || {}
  } catch (error) {
    logger.error(`Failed to load config for ${domain}:`, error)
  } finally {
    providerLoading[domain] = false
  }
}

const saveConfig = async (domain) => {
  providerSaving[domain] = true
  providerErrors[domain] = null
  providerSuccess[domain] = null
  try {
    await api.put(`/api/metadata/providers/${domain}/config`, {
      config: providerConfigs[domain],
    })
    providerSuccess[domain] = t('admin.metadata.saveSuccess')
    // Update configured status
    const provider = providers.value.find((p) => p.domain === domain)
    if (provider) provider.configured = true
    setTimeout(() => {
      providerSuccess[domain] = null
    }, 3000)
  } catch (error) {
    logger.error(`Failed to save config for ${domain}:`, error)
    const detail = error.response?.data?.detail
    if (typeof detail === 'object' && detail.errors) {
      providerErrors[domain] = detail.errors.join(', ')
    } else if (typeof detail === 'string') {
      providerErrors[domain] = detail
    } else {
      providerErrors[domain] = t('admin.metadata.saveError')
    }
  } finally {
    providerSaving[domain] = false
  }
}

const testConnection = async (domain) => {
  providerTesting[domain] = true
  providerErrors[domain] = null
  providerSuccess[domain] = null
  try {
    const config = providerConfigs[domain] || {}
    const hasConfig = Object.keys(config).length > 0
    const response = hasConfig
      ? await api.post(`/api/metadata/providers/${domain}/test`, { config })
      : await api.post(`/api/metadata/providers/${domain}/test`)

    if (response.data.success) {
      providerSuccess[domain] = t('admin.metadata.testSuccess')
      setTimeout(() => {
        providerSuccess[domain] = null
      }, 3000)
    } else {
      providerErrors[domain] =
        response.data.error || response.data.errors?.join(', ') || t('admin.metadata.testFailed')
    }
  } catch (error) {
    logger.error(`Failed to test connection for ${domain}:`, error)
    providerErrors[domain] = error.response?.data?.detail || t('admin.metadata.testFailed')
  } finally {
    providerTesting[domain] = false
  }
}

onMounted(async () => {
  loading.value = true
  try {
    await loadProviders()
  } finally {
    loading.value = false
  }
})
</script>
