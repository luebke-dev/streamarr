<template>
  <q-page padding>
    <div class="q-pa-md" style="max-width: 800px; margin: 0 auto">
      <div class="text-h4 q-mb-md">{{ $t('adminLibrary.createLibrary') }}</div>

      <q-form @submit="createLibrary" class="q-gutter-md">
        <!-- Library Name -->
        <q-input
          v-model="library.name"
          :label="$t('adminLibrary.libraryName')"
          :hint="$t('adminLibrary.libraryNameHint')"
          outlined
          required
          :rules="[(val) => !!val || $t('adminLibrary.libraryNameRequired')]"
        />

        <!-- Library Type -->
        <q-select
          v-model="library.type"
          :options="libraryTypes"
          :label="$t('adminLibrary.libraryType')"
          :hint="$t('adminLibrary.libraryTypeHint')"
          outlined
          required
          emit-value
          map-options
          :loading="loadingLibraryTypes"
          :rules="[(val) => !!val || $t('adminLibrary.libraryTypeRequired')]"
        >
          <template v-slot:prepend>
            <q-icon :name="getLibraryIcon(library.type)" />
          </template>
        </q-select>

        <!-- Plugin Selection -->
        <q-select
          v-model="library.plugin_id"
          :options="availablePlugins"
          :label="$t('adminLibrary.libraryPlugin')"
          :hint="$t('adminLibrary.libraryPluginHint')"
          outlined
          required
          emit-value
          map-options
          :loading="loadingPlugins"
          :disable="!library.type"
          :rules="[(val) => !!val || $t('adminLibrary.libraryPluginRequired')]"
        >
          <template v-slot:prepend>
            <q-icon name="mdi-puzzle" />
          </template>
        </q-select>

        <!-- Metadata Provider Selection -->
        <q-select
          v-model="library.metadata_provider"
          :options="availableMetadataProviders"
          :label="$t('adminLibrary.metadataProvider')"
          :hint="$t('adminLibrary.metadataProviderHint')"
          outlined
          emit-value
          map-options
          :loading="loadingMetadataProviders"
          :disable="!library.type"
          clearable
        >
          <template v-slot:prepend>
            <q-icon name="mdi-cloud-search" />
          </template>
          <template v-slot:no-option>
            <q-item>
              <q-item-section class="text-grey">
                {{ $t('adminLibrary.noMetadataProvidersAvailable') }}
              </q-item-section>
            </q-item>
          </template>
          <template v-slot:option="scope">
            <q-item v-bind="scope.itemProps">
              <q-item-section>
                <q-item-label>{{ scope.opt.label }}</q-item-label>
                <q-item-label caption>{{ scope.opt.description }}</q-item-label>
              </q-item-section>
              <q-item-section side>
                <q-badge
                  v-if="!scope.opt.configured"
                  color="orange"
                  :label="$t('adminLibrary.notConfigured')"
                />
              </q-item-section>
            </q-item>
          </template>
        </q-select>

        <!-- Library Path -->
        <q-input
          v-model="library.path"
          :label="$t('adminLibrary.libraryPath')"
          :hint="$t('adminLibrary.libraryPathHint')"
          outlined
          required
          :rules="[(val) => !!val || $t('adminLibrary.libraryPathRequired')]"
        >
          <template v-slot:prepend>
            <q-icon name="mdi-folder" />
          </template>
          <template v-slot:append>
            <q-btn flat dense icon="mdi-information" color="info" @click="showPathInfo">
              <q-tooltip>{{ $t('adminLibrary.pathInfoTooltip') }}</q-tooltip>
            </q-btn>
          </template>
        </q-input>

        <!-- Description -->
        <q-input
          v-model="library.description"
          :label="$t('adminLibrary.libraryDescription')"
          :hint="$t('adminLibrary.libraryDescriptionHint')"
          outlined
          type="textarea"
          rows="3"
        />

        <!-- Enabled Toggle -->
        <q-toggle
          v-model="library.enabled"
          :label="$t('adminLibrary.libraryEnabled')"
          color="positive"
        />

        <!-- Action Buttons -->
        <div class="row q-gutter-sm">
          <q-btn
            type="submit"
            color="primary"
            :label="$t('common.create')"
            :loading="saving"
            icon="mdi-plus"
          />
          <q-btn
            flat
            color="grey-7"
            :label="$t('common.cancel')"
            @click="$router.back()"
            :disable="saving"
          />
        </div>
      </q-form>
    </div>
  </q-page>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import { api } from 'boot/axios'
import { logger } from 'src/utils/logger'

const router = useRouter()
const $q = useQuasar()
const { t } = useI18n()

const library = ref({
  name: '',
  type: '',
  plugin_id: '',
  metadata_provider: '',
  path: '',
  description: '',
  enabled: true,
})

const saving = ref(false)
const loadingPlugins = ref(false)
const loadingMetadataProviders = ref(false)
const plugins = ref([])
const metadataProviders = ref([])

const availablePlugins = computed(() => {
  if (!library.value.type) return []

  return plugins.value
    .filter((p) => p.library_type.toUpperCase() === library.value.type)
    .map((p) => ({
      label: `${p.name} (${p.version})`,
      value: p.id,
      description: p.description,
    }))
})

const availableMetadataProviders = computed(() => {
  if (!library.value.type) return []

  return metadataProviders.value
    .filter((p) => p.supported_media_types && p.supported_media_types.includes(library.value.type))
    .map((p) => ({
      label: `${p.name}`,
      value: p.domain,
      description: p.description,
      configured: p.configured,
    }))
})

// Watch for type changes to load plugins
watch(
  () => library.value.type,
  async (newType) => {
    if (newType) {
      library.value.plugin_id = '' // Reset plugin selection
      library.value.metadata_provider = '' // Reset metadata provider selection
      await Promise.all([loadPlugins(newType), loadMetadataProviders(newType)])
    }
  },
)

async function loadPlugins(type) {
  loadingPlugins.value = true
  try {
    const response = await api.get('/api/libraries/plugins', {
      params: { library_type: type },
    })
    plugins.value = response.data

    // Auto-select if only one plugin available
    if (plugins.value.length === 1) {
      library.value.plugin_id = plugins.value[0].id
    }
  } catch (error) {
    logger.error('Failed to load plugins:', error)
  } finally {
    loadingPlugins.value = false
  }
}

async function loadMetadataProviders(type) {
  loadingMetadataProviders.value = true
  try {
    const response = await api.get('/api/libraries/metadata-providers', {
      params: { library_type: type },
    })
    metadataProviders.value = response.data.metadata_providers || []

    // Auto-select if only one provider available and configured
    const configuredProviders = metadataProviders.value.filter((p) => p.configured)
    if (configuredProviders.length === 1) {
      library.value.metadata_provider = configuredProviders[0].domain
    }
  } catch (error) {
    logger.error('Failed to load metadata providers:', error)
  } finally {
    loadingMetadataProviders.value = false
  }
}

// Load available library types from API
const libraryTypes = ref([])
const loadingLibraryTypes = ref(false)

async function loadLibraryTypes() {
  loadingLibraryTypes.value = true
  try {
    const response = await api.get('/api/libraries/types')
    libraryTypes.value = response.data.map((type) => ({
      label: type.label,
      value: type.type,
      description: type.description,
      icon: getLibraryIcon(type.type),
    }))
  } catch (error) {
    logger.error('Failed to load library types:', error)
  } finally {
    loadingLibraryTypes.value = false
  }
}

function getLibraryIcon(type) {
  const icons = {
    MOVIES: 'mdi-movie',
    SHOWS: 'mdi-television',
    GAMES: 'mdi-gamepad-variant',
    MUSIC: 'mdi-music',
    BOOKS: 'mdi-book',
    AUDIOBOOKS: 'mdi-book-music',
  }
  return icons[type] || 'mdi-folder'
}

function showPathInfo() {
  $q.dialog({
    title: t('adminLibrary.pathInfo'),
    message: t('adminLibrary.pathInfoMessage'),
    html: true,
  })
}

async function createLibrary() {
  saving.value = true
  try {
    await api.post('/api/libraries', library.value)

    // Redirect to library settings page (convert type to lowercase for URL)
    router.push(`/admin/libraries/${library.value.type.toLowerCase()}`)
  } catch (error) {
    logger.error('Failed to create library:', error)

    // Handle duplicate library type error (409 Conflict)
    if (error.response?.status === 409) {
      // silently ignore
    } else {
      // silently ignore
    }
  } finally {
    saving.value = false
  }
}

// Load library types on mount
onMounted(() => {
  loadLibraryTypes()
})
</script>
