<template>
  <div v-if="visibleEntries.length === 0" class="text-grey-6 text-caption">
    {{ $t('common.noFieldsToConfigure') }}
  </div>
  <div v-else class="q-gutter-md">
    <template v-for="[key, field] in visibleEntries" :key="key">
      <!-- select -->
      <q-select
        v-if="field.type === 'select'"
        outlined dark dense
        :model-value="modelValue[key]"
        :options="optionList(field)"
        emit-value map-options
        :label="fieldLabel(key, field)"
        :hint="field.hint || null"
        :clearable="!isRequired(field)"
        :disable="disabled"
        :rules="isRequired(field) ? [(v) => !!v || $t('common.required')] : []"
        @update:model-value="(v) => setField(key, v)"
      />

      <!-- integer -->
      <q-input
        v-else-if="field.type === 'integer'"
        outlined dark dense
        type="number"
        :model-value="modelValue[key] ?? null"
        :label="fieldLabel(key, field)"
        :hint="field.hint || null"
        :disable="disabled"
        :rules="isRequired(field) ? [(v) => v !== null && v !== '' || $t('common.required')] : []"
        @update:model-value="(v) => setField(key, coerceInt(v))"
      />

      <!-- string -->
      <q-input
        v-else-if="field.type === 'string'"
        outlined dark dense
        :model-value="modelValue[key] ?? ''"
        :label="fieldLabel(key, field)"
        :hint="field.hint || null"
        :disable="disabled"
        :rules="isRequired(field) ? [(v) => !!v || $t('common.required')] : []"
        @update:model-value="(v) => setField(key, v || null)"
      />

      <!-- boolean -->
      <q-toggle
        v-else-if="field.type === 'boolean'"
        :model-value="!!modelValue[key]"
        :label="fieldLabel(key, field)"
        :disable="disabled"
        color="primary"
        @update:model-value="(v) => setField(key, v)"
      />

      <!-- list-of-strings (chips input) -->
      <q-select
        v-else-if="field.type === 'string_list'"
        outlined dark dense use-input use-chips multiple
        new-value-mode="add-unique"
        hide-dropdown-icon
        :model-value="modelValue[key] || []"
        :label="fieldLabel(key, field)"
        :hint="field.hint || $t('common.pressEnterToAdd')"
        :options="optionList(field)"
        :disable="disabled"
        @update:model-value="(v) => setField(key, v)"
      />

      <!-- json blob fallback -->
      <q-input
        v-else
        outlined dark dense
        type="textarea" autogrow
        :model-value="jsonText(modelValue[key])"
        :label="fieldLabel(key, field)"
        :hint="field.hint || $t('common.jsonFallback')"
        :disable="disabled"
        :rules="[(v) => isValidJsonOrEmpty(v) || $t('common.invalidJson')]"
        @update:model-value="(v) => setField(key, parseJsonOrNull(v))"
      />
    </template>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  // Field descriptors keyed by name. See backend ``config_schema`` shape.
  schema: { type: Object, default: () => ({}) },
  // The current form payload (object).
  modelValue: { type: Object, default: () => ({}) },
  disabled: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue'])

function fieldLabel(key, field) {
  if (field.label) return field.label
  // Auto-titleize "watch_provider_id" → "Watch provider id"
  return key.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase())
}

function isRequired(field) {
  return !!field.required
}

function optionList(field) {
  if (!Array.isArray(field.options)) return []
  return field.options.map((opt) =>
    typeof opt === 'object' ? opt : { label: String(opt), value: opt }
  )
}

function dependencyMet(field, payload) {
  const deps = field?.depends_on
  if (!deps || typeof deps !== 'object') return true
  const source = payload ?? props.modelValue
  return Object.entries(deps).every(([k, expected]) => {
    const actual = source?.[k]
    if (Array.isArray(expected)) return expected.includes(actual)
    return actual === expected
  })
}

const visibleEntries = computed(() =>
  Object.entries(props.schema || {}).filter(([, field]) => dependencyMet(field))
)

function setField(key, value) {
  const next = { ...(props.modelValue || {}) }
  if (value === null || value === undefined || value === '') {
    delete next[key]
  } else {
    next[key] = value
  }
  // When a "controlling" field changes, drop hidden fields so the
  // payload stays clean (e.g. switching TMDb mode from "discover" to
  // "chart" shouldn't carry over a stale ``params`` blob).
  pruneHidden(next)
  emit('update:modelValue', next)
}

function pruneHidden(payload) {
  for (const [k, field] of Object.entries(props.schema || {})) {
    if (!dependencyMet(field, payload) && k in payload) {
      delete payload[k]
    }
  }
}

function coerceInt(v) {
  if (v === null || v === undefined || v === '') return null
  const n = Number(v)
  return Number.isFinite(n) ? Math.trunc(n) : null
}

function jsonText(v) {
  if (v === undefined || v === null) return ''
  if (typeof v === 'string') return v
  try { return JSON.stringify(v, null, 2) } catch { return '' }
}

function isValidJsonOrEmpty(v) {
  if (!v || !v.trim()) return true
  try { JSON.parse(v); return true } catch { return false }
}

function parseJsonOrNull(v) {
  if (!v || !v.trim()) return null
  try { return JSON.parse(v) } catch { return v }
}
</script>
