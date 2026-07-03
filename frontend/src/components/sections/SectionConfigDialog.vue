<template>
  <q-dialog
    :model-value="modelValue"
    @update:model-value="$emit('update:modelValue', $event)"
    persistent
  >
    <q-card style="min-width: 550px; max-width: 700px">
      <q-card-section>
        <div class="text-h6">
          {{ section ? $t('pageLayouts.editSection') : $t('pageLayouts.addSection') }}
        </div>
      </q-card-section>

      <q-card-section class="q-pt-none q-gutter-md">
        <q-select
          v-model="form.section_type"
          :label="$t('pageLayouts.sectionType')"
          :options="sectionOptions.sectionTypeOptions"
          emit-value
          map-options
          outlined
          dense
          :disable="!!section"
        />

        <q-input
          v-model="form.title"
          :label="$t('pageLayouts.sectionTitle')"
          outlined
          dense
          clearable
        />

        <component
          :is="activeConfigComponent"
          v-if="activeConfigComponent"
          :section-type="form.section_type"
          :config="form.config"
          :options="sectionOptions"
          :genre-options="genreOptions"
          :list-options="listOptions"
          :platform-options="platformOptions"
        />
      </q-card-section>

      <q-card-actions align="right">
        <q-btn flat :label="$t('common.cancel')" @click="$emit('update:modelValue', false)" />
        <q-btn color="primary" :label="$t('common.save')" @click="save" :loading="saving" />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  SECTION_CONFIG_COMPONENTS,
  createSectionConfigOptions,
  createSectionDefaultConfig,
} from 'src/components/sections/sectionConfigRegistry'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  section: { type: Object, default: null },
  genreOptions: { type: Array, default: () => [] },
  listOptions: { type: Array, default: () => [] },
  platformOptions: { type: Array, default: () => [] },
  saving: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue', 'save'])
const { t } = useI18n()

const defaultForm = () => ({
  section_type: 'hero_carousel',
  title: '',
  config: createSectionDefaultConfig('hero_carousel'),
})

const form = ref(defaultForm())
const sectionOptions = computed(() => createSectionConfigOptions(t))
const activeConfigComponent = computed(() => SECTION_CONFIG_COMPONENTS[form.value.section_type])

watch(
  () => props.modelValue,
  (open) => {
    if (!open) return
    if (props.section) {
      form.value = {
        section_type: props.section.section_type,
        title: props.section.title || '',
        config: {
          ...createSectionDefaultConfig(props.section.section_type),
          ...JSON.parse(JSON.stringify(props.section.config || {})),
        },
      }
      ensureFilters()
    } else {
      form.value = defaultForm()
    }
  },
)

watch(
  () => form.value.section_type,
  (sectionType, previousType) => {
    if (!props.modelValue || props.section || !sectionType || sectionType === previousType) return
    form.value.config = createSectionDefaultConfig(sectionType)
    ensureFilters()
  },
)

function ensureFilters() {
  if (form.value.config && !form.value.config.filters) {
    form.value.config.filters = {}
  }
}

function cleanConfig(config) {
  const cleaned = { ...config }
  if (cleaned.filters) {
    const filters = {}
    for (const [key, value] of Object.entries(cleaned.filters)) {
      if (value !== null && value !== undefined && value !== '') {
        filters[key] = value
      }
    }
    cleaned.filters = Object.keys(filters).length > 0 ? filters : undefined
  }
  for (const [key, value] of Object.entries(cleaned)) {
    if (value === null || value === undefined || value === '') {
      delete cleaned[key]
    }
  }
  return cleaned
}

function save() {
  emit('save', {
    section_type: form.value.section_type,
    title: form.value.title || null,
    config: cleanConfig(form.value.config),
    is_enabled: true,
  })
}
</script>
