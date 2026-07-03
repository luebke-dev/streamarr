<template>
  <q-page padding>
    <div class="row items-center q-mb-lg">
      <div class="col">
        <q-btn
          flat
          icon="mdi-arrow-left"
          :label="$t('common.back')"
          @click="$router.push('/admin/page-layouts')"
          class="q-mb-sm"
        />
        <h4 class="q-my-none">
          {{
            isCreateMode
              ? $t('pageLayouts.create', 'Create Layout')
              : $t('pageLayouts.edit', 'Edit Layout')
          }}
        </h4>
      </div>
    </div>

    <div class="row q-col-gutter-lg">
      <!-- Left column: Layout details -->
      <div class="col-12 col-md-4">
        <q-card flat bordered>
          <q-card-section>
            <div class="text-h6 q-mb-md">{{ $t('pageLayouts.details', 'Layout Details') }}</div>
            <q-form @submit="saveLayout" class="q-gutter-md">
              <q-input
                v-model="formData.name"
                :label="$t('common.name')"
                outlined
                dense
                :rules="[(val) => !!val || $t('validation.required')]"
              />
              <q-input
                v-model="formData.slug"
                :label="$t('common.slug', 'Slug')"
                outlined
                dense
                :rules="[(val) => !!val || $t('validation.required')]"
                :hint="$t('pageLayouts.slugHint')"
              />
              <q-select
                v-model="formData.library_guid"
                :label="$t('pageLayouts.library', 'Library (optional)')"
                :options="libraryOptions"
                emit-value
                map-options
                outlined
                dense
                clearable
              />
              <q-toggle v-model="formData.is_active" :label="$t('common.active', 'Active')" />

              <div class="row q-gutter-sm">
                <q-btn type="submit" color="primary" :label="$t('common.save')" :loading="saving" />
                <q-btn
                  flat
                  :label="$t('common.cancel')"
                  @click="$router.push('/admin/page-layouts')"
                />
              </div>
            </q-form>
          </q-card-section>
        </q-card>
      </div>

      <!-- Right column: Sections editor -->
      <div class="col-12 col-md-8">
        <q-card flat bordered>
          <q-card-section>
            <div class="row items-center q-mb-md">
              <div class="col text-h6">{{ $t('pageLayouts.sections', 'Sections') }}</div>
              <div class="col-auto">
                <q-btn
                  color="primary"
                  size="sm"
                  icon="mdi-plus"
                  :label="$t('pageLayouts.addSection', 'Add Section')"
                  @click="showAddSection = true"
                  :disable="isCreateMode"
                />
              </div>
            </div>

            <div v-if="isCreateMode" class="text-grey-6 text-center q-pa-lg">
              {{ $t('pageLayouts.saveFirst', 'Save the layout first, then add sections.') }}
            </div>

            <!-- Draggable section list -->
            <div v-else class="sections-list">
              <div
                v-for="(section, index) in sections"
                :key="section.guid"
                class="section-item q-mb-sm"
                :class="{ 'section-disabled': !section.is_enabled }"
              >
                <q-card flat bordered>
                  <q-card-section class="q-pa-sm">
                    <div class="row items-center no-wrap">
                      <!-- Drag handle & reorder buttons -->
                      <div class="col-auto q-mr-sm">
                        <div class="column items-center">
                          <q-btn
                            flat
                            dense
                            round
                            icon="mdi-chevron-up"
                            size="xs"
                            @click="moveSection(index, -1)"
                            :disable="index === 0"
                          />
                          <q-icon name="mdi-drag" color="grey-6" size="sm" class="cursor-move" />
                          <q-btn
                            flat
                            dense
                            round
                            icon="mdi-chevron-down"
                            size="xs"
                            @click="moveSection(index, 1)"
                            :disable="index === sections.length - 1"
                          />
                        </div>
                      </div>

                      <!-- Section type icon & info -->
                      <div class="col">
                        <div class="row items-center">
                          <q-icon
                            :name="sectionTypeIcon(section.section_type)"
                            size="sm"
                            color="primary"
                            class="q-mr-sm"
                          />
                          <div>
                            <div class="text-weight-medium">
                              {{ section.title || sectionTypeLabel(section.section_type) }}
                            </div>
                            <div class="text-caption text-grey-6">
                              {{ sectionTypeLabel(section.section_type) }}
                            </div>
                          </div>
                        </div>
                      </div>

                      <!-- Actions -->
                      <div class="col-auto">
                        <q-toggle
                          v-model="section.is_enabled"
                          dense
                          @update:model-value="updateSection(section)"
                        />
                        <q-btn
                          flat
                          round
                          dense
                          icon="mdi-pencil"
                          size="sm"
                          color="grey-7"
                          @click="editSection(section)"
                        />
                        <q-btn
                          flat
                          round
                          dense
                          icon="mdi-delete"
                          size="sm"
                          color="negative"
                          @click="confirmDeleteSection(section)"
                        />
                      </div>
                    </div>
                  </q-card-section>
                </q-card>
              </div>

              <div v-if="sections.length === 0" class="text-center text-grey-5 q-pa-xl">
                <q-icon name="mdi-view-dashboard-outline" size="3em" />
                <div class="q-mt-sm">
                  {{ $t('pageLayouts.noSections', 'No sections yet. Add one to get started.') }}
                </div>
              </div>
            </div>
          </q-card-section>
        </q-card>
      </div>
    </div>

    <!-- Add/Edit Section Dialog -->
    <SectionConfigDialog
      v-model="showSectionDialog"
      :section="editingSection"
      :genre-options="genreOptions"
      :list-options="listOptions"
      :saving="savingSection"
      @save="saveSection"
    />

    <!-- Delete section confirmation -->
    <q-dialog v-model="showDeleteSectionDialog">
      <q-card style="min-width: 350px">
        <q-card-section class="row items-center">
          <q-avatar icon="mdi-alert" color="negative" text-color="white" />
          <span class="q-ml-sm">{{
            $t('pageLayouts.confirmDeleteSection', 'Delete this section?')
          }}</span>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat :label="$t('common.cancel')" v-close-popup />
          <q-btn
            flat
            color="negative"
            :label="$t('common.delete')"
            @click="deleteSection"
            :loading="deletingSection"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { api } from 'boot/axios'
import { logger } from 'src/utils/logger'
import SectionConfigDialog from 'src/components/sections/SectionConfigDialog.vue'

const route = useRoute()
const router = useRouter()
useI18n()

const isCreateMode = computed(() => route.params.guid === 'create')
const layoutGuid = computed(() => (isCreateMode.value ? null : route.params.guid))

// Layout form
const formData = ref({
  name: '',
  slug: '',
  library_guid: null,
  is_active: true,
})

const saving = ref(false)
const sections = ref([])

// Section dialog
const showSectionDialog = ref(false)
const showAddSection = ref(false)
const editingSection = ref(null)
const savingSection = ref(false)
const showDeleteSectionDialog = ref(false)
const sectionToDelete = ref(null)
const deletingSection = ref(false)

// Options data
const libraryOptions = ref([])
const genreOptions = ref([])
const listOptions = ref([])

const sectionTypeOptions = [
  { value: 'hero_carousel', label: 'Hero Carousel' },
  { value: 'genre', label: 'Specific Genre' },
  { value: 'all_genres', label: 'All Genres' },
  { value: 'list', label: 'List' },
  { value: 'dynamic_search', label: 'Dynamic Search' },
  { value: 'latest_items', label: 'Latest Items' },
  { value: 'continue_watching', label: 'Continue Watching' },
  { value: 'favorites', label: 'Favorites' },
  { value: 'trailers', label: 'Trailers' },
]

function sectionTypeIcon(type) {
  const icons = {
    hero_carousel: 'mdi-image-multiple',
    genre: 'mdi-tag',
    all_genres: 'mdi-tag-multiple',
    list: 'mdi-format-list-bulleted',
    dynamic_search: 'mdi-magnify',
    latest_items: 'mdi-clock-outline',
    continue_watching: 'mdi-play-circle',
    favorites: 'mdi-heart',
    trailers: 'mdi-movie-open-play',
  }
  return icons[type] || 'mdi-view-dashboard'
}

function sectionTypeLabel(type) {
  const opt = sectionTypeOptions.find((o) => o.value === type)
  return opt ? opt.label : type
}

// Load layout data
async function loadLayout() {
  if (isCreateMode.value) return
  try {
    const response = await api.get(`/api/page-layouts/${layoutGuid.value}`)
    const layout = response.data
    formData.value = {
      name: layout.name,
      slug: layout.slug,
      library_guid: layout.library_guid,
      is_active: layout.is_active,
    }
    sections.value = (layout.sections || []).sort((a, b) => a.order_index - b.order_index)
  } catch (error) {
    logger.error('Error loading layout:', error)
  }
}

// Save layout (create or update)
async function saveLayout() {
  saving.value = true
  try {
    if (isCreateMode.value) {
      const response = await api.post('/api/page-layouts', formData.value)
      router.replace(`/admin/page-layouts/${response.data.guid}`)
    } else {
      await api.put(`/api/page-layouts/${layoutGuid.value}`, formData.value)
    }
  } catch (error) {
    logger.error('Error saving layout:', error)
  } finally {
    saving.value = false
  }
}

// Move section up/down
async function moveSection(index, direction) {
  const newIndex = index + direction
  if (newIndex < 0 || newIndex >= sections.value.length) return

  const items = [...sections.value]
  const [moved] = items.splice(index, 1)
  items.splice(newIndex, 0, moved)
  sections.value = items

  // Persist order
  try {
    await api.put(`/api/page-layouts/${layoutGuid.value}/sections-order`, {
      section_order: items.map((s) => s.guid),
    })
  } catch (error) {
    logger.error('Error reordering sections:', error)
    loadLayout() // revert
  }
}

// Open add section dialog
function openAddSection() {
  editingSection.value = null
  showSectionDialog.value = true
}

// When showAddSection changes, open dialog
import { watch } from 'vue'
watch(showAddSection, (val) => {
  if (val) {
    openAddSection()
    showAddSection.value = false
  }
})

// Edit section
function editSection(section) {
  editingSection.value = section
  showSectionDialog.value = true
}

// Save section (add or update) — payload comes from SectionConfigDialog
async function saveSection(payload) {
  savingSection.value = true
  try {
    if (editingSection.value) {
      await api.put(
        `/api/page-layouts/${layoutGuid.value}/sections/${editingSection.value.guid}`,
        payload,
      )
    } else {
      payload.order_index = sections.value.length
      await api.post(`/api/page-layouts/${layoutGuid.value}/sections`, payload)
    }

    showSectionDialog.value = false
    await loadLayout()
  } catch (error) {
    logger.error('Error saving section:', error)
  } finally {
    savingSection.value = false
  }
}

// Update section (toggle enable)
async function updateSection(section) {
  try {
    await api.put(`/api/page-layouts/${layoutGuid.value}/sections/${section.guid}`, {
      is_enabled: section.is_enabled,
    })
  } catch (error) {
    logger.error('Error updating section:', error)
    loadLayout()
  }
}

// Delete section
function confirmDeleteSection(section) {
  sectionToDelete.value = section
  showDeleteSectionDialog.value = true
}

async function deleteSection() {
  if (!sectionToDelete.value) return
  deletingSection.value = true
  try {
    await api.delete(`/api/page-layouts/${layoutGuid.value}/sections/${sectionToDelete.value.guid}`)
    showDeleteSectionDialog.value = false
    await loadLayout()
  } catch (error) {
    logger.error('Error deleting section:', error)
  } finally {
    deletingSection.value = false
  }
}

// Load reference data
async function loadReferenceData() {
  try {
    const [libRes, genreRes, listRes] = await Promise.all([
      api.get('/api/libraries'),
      api.get('/api/genres'),
      api.get('/api/lists', { params: { per_page: 100 } }),
    ])

    libraryOptions.value = (libRes.data || []).map((l) => ({ value: l.guid, label: l.name }))
    genreOptions.value = (genreRes.data || []).map((g) => ({ value: g.id, label: g.name }))
    listOptions.value = (listRes.data.items || listRes.data || []).map((l) => ({
      value: l.guid,
      label: l.name,
    }))
  } catch (error) {
    logger.error('Error loading reference data:', error)
  }
}

onMounted(async () => {
  await Promise.all([loadReferenceData(), loadLayout()])
})
</script>

<style lang="scss" scoped>
.section-item.section-disabled {
  opacity: 0.5;
}

.cursor-move {
  cursor: grab;
}
</style>
