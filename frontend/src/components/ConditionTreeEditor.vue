<template>
  <div class="condition-node" :class="`node-${nodeKind}`">
    <div class="row q-col-gutter-sm items-center q-mb-sm">
      <q-select
        outlined dark dense class="col-auto"
        :model-value="nodeKind"
        :options="kindOptions"
        emit-value map-options
        :label="depth === 0 ? $t('overlayCondition.rootType') : $t('overlayCondition.nodeType')"
        :disable="disabled"
        @update:model-value="changeKind"
      />
      <q-space v-if="depth > 0" />
      <q-btn
        v-if="depth > 0"
        flat dense round icon="mdi-close" color="negative" size="sm"
        :disable="disabled"
        @click="$emit('remove')"
      >
        <q-tooltip>{{ $t('overlayCondition.removeNode') }}</q-tooltip>
      </q-btn>
    </div>

    <!-- ALL / ANY: list of child expressions -->
    <div v-if="nodeKind === 'all' || nodeKind === 'any'" class="children">
      <div
        v-for="(child, idx) in childList"
        :key="idx"
        class="child-slot q-mb-sm"
      >
        <ConditionTreeEditor
          :model-value="child"
          :depth="depth + 1"
          :disabled="disabled"
          @update:model-value="(v) => updateChild(idx, v)"
          @remove="removeChild(idx)"
        />
      </div>
      <q-btn
        flat dense color="primary" icon="mdi-plus" size="sm"
        :label="$t('overlayCondition.addChild')"
        :disable="disabled"
        @click="addChild"
      />
    </div>

    <!-- NOT: single child -->
    <div v-else-if="nodeKind === 'not'" class="children">
      <ConditionTreeEditor
        :model-value="modelValue?.not || _newLeaf()"
        :depth="depth + 1"
        :disabled="disabled"
        @update:model-value="(v) => $emit('update:modelValue', { not: v })"
      />
    </div>

    <!-- LEAF: field/op/value -->
    <div v-else-if="nodeKind === 'leaf'" class="leaf-row row q-col-gutter-sm">
      <q-select
        outlined dark dense use-input fill-input hide-selected
        class="col-12 col-sm-5"
        :model-value="modelValue.field"
        :options="filteredFieldOptions"
        :input-debounce="0"
        emit-value map-options
        new-value-mode="add-unique"
        :label="$t('overlayCondition.field')"
        :disable="disabled"
        @filter="onFieldFilter"
        @update:model-value="(v) => emitLeaf({ field: v })"
      >
        <template v-slot:hint>
          <span v-if="fieldMeta">{{ fieldMeta.hint }}</span>
        </template>
      </q-select>

      <q-select
        outlined dark dense class="col-12 col-sm-3"
        :model-value="modelValue.op || 'eq'"
        :options="opOptions"
        emit-value map-options
        :label="$t('overlayCondition.op')"
        :disable="disabled"
        @update:model-value="(v) => emitLeaf({ op: v, value: defaultValueFor(modelValue.field, v) })"
      />

      <!-- Value widget: type depends on op (and sometimes field) -->
      <div class="col-12 col-sm-4">
        <q-input
          v-if="valueKind === 'none'"
          outlined dark dense readonly
          :model-value="$t('overlayCondition.noValue')"
        />
        <q-input
          v-else-if="valueKind === 'number'"
          outlined dark dense type="number"
          :model-value="modelValue.value ?? null"
          :label="$t('overlayCondition.value')"
          :disable="disabled"
          @update:model-value="(v) => emitLeaf({ value: coerceNumber(v) })"
        />
        <q-toggle
          v-else-if="valueKind === 'boolean'"
          :model-value="!!modelValue.value"
          :label="$t('overlayCondition.value')"
          :disable="disabled"
          color="primary"
          @update:model-value="(v) => emitLeaf({ value: v })"
        />
        <q-select
          v-else-if="valueKind === 'select'"
          outlined dark dense
          :model-value="modelValue.value"
          :options="fieldValueOptions"
          emit-value map-options
          :label="$t('overlayCondition.value')"
          :disable="disabled"
          @update:model-value="(v) => emitLeaf({ value: v })"
        />
        <q-select
          v-else-if="valueKind === 'list'"
          outlined dark dense use-input use-chips multiple
          new-value-mode="add-unique"
          hide-dropdown-icon
          :model-value="Array.isArray(modelValue.value) ? modelValue.value : []"
          :label="$t('overlayCondition.values')"
          :hint="$t('common.pressEnterToAdd')"
          :options="fieldValueOptions"
          :disable="disabled"
          @update:model-value="(v) => emitLeaf({ value: v })"
        />
        <q-input
          v-else
          outlined dark dense
          :model-value="modelValue.value ?? ''"
          :label="$t('overlayCondition.value')"
          :hint="valueKind === 'regex' ? $t('overlayCondition.regexHint') : null"
          :disable="disabled"
          @update:model-value="(v) => emitLeaf({ value: v })"
        />
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const props = defineProps({
  modelValue: { type: [Object, null], default: null },
  depth: { type: Number, default: 0 },
  disabled: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue', 'remove'])

// ---------------------------------------------------------------------------
// Known context fields (mirrors backend/overlays/context.py keys)
// ---------------------------------------------------------------------------
const FIELDS = [
  { value: 'resolution.height', label: 'Resolution height (px)', type: 'number' },
  { value: 'resolution.width', label: 'Resolution width (px)', type: 'number' },
  {
    value: 'resolution.label',
    label: 'Resolution bucket',
    type: 'enum',
    options: ['4K', '1440p', '1080p', '720p', '480p', 'SD'],
  },
  {
    value: 'media_type',
    label: 'Media type',
    type: 'enum',
    options: ['MOVIES', 'SHOWS'],
  },
  { value: 'year', label: 'Release year', type: 'number' },
  { value: 'title', label: 'Title', type: 'string' },
  {
    value: 'availability',
    label: 'Availability',
    type: 'enum',
    options: ['available', 'downloadable', 'unknown'],
  },
  { value: 'min_age', label: 'Parental rating (min_age)', type: 'number' },
  {
    value: 'genres',
    label: 'Genres',
    type: 'list',
    hint: 'list of genre names (lowercased)',
  },
  {
    value: 'codecs.video',
    label: 'Video codec(s)',
    type: 'list',
    hint: 'e.g. hevc, h264, av1',
  },
  {
    value: 'codecs.audio',
    label: 'Audio codec(s)',
    type: 'list',
    hint: 'e.g. eac3, dts, opus',
  },
  { value: 'has_files', label: 'Has local files', type: 'bool' },
]

const kindOptions = [
  { label: t('overlayCondition.kindAll'), value: 'all' },
  { label: t('overlayCondition.kindAny'), value: 'any' },
  { label: t('overlayCondition.kindNot'), value: 'not' },
  { label: t('overlayCondition.kindLeaf'), value: 'leaf' },
]

const OPS = [
  { value: 'eq', label: 'equals' },
  { value: 'ne', label: 'not equals' },
  { value: 'gte', label: '≥' },
  { value: 'lte', label: '≤' },
  { value: 'gt', label: '>' },
  { value: 'lt', label: '<' },
  { value: 'in', label: 'in (any of)' },
  { value: 'not_in', label: 'not in' },
  { value: 'contains', label: 'contains' },
  { value: 'not_contains', label: 'does not contain' },
  { value: 'matches', label: 'matches regex' },
  { value: 'truthy', label: 'is set / true' },
  { value: 'falsy', label: 'is empty / false' },
]
const opOptions = OPS

// ---------------------------------------------------------------------------
// Derived state
// ---------------------------------------------------------------------------
const nodeKind = computed(() => kindOf(props.modelValue))

const childList = computed(() => {
  if (nodeKind.value === 'all') return props.modelValue?.all || []
  if (nodeKind.value === 'any') return props.modelValue?.any || []
  return []
})

const fieldMeta = computed(() =>
  FIELDS.find((f) => f.value === props.modelValue?.field) || null
)

// op-driven value rendering
const valueKind = computed(() => {
  const op = props.modelValue?.op || 'eq'
  if (op === 'truthy' || op === 'falsy') return 'none'
  if (op === 'in' || op === 'not_in') return 'list'
  if (op === 'matches') return 'regex'
  const meta = fieldMeta.value
  if (meta?.type === 'number') return 'number'
  if (meta?.type === 'bool') return 'boolean'
  if (meta?.type === 'enum') return 'select'
  if (meta?.type === 'list') return 'list'
  return 'string'
})

const fieldValueOptions = computed(() => {
  const meta = fieldMeta.value
  if (!meta) return []
  if (Array.isArray(meta.options)) return meta.options
  return []
})

// Free-text field input: filter the known-fields list as the user types.
const fieldFilter = ref('')
const filteredFieldOptions = computed(() => {
  const q = fieldFilter.value?.toLowerCase()
  const base = FIELDS.map((f) => ({ label: `${f.label}  —  ${f.value}`, value: f.value }))
  if (!q) return base
  return base.filter((o) => o.value.toLowerCase().includes(q) || o.label.toLowerCase().includes(q))
})
function onFieldFilter(val, update) {
  update(() => { fieldFilter.value = val || '' })
}

// ---------------------------------------------------------------------------
// Mutations
// ---------------------------------------------------------------------------
function kindOf(value) {
  if (!value || typeof value !== 'object') return 'leaf'
  if ('all' in value) return 'all'
  if ('any' in value) return 'any'
  if ('not' in value) return 'not'
  return 'leaf'
}

function _newLeaf() {
  return { field: 'resolution.height', op: 'gte', value: 2160 }
}

function changeKind(kind) {
  if (kind === 'all') return emit('update:modelValue', { all: childList.value.length ? childList.value : [_newLeaf()] })
  if (kind === 'any') return emit('update:modelValue', { any: childList.value.length ? childList.value : [_newLeaf()] })
  if (kind === 'not') return emit('update:modelValue', { not: _newLeaf() })
  return emit('update:modelValue', _newLeaf())
}

function updateChild(idx, value) {
  const list = [...childList.value]
  list[idx] = value
  emit('update:modelValue', { [nodeKind.value]: list })
}

function removeChild(idx) {
  const list = [...childList.value]
  list.splice(idx, 1)
  if (list.length === 0) {
    // collapse empty combinator back to a single leaf so the UI never
    // shows an "all of nothing" node that's silently true.
    emit('update:modelValue', _newLeaf())
    return
  }
  emit('update:modelValue', { [nodeKind.value]: list })
}

function addChild() {
  const list = [...childList.value, _newLeaf()]
  emit('update:modelValue', { [nodeKind.value]: list })
}

function emitLeaf(patch) {
  emit('update:modelValue', {
    field: props.modelValue?.field,
    op: props.modelValue?.op || 'eq',
    value: props.modelValue?.value,
    ...patch,
  })
}

function defaultValueFor(field, op) {
  if (op === 'truthy' || op === 'falsy') return undefined
  if (op === 'in' || op === 'not_in') return []
  const meta = FIELDS.find((f) => f.value === field)
  if (!meta) return ''
  if (meta.type === 'number') return null
  if (meta.type === 'bool') return false
  return ''
}

function coerceNumber(v) {
  if (v === null || v === undefined || v === '') return null
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}
</script>

<style scoped>
.condition-node {
  border-left: 3px solid rgba(255,255,255,0.15);
  padding: 8px 12px;
  border-radius: 4px;
  background: rgba(255,255,255,0.02);
}
.condition-node.node-all { border-left-color: #5fa3ff; }
.condition-node.node-any { border-left-color: #ffa05f; }
.condition-node.node-not { border-left-color: #ff5f5f; }
.condition-node.node-leaf { border-left-color: #5fff8f; }
.children {
  padding-left: 12px;
}
.leaf-row {
  align-items: flex-start;
}
.child-slot {
  background: rgba(255,255,255,0.02);
  border-radius: 4px;
}
</style>
