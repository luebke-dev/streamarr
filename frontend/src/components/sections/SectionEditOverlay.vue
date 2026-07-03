<template>
  <div class="section-edit-overlay" :class="{ 'section-edit-disabled': !section.is_enabled }">
    <!-- Toolbar -->
    <div class="section-edit-toolbar">
      <div class="row items-center no-wrap q-gutter-xs">
        <q-icon :name="sectionIcon" size="xs" color="primary" />
        <span class="text-caption text-weight-medium">{{ sectionLabel }}</span>
        <span v-if="!section.is_enabled" class="text-caption text-orange q-ml-xs"
          >({{ $t('pageLayouts.disabled') }})</span
        >
      </div>
      <div class="row items-center no-wrap q-gutter-xs">
        <q-btn
          flat
          dense
          round
          icon="mdi-chevron-up"
          size="xs"
          :disable="isFirst"
          @click="editor.moveSection(index, -1)"
        />
        <q-btn
          flat
          dense
          round
          icon="mdi-chevron-down"
          size="xs"
          :disable="isLast"
          @click="editor.moveSection(index, 1)"
        />
        <q-toggle
          :model-value="section.is_enabled"
          dense
          size="sm"
          @update:model-value="editor.toggleSectionEnabled(section)"
        />
        <q-btn
          flat
          dense
          round
          icon="mdi-pencil"
          size="xs"
          color="primary"
          @click="editor.openEditDialog(section)"
        />
        <q-btn
          flat
          dense
          round
          icon="mdi-delete"
          size="xs"
          color="negative"
          @click="confirmDelete = true"
        />
      </div>
    </div>

    <!-- Section content -->
    <slot />

    <!-- Delete confirmation -->
    <q-dialog v-model="confirmDelete">
      <q-card style="min-width: 350px">
        <q-card-section class="row items-center">
          <q-avatar icon="mdi-alert" color="negative" text-color="white" />
          <span class="q-ml-sm">{{ $t('pageLayouts.confirmDeleteSection') }}</span>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat :label="$t('common.cancel')" v-close-popup />
          <q-btn flat color="negative" :label="$t('common.delete')" @click="doDelete" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useLayoutEditorInject } from 'src/composables/useLayoutEditor'
import { getSectionIcon, getSectionLabel } from 'src/components/sections/sectionRegistry'

const props = defineProps({
  section: { type: Object, required: true },
  index: { type: Number, required: true },
  isFirst: { type: Boolean, default: false },
  isLast: { type: Boolean, default: false },
})

const { t } = useI18n()
const editor = useLayoutEditorInject()
const confirmDelete = ref(false)

const sectionIcon = computed(() => getSectionIcon(props.section.section_type))
const sectionLabel = computed(
  () => props.section.title || getSectionLabel(props.section.section_type, t),
)

function doDelete() {
  confirmDelete.value = false
  editor.deleteSection(props.section.guid)
}
</script>

<style lang="scss" scoped>
.section-edit-overlay {
  position: relative;
  outline: 2px dashed rgba(var(--q-primary-rgb, 25, 118, 210), 0.4);
  outline-offset: -2px;
  border-radius: 4px;
}

.section-edit-disabled {
  opacity: 0.4;
}

.section-edit-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 4px 12px;
  background: rgba(0, 0, 0, 0.6);
  backdrop-filter: blur(4px);
  border-radius: 4px 4px 0 0;
  z-index: 10;
  position: relative;
}
</style>
