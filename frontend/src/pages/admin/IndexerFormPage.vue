<template>
  <q-page class="q-pa-md">
    <div class="row justify-between items-center q-mb-lg">
      <div>
        <h4 class="q-my-none">{{ $t(`${tKey}.title`) }}</h4>
        <p class="text-grey-6 q-mb-none">{{ $t(`${tKey}.subtitle`) }}</p>
      </div>
      <q-btn
        flat
        icon="mdi-arrow-left"
        :label="$t(`${tKey}.backToIndexers`)"
        @click="$router.push('/admin/indexers')"
        class="q-ml-md"
      />
    </div>

    <q-card class="q-pa-lg" style="max-width: 900px" v-if="!loading">
      <q-stepper v-model="step" ref="stepper" color="primary" animated>
        <!-- Step 1: Connection -->
        <q-step :name="1" :title="$t(`${tKey}.connectionStep`)" icon="mdi-cog" :done="step > 1">
          <q-form @submit.prevent="testConnection" ref="stepOneForm" class="q-gutter-md">
            <q-input
              filled
              v-model="indexerForm.label"
              :label="$t(`${tKey}.name`)"
              lazy-rules
              :rules="[(val) => (val && val.length > 0) || $t(`${tKey}.${nameRuleKey}`)]"
            />

            <q-select
              filled
              v-model="indexerForm.type"
              :options="indexerTypes"
              :label="$t(`${tKey}.type`)"
              emit-value
              map-options
            />

            <q-input
              filled
              v-model="indexerForm.host"
              :label="$t(`${tKey}.hostUrl`)"
              :hint="$t(`${tKey}.hostHint`)"
              lazy-rules
              :rules="[(val) => (val && val.length > 0) || $t(`${tKey}.${hostRuleKey}`)]"
            />

            <q-input
              filled
              v-model="indexerForm.api_key"
              :label="$t(`${tKey}.apiKey`)"
              :type="showApiKey ? 'text' : 'password'"
              :hint="apiKeyHint"
              lazy-rules
              :rules="apiKeyRules"
            >
              <template #append>
                <q-icon
                  :name="showApiKey ? 'mdi-eye-off' : 'mdi-eye'"
                  class="cursor-pointer"
                  @click="showApiKey = !showApiKey"
                />
              </template>
            </q-input>

            <div class="row q-gutter-md">
              <q-toggle v-model="indexerForm.ssl" :label="$t(`${tKey}.useSSL`)" />
              <q-toggle v-model="indexerForm.verify_ssl" :label="$t(`${tKey}.verifySSL`)" />
            </div>

            <div class="row q-gutter-md items-center q-mt-sm">
              <q-toggle
                v-model="indexerForm.enabled"
                :label="$t(`${tKey}.enabled`)"
              />
              <q-toggle
                v-model="indexerForm.rss_enabled"
                :label="$t(`${tKey}.rssEnabled`)"
              />
              <q-input
                v-model.number="indexerForm.priority"
                type="number"
                dense
                style="max-width: 120px"
                :label="$t(`${tKey}.priority`)"
              />
            </div>
            <div v-if="lastRssSyncAt" class="text-caption text-grey-6 q-mt-xs">
              {{ $t(`${tKey}.lastRssSync`) }}:
              {{ new Date(lastRssSyncAt).toLocaleString() }}
            </div>

            <!-- Connection test result -->
            <q-banner
              v-if="connectionResult"
              :class="
                connectionResult.connected ? 'bg-positive text-white' : 'bg-negative text-white'
              "
              rounded
            >
              <template #avatar>
                <q-icon
                  :name="connectionResult.connected ? 'mdi-check-circle' : 'mdi-alert-circle'"
                />
              </template>
              <span v-if="connectionResult.connected">
                {{
                  $t(`${tKey}.connectionSuccess`, {
                    count: connectionResult.categories.length,
                  })
                }}
              </span>
              <span v-else>{{ connectionResult.error }}</span>
            </q-banner>

            <q-stepper-navigation>
              <q-btn
                type="submit"
                color="primary"
                :label="
                  connectionResult && connectionResult.connected
                    ? $t(`${tKey}.nextCategories`)
                    : $t(`${tKey}.testConnection`)
                "
                :icon="
                  connectionResult && connectionResult.connected
                    ? 'mdi-arrow-right'
                    : 'mdi-connection'
                "
                :loading="testingConnection"
              />
              <q-btn
                v-if="isEditMode"
                flat
                :label="$t(`${tKey}.continueWithoutTest`)"
                icon="mdi-arrow-right"
                @click="step = 2"
                class="q-ml-sm"
              />
              <q-btn
                flat
                :label="$t(`${tKey}.cancel`)"
                @click="$router.push('/admin/indexers')"
                class="q-ml-sm"
              />
            </q-stepper-navigation>
          </q-form>
        </q-step>

        <!-- Step 2: Categories -->
        <q-step :name="2" :title="$t(`${tKey}.categoriesStep`)" icon="mdi-shape" :done="step > 2">
          <div class="q-gutter-md">
            <div class="row items-center justify-between q-mb-sm">
              <p class="text-body2 text-grey-7 q-mb-none">
                {{ $t(`${tKey}.categoriesDescription`) }}
              </p>
              <q-btn
                v-if="isEditMode"
                flat
                dense
                icon="mdi-refresh"
                :label="$t(`${tKey}.reloadCategories`)"
                color="primary"
                :loading="testingConnection"
                @click="fetchCapsOnly"
              />
            </div>

            <!-- Category tree from indexer -->
            <div v-if="availableCategories.length > 0">
              <div v-for="cat in availableCategories" :key="cat.id" class="q-mb-sm">
                <div class="text-subtitle2 text-grey-4 q-mb-xs q-mt-md">
                  <q-icon name="mdi-folder" size="sm" class="q-mr-xs" />
                  {{ cat.name }} ({{ cat.id }})
                </div>

                <div
                  v-for="sub in cat.subcategories && cat.subcategories.length > 0
                    ? cat.subcategories
                    : [cat]"
                  :key="sub.id"
                  class="category-row q-mb-xs"
                  :class="{ selected: isSelected(sub.id) }"
                >
                  <q-card flat bordered class="q-pa-sm">
                    <div class="row items-center q-gutter-sm">
                      <q-checkbox
                        :model-value="isSelected(sub.id)"
                        @update:model-value="(v) => toggleCategory(sub, cat, v)"
                        color="primary"
                      />

                      <div class="col-2">
                        <div class="text-body2">{{ sub.name }}</div>
                        <div class="text-caption text-grey-5">ID: {{ sub.id }}</div>
                      </div>

                      <template v-if="isSelected(sub.id)">
                        <div class="col-2">
                          <q-select
                            dense
                            filled
                            v-model="getSelectedCategory(sub.id).category_type"
                            :options="categoryTypes"
                            :label="$t(`${tKey}.mediaType`)"
                            emit-value
                            map-options
                          />
                        </div>

                        <div class="col-2">
                          <q-select
                            dense
                            filled
                            v-model="getSelectedCategory(sub.id).language"
                            :options="languageOptions"
                            :label="$t(`${tKey}.languages`)"
                            clearable
                            multiple
                            use-chips
                            emit-value
                            map-options
                          />
                        </div>

                        <div class="col-2">
                          <q-select
                            dense
                            filled
                            v-model="getSelectedCategory(sub.id).resolution"
                            :options="resolutionOptions"
                            :label="$t(`${tKey}.resolutions`)"
                            clearable
                            multiple
                            use-chips
                            emit-value
                            map-options
                          />
                        </div>
                      </template>
                    </div>
                  </q-card>
                </div>
              </div>
            </div>

            <!-- Fallback: manual category list when no caps fetched (edit-mode only) -->
            <div
              v-else-if="isEditMode && savedCategories.length > 0"
              class="q-pa-md bg-grey-10 rounded-borders"
            >
              <div class="row items-center q-mb-md">
                <q-icon name="mdi-information-outline" color="info" class="q-mr-sm" />
                <span class="text-grey-5 text-body2">
                  {{ $t(`${tKey}.noCategoriesLoaded`) }}
                </span>
              </div>

              <div
                v-for="(category, index) in savedCategories"
                :key="category.newznab_category_id"
                class="q-mb-xs"
              >
                <q-card flat bordered class="q-pa-sm">
                  <div class="row items-center q-gutter-sm">
                    <div class="col-3">
                      <div class="text-body2">{{ category.label }}</div>
                      <div class="text-caption text-grey-5">
                        ID: {{ category.newznab_category_id }}
                      </div>
                    </div>
                    <div class="col-2">
                      <q-select
                        dense
                        filled
                        v-model="category.category_type"
                        :options="categoryTypes"
                        :label="$t(`${tKey}.mediaTypeLabel`)"
                        emit-value
                        map-options
                      />
                    </div>
                    <div class="col-2">
                      <q-select
                        dense
                        filled
                        v-model="category.language"
                        :options="languageOptions"
                        :label="$t(`${tKey}.languages`)"
                        clearable
                        multiple
                        use-chips
                        emit-value
                        map-options
                      />
                    </div>
                    <div class="col-2">
                      <q-select
                        dense
                        filled
                        v-model="category.resolution"
                        :options="resolutionOptions"
                        :label="$t(`${tKey}.resolutions`)"
                        clearable
                        multiple
                        use-chips
                        emit-value
                        map-options
                      />
                    </div>
                    <div class="col-auto">
                      <q-btn
                        flat
                        round
                        dense
                        icon="mdi-delete"
                        color="negative"
                        @click="savedCategories.splice(index, 1)"
                      />
                    </div>
                  </div>
                </q-card>
              </div>
            </div>

            <div v-else class="text-center q-pa-lg text-grey-5">
              <q-icon name="mdi-shape-outline" size="48px" />
              <p class="q-mt-md">{{ $t(`${tKey}.noCategories`) }}</p>
            </div>

            <!-- Selected summary -->
            <q-banner v-if="effectiveCategoryCount > 0" class="bg-grey-9 rounded-borders">
              <template #avatar>
                <q-icon name="mdi-check-all" color="primary" />
              </template>
              {{
                $t(`${tKey}.${isEditMode ? 'categoriesConfigured' : 'categoriesSelected'}`, {
                  count: effectiveCategoryCount,
                })
              }}
            </q-banner>

            <q-stepper-navigation>
              <q-btn
                color="primary"
                :label="$t(`${tKey}.${isEditMode ? 'saveIndexer' : 'createIndexer'}`)"
                icon="mdi-check"
                @click="saveIndexer"
                :loading="saving"
              />
              <q-btn
                flat
                :label="$t(`${tKey}.back`)"
                @click="step = 1"
                class="q-ml-sm"
                :disable="saving"
              />
              <q-btn
                flat
                :label="$t(`${tKey}.cancel`)"
                @click="$router.push('/admin/indexers')"
                class="q-ml-sm"
                :disable="saving"
              />
            </q-stepper-navigation>
          </div>
        </q-step>
      </q-stepper>
    </q-card>

    <!-- Loading state (edit only) -->
    <div v-else class="flex flex-center q-pa-xl">
      <q-spinner-dots size="50px" color="primary" />
      <p class="q-ml-md text-grey-6">{{ $t(`${tKey}.loadingData`) }}</p>
    </div>
  </q-page>
</template>

<script>
import { ref, computed, onMounted } from 'vue'
import { api } from 'boot/axios'
import { useRouter, useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useQuasar } from 'quasar'
import { logger } from 'src/utils/logger'

export default {
  setup() {
    const router = useRouter()
    const route = useRoute()
    const { t } = useI18n()
    const $q = useQuasar()

    const isEditMode = computed(() => !!route.params.guid)
    const tKey = computed(() => (isEditMode.value ? 'editIndexer' : 'createIndexer'))
    // i18n key differences between create/edit trees
    const nameRuleKey = computed(() => (isEditMode.value ? 'nameRequired' : 'name'))
    const hostRuleKey = computed(() => (isEditMode.value ? 'urlRequired' : 'hostUrl'))

    const step = ref(1)
    const loading = ref(isEditMode.value)
    const saving = ref(false)
    const testingConnection = ref(false)
    const showApiKey = ref(false)
    const connectionResult = ref(null)
    const availableCategories = ref([])
    const selectedCategories = ref([])
    const savedCategories = ref([])
    const stepOneForm = ref(null)
    // Edit-mode signal from backend: there is already an api_key on file,
    // form starts empty and only replaces it when admin types something.
    const apiKeyConfigured = ref(false)

    const indexerForm = ref({
      label: '',
      host: '',
      api_key: '',
      type: 'newznab',
      ssl: false,
      verify_ssl: true,
      enabled: true,
      rss_enabled: false,
      priority: 25,
    })
    const lastRssSyncAt = ref(null)

    const indexerTypes = computed(() =>
      isEditMode.value
        ? [
            { label: t('editIndexer.newznab'), value: 'newznab' },
            { label: t('editIndexer.torznab'), value: 'torznab' },
          ]
        : [
            { label: 'Newznab (Usenet)', value: 'newznab' },
            { label: 'Torznab (Torrent)', value: 'torznab' },
          ],
    )

    const categoryTypes = computed(() => [
      { label: t(`${tKey.value}.movies`), value: 'movie' },
      { label: t(`${tKey.value}.series`), value: 'show' },
      { label: t(`${tKey.value}.music`), value: 'music' },
      { label: t(`${tKey.value}.games`), value: 'game' },
      { label: t(`${tKey.value}.books`), value: 'book' },
      { label: t(`${tKey.value}.audiobooks`), value: 'audiobook' },
      { label: t(`${tKey.value}.other`), value: 'other' },
    ])

    const languageOptions = computed(() => [
      { label: t(`${tKey.value}.german`), value: 'de' },
      { label: t(`${tKey.value}.english`), value: 'en' },
      { label: t(`${tKey.value}.french`), value: 'fr' },
      { label: t(`${tKey.value}.spanish`), value: 'es' },
      { label: t(`${tKey.value}.italian`), value: 'it' },
      { label: t(`${tKey.value}.portuguese`), value: 'pt' },
      { label: t(`${tKey.value}.russian`), value: 'ru' },
      { label: t(`${tKey.value}.japanese`), value: 'ja' },
      { label: t(`${tKey.value}.korean`), value: 'ko' },
      { label: t(`${tKey.value}.chinese`), value: 'zh' },
    ])

    const resolutionOptions = [
      { label: 'SD (480p)', value: '480p' },
      { label: 'HD (720p)', value: '720p' },
      { label: 'Full HD (1080p)', value: '1080p' },
      { label: '4K (2160p)', value: '2160p' },
    ]

    const apiKeyHint = computed(() => {
      if (!isEditMode.value) return undefined
      return apiKeyConfigured.value
        ? t('editIndexer.apiKeyKeepHint')
        : t('editIndexer.apiKeyRequired')
    })

    const apiKeyRules = computed(() =>
      isEditMode.value
        ? [
            (val) =>
              apiKeyConfigured.value || (val && val.length > 0) || t('editIndexer.apiKeyRequired'),
          ]
        : [(val) => (val && val.length > 0) || t('createIndexer.apiKey')],
    )

    // When caps are fetched in edit-mode, restore previously saved category selections
    const syncSavedToSelected = () => {
      selectedCategories.value = []
      for (const saved of savedCategories.value) {
        if (saved.newznab_category_id != null) {
          selectedCategories.value.push({ ...saved })
        }
      }
    }

    const effectiveCategoryCount = computed(() => {
      if (availableCategories.value.length > 0) {
        return selectedCategories.value.length
      }
      return savedCategories.value.length
    })

    const isSelected = (id) => selectedCategories.value.some((c) => c.newznab_category_id === id)

    const getSelectedCategory = (id) =>
      selectedCategories.value.find((c) => c.newznab_category_id === id)

    const autoDetectType = (id) => {
      if (id >= 2000 && id < 3000) return 'movie'
      if (id >= 5000 && id < 6000) return 'show'
      if (id >= 3000 && id < 3500) return 'music'
      if (id >= 6000 && id < 7000) return 'game'
      if (id >= 7000 && id < 8000) return 'book'
      return 'other'
    }

    const toggleCategory = (sub, parentCat, selected) => {
      if (selected) {
        // In edit-mode, prefill from previously saved category if present.
        const existing = isEditMode.value
          ? savedCategories.value.find((s) => s.newznab_category_id === sub.id)
          : null
        selectedCategories.value.push({
          newznab_category_id: sub.id,
          label: sub.name || `${parentCat.name} - ${sub.name}`,
          category_type: existing?.category_type || autoDetectType(sub.id),
          language: existing?.language || [],
          resolution: existing?.resolution || [],
          platform: null,
        })
      } else {
        selectedCategories.value = selectedCategories.value.filter(
          (c) => c.newznab_category_id !== sub.id,
        )
      }
    }

    const fetchCaps = async () => {
      const resp = await api.post('/api/indexers/caps', {
        host: indexerForm.value.host,
        api_key: indexerForm.value.api_key,
        ssl: indexerForm.value.ssl,
        verify_ssl: indexerForm.value.verify_ssl,
        plugin_type: indexerForm.value.type,
      })
      return resp.data
    }

    const testConnection = async () => {
      const isValid = await stepOneForm.value.validate()
      if (!isValid) return

      if (connectionResult.value && connectionResult.value.connected) {
        step.value = 2
        return
      }

      testingConnection.value = true
      connectionResult.value = null
      try {
        const data = await fetchCaps()
        connectionResult.value = data
        if (data.connected) {
          availableCategories.value = data.categories || []
          if (isEditMode.value) syncSavedToSelected()
          setTimeout(() => {
            step.value = 2
          }, 800)
        }
      } catch (err) {
        logger.warn('Indexer connection test failed', err)
        connectionResult.value = {
          connected: false,
          error: err.response?.data?.detail || err.message,
        }
      } finally {
        testingConnection.value = false
      }
    }

    const fetchCapsOnly = async () => {
      testingConnection.value = true
      try {
        const data = await fetchCaps()
        if (data.connected) {
          availableCategories.value = data.categories || []
          syncSavedToSelected()
        } else {
          $q.notify({
            type: 'negative',
            message: data.error || t(`${tKey.value}.connectionFailed`),
          })
        }
      } catch (err) {
        logger.error('Failed to reload indexer caps', err)
        $q.notify({
          type: 'negative',
          message: err?.response?.data?.detail || t(`${tKey.value}.connectionFailed`),
        })
      } finally {
        testingConnection.value = false
      }
    }

    const loadIndexer = async () => {
      try {
        const indexerGuid = route.params.guid
        const response = await api.get(`/api/indexers/${indexerGuid}`)
        const indexer = response.data

        // api_key is never returned from the server; only the "configured" flag.
        apiKeyConfigured.value = !!indexer.api_key_configured
        indexerForm.value = {
          label: indexer.label || '',
          host: indexer.host || '',
          api_key: '',
          type: indexer.type || 'newznab',
          ssl: indexer.ssl || false,
          verify_ssl: indexer.verify_ssl !== false,
          enabled: indexer.enabled !== false,
          rss_enabled: !!indexer.rss_enabled,
          priority: indexer.priority ?? 25,
        }
        lastRssSyncAt.value = indexer.last_rss_sync_at || null

        savedCategories.value = (indexer.categories || []).map((c) => ({ ...c }))
      } catch (e) {
        // Indexer not found or fetch failed; navigate back to list
        logger.error('Failed to load indexer for editing, redirecting', e)
        router.push('/admin/indexers')
      } finally {
        loading.value = false
      }
    }

    const buildCategoriesPayload = (categories) =>
      categories.map((c) => ({
        label: c.label,
        category_type: c.category_type,
        newznab_category_id: c.newznab_category_id,
        language: c.language || null,
        resolution: c.resolution || null,
        platform: c.platform || null,
      }))

    const saveIndexer = async () => {
      try {
        saving.value = true

        // Edit mode: keep previously saved categories when admin didn't (re)load caps.
        const categoriesToSave =
          isEditMode.value && availableCategories.value.length === 0
            ? savedCategories.value
            : selectedCategories.value

        const payload = {
          label: indexerForm.value.label,
          host: indexerForm.value.host,
          type: indexerForm.value.type,
          ssl: indexerForm.value.ssl,
          verify_ssl: indexerForm.value.verify_ssl,
          enabled: indexerForm.value.enabled,
          rss_enabled: indexerForm.value.rss_enabled,
          priority: indexerForm.value.priority,
          categories: buildCategoriesPayload(categoriesToSave),
        }

        if (isEditMode.value) {
          // Only send api_key when admin actually typed something; backend
          // treats empty/omitted as "keep the existing secret".
          if (indexerForm.value.api_key && indexerForm.value.api_key.length > 0) {
            payload.api_key = indexerForm.value.api_key
          }
          await api.put(`/api/indexers/${route.params.guid}`, payload)
        } else {
          payload.api_key = indexerForm.value.api_key
          await api.post('/api/indexers/', payload)
        }

        router.push('/admin/indexers')
      } catch (err) {
        logger.error('Failed to save indexer', err)
        const detail = err?.response?.data?.detail || t(`${tKey.value}.saveError`)
        $q.notify({ type: 'negative', message: detail })
      } finally {
        saving.value = false
      }
    }

    onMounted(() => {
      if (isEditMode.value) {
        loadIndexer()
      }
    })

    return {
      isEditMode,
      tKey,
      nameRuleKey,
      hostRuleKey,
      step,
      loading,
      saving,
      testingConnection,
      showApiKey,
      connectionResult,
      availableCategories,
      selectedCategories,
      savedCategories,
      effectiveCategoryCount,
      apiKeyConfigured,
      apiKeyHint,
      apiKeyRules,
      indexerForm,
      lastRssSyncAt,
      indexerTypes,
      categoryTypes,
      languageOptions,
      resolutionOptions,
      stepOneForm,
      isSelected,
      getSelectedCategory,
      toggleCategory,
      testConnection,
      fetchCapsOnly,
      saveIndexer,
    }
  },
}
</script>

<style scoped>
.category-row {
  transition: background 0.15s;
}
.category-row.selected {
  border-left: 3px solid var(--q-primary);
  border-radius: 4px;
}
</style>
