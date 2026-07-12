import { ref, provide, inject, watch } from 'vue'
import { logger } from 'src/utils/logger'
import {
  getGenres,
  getLists,
  getPlatforms,
  getPageLayout,
  createPageLayout,
  updateSectionsOrder,
  createPageLayoutSection,
  updatePageLayoutSection,
  deletePageLayoutSection,
} from 'src/services/contentAdminService'

const LAYOUT_EDITOR_KEY = Symbol('layoutEditor')

// Shared module-level state so MainLayout toolbar can read/toggle edit mode
export const layoutEditMode = ref(false)
export const layoutExists = ref(false)

export function useLayoutEditor() {
  const editMode = layoutEditMode
  const layoutGuid = ref(null)
  const allSections = ref([])
  const genreOptions = ref([])
  const listOptions = ref([])
  const platformOptions = ref([])
  const saving = ref(false)
  const referenceLoaded = ref(false)
  let referenceLoadPromise = null

  // Dialog state
  const showConfigDialog = ref(false)
  const editingSection = ref(null)
  const savingSection = ref(false)
  const insertAtIndex = ref(null)

  function init(guid, sections) {
    layoutGuid.value = guid
    allSections.value = [...sections].sort((a, b) => a.order_index - b.order_index)
  }

  async function loadReferenceData() {
    if (referenceLoaded.value) return
    if (referenceLoadPromise) return referenceLoadPromise

    referenceLoadPromise = (async () => {
      const [genreData, listData, platformData] = await Promise.all([
        getGenres(),
        getLists({ per_page: 100 }),
        getPlatforms(),
      ])
      genreOptions.value = (genreData || []).map((g) => ({ value: g.id, label: g.name }))
      listOptions.value = (listData.items || listData || []).map((l) => ({
        value: l.guid,
        label: l.name,
      }))
      platformOptions.value = (platformData || []).map((p) => ({ value: p.id, label: p.name }))
      referenceLoaded.value = true
    })()

    try {
      await referenceLoadPromise
    } catch (error) {
      logger.error('Error loading reference data:', error)
    } finally {
      referenceLoadPromise = null
    }
  }

  function toggleEditMode() {
    editMode.value = !editMode.value
  }

  watch(editMode, (active) => {
    if (active) loadReferenceData()
  })

  async function reloadLayout() {
    if (!layoutGuid.value) return
    try {
      const layout = await getPageLayout(layoutGuid.value)
      allSections.value = (layout.sections || []).sort((a, b) => a.order_index - b.order_index)
    } catch (error) {
      logger.error('Error reloading layout:', error)
    }
  }

  async function moveSection(index, direction) {
    const newIndex = index + direction
    if (newIndex < 0 || newIndex >= allSections.value.length) return

    const items = [...allSections.value]
    const [moved] = items.splice(index, 1)
    items.splice(newIndex, 0, moved)
    allSections.value = items

    try {
      await updateSectionsOrder(
        layoutGuid.value,
        items.map((s) => s.guid),
      )
      await reloadLayout()
    } catch (error) {
      logger.error('Error reordering sections:', error)
      await reloadLayout()
    }
  }

  async function openAddDialog(orderIndex) {
    await loadReferenceData()
    editingSection.value = null
    insertAtIndex.value = orderIndex
    showConfigDialog.value = true
  }

  async function openEditDialog(section) {
    await loadReferenceData()
    editingSection.value = section
    showConfigDialog.value = true
  }

  async function saveSection(payload) {
    savingSection.value = true
    try {
      if (editingSection.value) {
        await updatePageLayoutSection(layoutGuid.value, editingSection.value.guid, payload)
      } else {
        payload.order_index = insertAtIndex.value ?? allSections.value.length
        await createPageLayoutSection(layoutGuid.value, payload)
      }
      showConfigDialog.value = false
      await reloadLayout()
    } catch (error) {
      logger.error('Error saving section:', error)
    } finally {
      savingSection.value = false
    }
  }

  async function deleteSection(sectionGuid) {
    try {
      await deletePageLayoutSection(layoutGuid.value, sectionGuid)
      await reloadLayout()
    } catch (error) {
      logger.error('Error deleting section:', error)
    }
  }

  async function toggleSectionEnabled(section) {
    try {
      await updatePageLayoutSection(layoutGuid.value, section.guid, {
        is_enabled: !section.is_enabled,
      })
      await reloadLayout()
    } catch (error) {
      logger.error('Error toggling section:', error)
    }
  }

  async function createLayout(name, slug) {
    try {
      const layout = await createPageLayout({
        name,
        slug,
        is_active: true,
      })
      layoutGuid.value = layout.guid
      allSections.value = []
      editMode.value = true
      await loadReferenceData()
      return layout
    } catch (error) {
      logger.error('Error creating layout:', error)
      throw error
    }
  }

  const editor = {
    editMode,
    layoutGuid,
    allSections,
    genreOptions,
    listOptions,
    platformOptions,
    saving,
    showConfigDialog,
    editingSection,
    savingSection,
    init,
    toggleEditMode,
    reloadLayout,
    moveSection,
    openAddDialog,
    openEditDialog,
    saveSection,
    deleteSection,
    toggleSectionEnabled,
    createLayout,
  }

  return editor
}

export function provideLayoutEditor(editor) {
  provide(LAYOUT_EDITOR_KEY, editor)
}

export function useLayoutEditorInject() {
  return inject(LAYOUT_EDITOR_KEY, null)
}
