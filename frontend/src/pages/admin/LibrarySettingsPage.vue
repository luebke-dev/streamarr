<template>
  <q-page class="q-pa-md">
    <div class="text-h4 q-mb-md">{{ pageTitle }}</div>

    <!-- Library Configuration Card -->
    <q-card flat bordered class="q-mb-md">
      <q-card-section>
        <div class="text-h6 q-mb-md">{{ $t('adminLibrary.libraryConfiguration') }}</div>

        <q-form @submit="saveSettings" class="q-gutter-md">
          <q-list>
            <q-item>
              <q-toggle
                v-model="settings.enable_library"
                :label="enableLibraryLabel"
                color="positive"
              />
            </q-item>
            <q-item class="full-width">
              <q-input
                filled
                v-model="settings.library_path"
                :label="$t('adminLibrary.libraryPath')"
                :hint="$t('adminLibrary.libraryPathHint')"
                lazy-rules
                :rules="[
                  (val) => (val && val.length > 0) || $t('adminLibrary.libraryPathRequired'),
                ]"
              >
                <template v-slot:prepend>
                  <q-icon name="mdi-folder" />
                </template>
              </q-input>
            </q-item>
            <q-item
              v-if="mediaType && ['movies', 'shows', 'music'].includes(mediaType.toLowerCase())"
            >
              <q-toggle
                v-model="settings.enable_on_demand_downloads"
                :label="$t('adminLibrary.enableOnDemandDownloads')"
                color="positive"
              />
            </q-item>
            <!-- Show-specific settings -->
            <template v-if="mediaType && mediaType.toLowerCase() === 'shows'">
              <q-item>
                <q-toggle
                  v-model="settings.enable_prefetch_downloads"
                  :label="$t('adminLibrary.enablePrefetchDownloads')"
                  color="positive"
                />
              </q-item>
              <q-item>
                <q-toggle
                  v-model="settings.hide_season_zero"
                  :label="$t('adminLibrary.hideSeasonZero')"
                  color="positive"
                />
                <q-item-section side>
                  <q-icon name="mdi-help-circle-outline" color="grey" size="sm">
                    <q-tooltip>{{ $t('adminLibrary.hideSeasonZeroHint') }}</q-tooltip>
                  </q-icon>
                </q-item-section>
              </q-item>
            </template>
            <!-- Allowed Languages (movies + shows only) -->
            <template v-if="mediaType && ['movies', 'shows'].includes(mediaType.toLowerCase())">
              <q-item class="full-width">
                <q-select
                  v-model="settings.allowed_languages"
                  :options="availableLanguageOptions"
                  :label="$t('adminLibrary.allowedLanguages')"
                  :hint="$t('adminLibrary.allowedLanguagesHint')"
                  multiple
                  use-chips
                  emit-value
                  map-options
                  outlined
                  dense
                  clearable
                  style="width: 100%"
                >
                  <template v-slot:prepend>
                    <q-icon name="mdi-translate" />
                  </template>
                </q-select>
              </q-item>
            </template>
            <!-- Allowed Platforms (games only) -->
            <template v-if="mediaType && mediaType.toLowerCase() === 'games'">
              <q-item class="full-width">
                <q-select
                  v-model="settings.allowed_platforms"
                  :options="availablePlatformOptions"
                  :label="$t('adminLibrary.allowedPlatforms')"
                  :hint="$t('adminLibrary.allowedPlatformsHint')"
                  multiple
                  use-chips
                  emit-value
                  map-options
                  outlined
                  dense
                  clearable
                  style="width: 100%"
                >
                  <template v-slot:prepend>
                    <q-icon name="mdi-gamepad-variant" />
                  </template>
                </q-select>
              </q-item>
            </template>
          </q-list>
          <div class="row q-gutter-md">
            <q-btn
              color="primary"
              :label="$t('adminLibrary.saveSettings')"
              type="submit"
              :loading="saving"
              :disable="!hasChanges"
            />
            <q-btn
              color="grey-7"
              :label="$t('adminLibrary.reset')"
              @click="resetSettings"
              :disable="!hasChanges"
            />
          </div>
        </q-form>
      </q-card-section>
    </q-card>

    <!-- Naming Settings Card -->
    <q-card flat bordered class="q-mb-md">
      <q-card-section>
        <div class="text-h6 q-mb-md">{{ $t('adminLibrary.namingSettings') }}</div>

        <FormBanner
          v-if="!namingSchema"
          type="info"
          :message="$t('adminLibrary.loadingSchema')"
          no-margin
          class="q-mb-md"
        />

        <q-form v-if="namingSchema" @submit="saveSettings" class="q-gutter-md">
          <!-- Dynamic template fields based on schema.defaults -->
          <div
            v-for="(defaultValue, templateKey) in namingSchema.defaults"
            :key="templateKey"
            class="q-mb-md"
          >
            <q-input
              v-model="namingSettings[templateKey]"
              :label="getTemplateLabel(templateKey)"
              filled
              :hint="getTemplateHint()"
            >
              <template v-slot:append>
                <q-btn
                  flat
                  round
                  dense
                  icon="mdi-help-circle"
                  @click="showVariablesDialog = true"
                />
              </template>
            </q-input>
          </div>

          <!-- Naming options -->
          <q-toggle
            v-model="namingSettings.replace_illegal_characters"
            :label="$t('adminLibrary.replaceIllegalCharacters')"
            color="primary"
          />

          <q-select
            v-model="namingSettings.colon_replacement"
            :options="colonReplacementOptions"
            :label="$t('adminLibrary.colonReplacement')"
            filled
            emit-value
            map-options
          />

          <!-- Preview Section -->
          <div class="q-mt-md">
            <div class="text-subtitle2 q-mb-sm">{{ $t('adminLibrary.preview') }}</div>
            <q-card flat bordered>
              <q-card-section>
                <div v-if="namingPreview.folder" class="q-mb-sm">
                  <strong>{{ $t('adminLibrary.folderPreview') }}:</strong>
                  {{ namingPreview.folder }}
                </div>
                <div v-if="namingPreview.file" class="q-mb-sm">
                  <strong>{{ $t('adminLibrary.filePreview') }}:</strong> {{ namingPreview.file }}
                </div>
                <div v-if="namingPreview.full_path">
                  <strong>{{ $t('adminLibrary.fullPathPreview') }}:</strong>
                  {{ namingPreview.full_path }}
                </div>
              </q-card-section>
            </q-card>
          </div>

          <div class="row q-gutter-md">
            <q-btn
              color="primary"
              :label="$t('adminLibrary.saveNamingSettings')"
              type="submit"
              :loading="saving"
            />
            <q-btn
              color="secondary"
              :label="$t('adminLibrary.previewNaming')"
              @click="previewNaming"
              :loading="previewing"
            />
            <q-btn
              color="grey-7"
              :label="$t('adminLibrary.resetToDefaults')"
              @click="resetNamingToDefaults"
            />
          </div>
        </q-form>
      </q-card-section>
    </q-card>

    <!-- Scoring Configuration Card (only for video libraries) -->
    <q-card
      v-if="mediaType && ['movies', 'shows'].includes(mediaType.toLowerCase())"
      flat
      bordered
      class="q-mb-md"
    >
      <q-card-section>
        <div class="text-h6 q-mb-md">
          <q-icon name="mdi-trophy-award" class="q-mr-sm" />
          {{ $t('scoringRules.title') }}
        </div>
        <div class="text-caption text-grey-6 q-mb-md">{{ $t('scoringRules.description') }}</div>

        <ScoringConfigPanel
          v-if="scoringConfig"
          :config="scoringConfig"
          :media-type="mediaType.toLowerCase()"
          :saving="savingScoring"
          @save="saveScoring"
          @reset="resetScoring"
        />
        <q-spinner v-else-if="loadingScoring" size="2rem" class="q-mt-md" />
      </q-card-section>
    </q-card>

    <!-- Quality Profile Card (all downloadable media types) -->
    <q-card v-if="showQualityProfile" flat bordered class="q-mb-md">
      <q-card-section>
        <div class="text-h6 q-mb-md">
          <q-icon name="mdi-tune-vertical" class="q-mr-sm" />
          {{ $t('qualityProfile.title') }}
        </div>
        <div class="text-caption text-grey-6 q-mb-md">
          {{ $t('qualityProfile.description') }}
        </div>

        <q-tabs
          v-model="qpTab"
          dense
          align="left"
          class="text-grey-6 q-mb-md"
          active-color="primary"
          indicator-color="primary"
        >
          <q-tab name="standard" :label="$t('qualityProfile.tabStandard')" />
          <q-tab name="favorites" :label="$t('qualityProfile.tabFavorites')" />
        </q-tabs>

        <q-tab-panels v-model="qpTab" animated>
          <q-tab-panel name="standard" class="q-pa-none">
            <QualityProfilePanel
              v-if="qualityProfileStd"
              :profile="qualityProfileStd"
              :qualities="qualityLadder"
              :saving="savingQP"
              variant="standard"
              @save="(p) => saveQualityProfile('standard', p)"
              @reset="resetQualityProfile('standard')"
            />
            <q-spinner v-else-if="loadingQP" size="2rem" class="q-mt-md" />
          </q-tab-panel>

          <q-tab-panel name="favorites" class="q-pa-none">
            <div class="text-caption text-grey-6 q-mb-sm">
              {{ $t('qualityProfile.favoritesHint') }}
            </div>
            <QualityProfilePanel
              v-if="qualityProfileFav"
              :profile="qualityProfileFav"
              :qualities="qualityLadder"
              :saving="savingQP"
              variant="favorites"
              @save="(p) => saveQualityProfile('favorites', p)"
              @reset="resetQualityProfile('favorites')"
            />
            <q-spinner v-else-if="loadingQP" size="2rem" class="q-mt-md" />
          </q-tab-panel>
        </q-tab-panels>
      </q-card-section>
    </q-card>

    <!-- Danger Zone -->
    <q-card flat bordered class="q-mb-md">
      <q-card-section>
        <div class="text-h6 text-negative q-mb-md">
          <q-icon name="mdi-alert" class="q-mr-sm" />
          {{ $t('adminLibrary.dangerZone') }}
        </div>
        <q-btn
          color="negative"
          :label="$t('adminLibrary.deleteLibrary')"
          icon="mdi-delete"
          @click="confirmDeleteLibrary"
          :loading="deleting"
        />
      </q-card-section>
    </q-card>

    <!-- Variables Help Dialog -->
    <q-dialog v-model="showVariablesDialog">
      <q-card style="min-width: 500px">
        <q-card-section>
          <div class="text-h6">{{ $t('adminLibrary.availableVariables') }}</div>
        </q-card-section>

        <q-card-section class="q-pt-none" style="max-height: 500px; overflow-y: auto">
          <q-list bordered separator>
            <q-item v-for="variable in namingSchema?.variables || []" :key="variable.name">
              <q-item-section>
                <q-item-label>
                  <code>{{ '{' + variable.name + '}' }}</code>
                </q-item-label>
                <q-item-label caption>{{ variable.description }}</q-item-label>
                <q-item-label caption class="text-positive">
                  {{ $t('adminLibrary.example') }}: {{ variable.example }}
                </q-item-label>
              </q-item-section>
            </q-item>
          </q-list>
        </q-card-section>

        <q-card-actions align="right">
          <q-btn flat :label="$t('common.close')" color="primary" v-close-popup />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useQuasar } from 'quasar'
import {
  getPlatforms,
  getLibrary,
  deleteLibrary as deleteLibraryRequest,
  getLibraryConfig,
  saveLibraryConfig,
  previewNaming as previewNamingRequest,
  getScoring,
  saveScoring as saveScoringRequest,
  resetScoring as resetScoringRequest,
  getQualityLadder,
  getQualityProfile,
  saveQualityProfile as saveQualityProfileRequest,
  resetQualityProfile as resetQualityProfileRequest,
} from 'src/services/libraryAdminService'
import { useI18n } from 'vue-i18n'
import ScoringConfigPanel from 'components/admin/ScoringConfigPanel.vue'
import QualityProfilePanel from 'components/admin/QualityProfilePanel.vue'
import FormBanner from 'src/components/FormBanner.vue'
import { useRouter } from 'vue-router'
import { logger } from 'src/utils/logger'

const props = defineProps({
  libraryId: {
    type: String,
    required: true,
  },
})

// libraryId can be a UUID (legacy) or a type name like "movies"
const isTypeName = computed(() => {
  const knownTypes = ['movies', 'shows', 'games', 'music', 'books', 'audiobooks']
  return knownTypes.includes(props.libraryId.toLowerCase())
})

const $q = useQuasar()
const { t } = useI18n()
const router = useRouter()

// State
const library = ref(null)
const mediaType = ref(null)
const settings = ref({
  enable_library: false,
  library_path: '',
  enable_on_demand_downloads: false,
  enable_prefetch_downloads: false,
  hide_season_zero: false,
  allowed_languages: [],
})

const originalSettings = ref({})
const namingSettings = ref({})
const originalNamingSettings = ref({})
const namingSchema = ref(null)
const namingPreview = ref({})

const saving = ref(false)
const previewing = ref(false)
const showVariablesDialog = ref(false)

// Scoring state
const scoringConfig = ref(null)
const loadingScoring = ref(false)
const savingScoring = ref(false)
const deleting = ref(false)

// Quality profile state (Sonarr-style ordered list + cutoff)
const qualityLadder = ref([])
const qualityProfileStd = ref(null)
const qualityProfileFav = ref(null)
const qpTab = ref('standard')
const loadingQP = ref(false)
const savingQP = ref(false)
const QP_TYPES = ['movies', 'shows', 'music', 'books', 'games']
const showQualityProfile = computed(
  () => lcType.value && QP_TYPES.includes(lcType.value),
)

// Computed
// Centralized media-type metadata so page title, banner label and the
// per-type API endpoints all derive from one place. Keys mirror the
// lowercase `mediaType` value coming from the backend.
const MEDIA_TYPE_META = {
  movies: { nameKey: 'movies', enableLabelKey: 'adminLibrary.enableMovieLibrary' },
  shows: { nameKey: 'shows', enableLabelKey: 'adminLibrary.enableShowLibrary' },
  games: { nameKey: 'games', enableLabelKey: 'adminLibrary.enableGamesLibrary' },
  music: { nameKey: 'music', enableLabelKey: 'adminLibrary.enableMusicLibrary' },
  books: { nameKey: 'books', enableLabelKey: 'adminLibrary.enableBooksLibrary' },
  audiobooks: { nameKey: 'audiobooks', enableLabelKey: 'adminLibrary.enableShowLibrary' },
}

const lcType = computed(() => mediaType.value?.toLowerCase() || null)

const pageTitle = computed(() => {
  const meta = MEDIA_TYPE_META[lcType.value]
  if (meta) return t(meta.nameKey)
  if (!library.value) return t('common.loading')
  const fallback = MEDIA_TYPE_META[library.value.type?.toLowerCase()]
  return fallback ? t(fallback.nameKey) : library.value.type
})

const enableLibraryLabel = computed(() => {
  const meta = MEDIA_TYPE_META[lcType.value]
  return t(meta?.enableLabelKey || 'adminLibrary.enableShowLibrary')
})

const hasChanges = computed(() => {
  return JSON.stringify(settings.value) !== JSON.stringify(originalSettings.value)
})

const colonReplacementOptions = computed(() => [
  { label: t('adminLibrary.colonSpace'), value: ' ' },
  { label: t('adminLibrary.colonDash'), value: ' - ' },
  { label: t('adminLibrary.colonDelete'), value: '' },
])

const availableLanguageOptions = computed(() => [
  { label: 'German (de)', value: 'de' },
  { label: 'English (en)', value: 'en' },
  { label: 'French (fr)', value: 'fr' },
  { label: 'Spanish (es)', value: 'es' },
  { label: 'Italian (it)', value: 'it' },
  { label: 'Japanese (ja)', value: 'ja' },
  { label: 'Chinese (zh)', value: 'zh' },
  { label: 'Korean (ko)', value: 'ko' },
  { label: 'Dutch (nl)', value: 'nl' },
  { label: 'Portuguese (pt)', value: 'pt' },
  { label: 'Russian (ru)', value: 'ru' },
  { label: 'Multi / Dual Language', value: 'multi' },
])

const availablePlatformOptions = ref([])

async function loadPlatformOptions() {
  try {
    const data = await getPlatforms()
    availablePlatformOptions.value = (data || []).map((p) => ({ label: p.name, value: p.name }))
  } catch (e) {
    // Platform options are an optional dropdown; tolerate failures
    logger.warn('Failed to load platform options', e)
  }
}

// Methods
const getTemplateLabel = (key) => {
  const labelMap = {
    folder: t('adminLibrary.folderTemplate'),
    file: t('adminLibrary.fileTemplate'),
    series_folder: t('adminLibrary.seriesFolderTemplate'),
    season_folder: t('adminLibrary.seasonFolderTemplate'),
  }
  return labelMap[key] || key
}

const getTemplateHint = () => {
  if (!namingSchema.value) return ''
  const variables = namingSchema.value.variables
    .slice(0, 3)
    .map((v) => `{${v.name}}`)
    .join(', ')
  return `${t('adminLibrary.useVariables')}: ${variables}...`
}

const loadSettings = async () => {
  try {
    // Determine library type
    if (!library.value) {
      if (isTypeName.value) {
        // Navigate by type name — set type directly
        mediaType.value = props.libraryId.toUpperCase()
        library.value = { type: mediaType.value, name: props.libraryId }
      } else {
        // Navigate by GUID (legacy)
        library.value = await getLibrary(props.libraryId)
        mediaType.value = library.value.type
      }
    }

    // New unified API endpoint - config suffix for type-specific settings
    const data = await getLibraryConfig(lcType.value)

    // Extract library settings from response
    const { naming, ...librarySettings } = data
    settings.value = { ...librarySettings }
    originalSettings.value = { ...librarySettings }

    // Extract naming configuration
    if (naming) {
      namingSchema.value = naming.schema

      // Initialize naming settings from current values (includes defaults)
      namingSettings.value = { ...naming.current }
      originalNamingSettings.value = { ...naming.current }
    }
  } catch (error) {
    logger.error('Failed to load settings:', error)
  }
  await loadScoring()
  await loadQualityProfiles()
}

const saveSettings = async () => {
  saving.value = true
  try {
    // Combine library settings and naming templates in one request
    await saveLibraryConfig(lcType.value, {
      ...settings.value,
      naming: namingSettings.value,
    })
    originalSettings.value = { ...settings.value }
    originalNamingSettings.value = { ...namingSettings.value }
  } catch (error) {
    logger.error('Failed to save settings:', error)
  } finally {
    saving.value = false
  }
}

const resetSettings = () => {
  settings.value = { ...originalSettings.value }
  namingSettings.value = { ...originalNamingSettings.value }
}

const previewNaming = async () => {
  previewing.value = true
  try {
    namingPreview.value = await previewNamingRequest(lcType.value, namingSettings.value)
  } catch (error) {
    logger.error('Failed to preview naming:', error)
  } finally {
    previewing.value = false
  }
}

const resetNamingToDefaults = () => {
  if (namingSchema.value) {
    const defaults = namingSchema.value.defaults || {}
    const options = namingSchema.value.options || {}

    namingSettings.value = {
      ...defaults,
      replace_illegal_characters: options.replace_illegal_characters ?? true,
      colon_replacement: options.colon_replacement ?? ' - ',
    }
  }
}

const loadScoring = async () => {
  if (!['movies', 'shows'].includes(lcType.value)) return
  loadingScoring.value = true
  try {
    scoringConfig.value = await getScoring(lcType.value)
  } catch (error) {
    logger.error('Failed to load scoring config:', error)
  } finally {
    loadingScoring.value = false
  }
}

const saveScoring = async (config) => {
  savingScoring.value = true
  try {
    scoringConfig.value = await saveScoringRequest(lcType.value, config)
    $q.notify({ type: 'positive', message: t('scoringRules.saveSuccess') })
  } catch (error) {
    logger.error('Failed to save scoring config:', error)
    $q.notify({ type: 'negative', message: t('scoringRules.saveError') })
  } finally {
    savingScoring.value = false
  }
}

const confirmDeleteLibrary = () => {
  $q.dialog({
    title: t('adminLibrary.deleteLibraryTitle'),
    message: t('adminLibrary.deleteLibraryConfirm', { name: library.value?.name }),
    ok: { label: t('adminLibrary.deleteLibrary'), color: 'negative' },
    cancel: { label: t('common.cancel'), flat: true },
  }).onOk(async () => {
    deleting.value = true
    try {
      await deleteLibraryRequest(props.libraryId)
      router.push('/admin')
    } catch (error) {
      logger.error('Failed to delete library:', error)
      $q.notify({ type: 'negative', message: t('adminLibrary.deleteLibraryError') })
    } finally {
      deleting.value = false
    }
  })
}

const resetScoring = () => {
  $q.dialog({
    title: t('scoringRules.resetTitle'),
    message: t('scoringRules.resetConfirm'),
    ok: { label: t('scoringRules.resetButton'), color: 'negative' },
    cancel: { label: t('common.cancel'), flat: true },
  }).onOk(async () => {
    savingScoring.value = true
    try {
      scoringConfig.value = await resetScoringRequest(lcType.value)
      $q.notify({ type: 'positive', message: t('scoringRules.resetSuccess') })
    } catch (error) {
      logger.error('Failed to reset scoring config:', error)
      $q.notify({ type: 'negative', message: t('scoringRules.resetError') })
    } finally {
      savingScoring.value = false
    }
  })
}

// ---- Quality profiles (Sonarr-style ordered list + cutoff) ----
const loadQualityProfiles = async () => {
  if (!showQualityProfile.value) return
  loadingQP.value = true
  try {
    const [ladder, std, fav] = await Promise.all([
      getQualityLadder(lcType.value),
      getQualityProfile(lcType.value),
      getQualityProfile(lcType.value, { favorites: true }),
    ])
    qualityLadder.value = ladder || []
    qualityProfileStd.value = std
    qualityProfileFav.value = fav
  } catch (error) {
    logger.error('Failed to load quality profiles:', error)
  } finally {
    loadingQP.value = false
  }
}

const saveQualityProfile = async (variant, payload) => {
  savingQP.value = true
  try {
    const data = await saveQualityProfileRequest(lcType.value, payload, variant === 'favorites')
    if (variant === 'favorites') qualityProfileFav.value = data
    else qualityProfileStd.value = data
  } catch (error) {
    logger.error('Failed to save quality profile:', error)
  } finally {
    savingQP.value = false
  }
}

const resetQualityProfile = (variant) => {
  $q.dialog({
    title: t('qualityProfile.resetTitle'),
    message:
      variant === 'favorites'
        ? t('qualityProfile.clearFavoritesConfirm')
        : t('qualityProfile.resetConfirm'),
    ok: { label: t('scoringRules.resetButton'), color: 'negative' },
    cancel: { label: t('common.cancel'), flat: true },
  }).onOk(async () => {
    savingQP.value = true
    try {
      const data = await resetQualityProfileRequest(lcType.value, variant === 'favorites')
      if (variant === 'favorites') {
        // Cleared -> reload so it reflects the standard fallback.
        await loadQualityProfiles()
      } else {
        qualityProfileStd.value = data
      }
      $q.notify({
        type: 'positive',
        message: t('scoringRules.resetSuccess', 'Reset to defaults'),
      })
    } catch (error) {
      logger.error('Failed to reset quality profile:', error)
      $q.notify({
        type: 'negative',
        message: t('scoringRules.resetError', 'Failed to reset quality profile'),
      })
    } finally {
      savingQP.value = false
    }
  })
}

// Lifecycle
onMounted(() => {
  loadSettings()
  loadPlatformOptions()
})

// Watch for library ID changes
watch(
  () => props.libraryId,
  () => {
    library.value = null // Reset library so it gets reloaded
    loadSettings()
  },
)
</script>
