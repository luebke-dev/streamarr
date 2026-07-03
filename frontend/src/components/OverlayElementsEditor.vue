<template>
  <div class="overlay-elements-editor">
    <div class="row q-col-gutter-sm q-mb-md">
      <q-btn
        color="primary" icon="mdi-format-text" unelevated dense
        :label="$t('overlayElements.addText')"
        :disable="disabled"
        @click="addElement('text')"
      />
      <q-btn
        color="primary" icon="mdi-image-outline" unelevated dense outline
        :label="$t('overlayElements.addImage')"
        :disable="disabled"
        @click="addElement('image')"
      />
    </div>

    <div v-if="elements.length === 0" class="text-grey-6 text-caption">
      {{ $t('overlayElements.empty') }}
    </div>

    <q-card
      v-for="(el, idx) in elements"
      :key="uidFor(el)"
      flat bordered dark
      class="q-mb-md element-card"
      :class="`element-${el.type || 'unknown'}`"
    >
      <q-card-section class="q-pa-sm">
        <div class="row items-center q-col-gutter-sm">
          <q-chip
            size="sm" text-color="white" dense
            :color="el.type === 'text' ? 'primary' : 'secondary'"
            :icon="el.type === 'text' ? 'mdi-format-text' : 'mdi-image-outline'"
            :label="el.type === 'text' ? $t('overlayElements.text') : $t('overlayElements.image')"
          />
          <span class="text-caption text-grey-6">#{{ idx + 1 }}</span>
          <q-space />
          <q-btn
            flat dense round icon="mdi-chevron-up" size="sm"
            :disable="idx === 0 || disabled"
            @click="moveUp(idx)"
          >
            <q-tooltip>{{ $t('overlayElements.moveUp') }}</q-tooltip>
          </q-btn>
          <q-btn
            flat dense round icon="mdi-chevron-down" size="sm"
            :disable="idx === elements.length - 1 || disabled"
            @click="moveDown(idx)"
          >
            <q-tooltip>{{ $t('overlayElements.moveDown') }}</q-tooltip>
          </q-btn>
          <q-btn
            flat dense round icon="mdi-content-copy" size="sm" color="primary"
            :disable="disabled"
            @click="duplicate(idx)"
          >
            <q-tooltip>{{ $t('overlayElements.duplicate') }}</q-tooltip>
          </q-btn>
          <q-btn
            flat dense round icon="mdi-delete" size="sm" color="negative"
            :disable="disabled"
            @click="removeAt(idx)"
          >
            <q-tooltip>{{ $t('common.delete') }}</q-tooltip>
          </q-btn>
        </div>
      </q-card-section>

      <q-separator dark />

      <q-card-section class="q-gutter-md">
        <!-- Text-specific fields -->
        <template v-if="el.type === 'text'">
          <q-input
            outlined dark dense
            :model-value="el.text"
            :label="$t('overlayElements.fields.text')"
            :hint="$t('overlayElements.textHint')"
            :disable="disabled"
            :rules="[(v) => !!v || $t('common.required')]"
            @update:model-value="(v) => patch(idx, { text: v })"
          />
          <div class="row q-col-gutter-md">
            <q-input
              outlined dark dense class="col"
              type="number"
              :model-value="el.font_size ?? 36"
              :label="$t('overlayElements.fields.fontSize')"
              :disable="disabled"
              @update:model-value="(v) => patch(idx, { font_size: coerceInt(v) })"
            />
            <q-input
              outlined dark dense class="col"
              :model-value="el.font_path || ''"
              :label="$t('overlayElements.fields.fontPath')"
              :hint="$t('overlayElements.fontPathHint')"
              :disable="disabled"
              @update:model-value="(v) => patch(idx, { font_path: v || undefined })"
            />
          </div>
          <div class="row q-col-gutter-md">
            <div class="col">
              <ColorField
                :model-value="el.color"
                :label="$t('overlayElements.fields.color')"
                :disable="disabled"
                @update:model-value="(v) => patch(idx, { color: v })"
              />
            </div>
            <div class="col">
              <ColorField
                :model-value="el.background"
                :label="$t('overlayElements.fields.background')"
                clearable
                :disable="disabled"
                @update:model-value="(v) => patch(idx, { background: v })"
              />
            </div>
            <q-input
              outlined dark dense class="col"
              type="number"
              :model-value="el.background_radius ?? 0"
              :label="$t('overlayElements.fields.backgroundRadius')"
              :disable="disabled"
              @update:model-value="(v) => patch(idx, { background_radius: coerceInt(v) })"
            />
          </div>
          <div class="row q-col-gutter-md">
            <q-input
              outlined dark dense class="col"
              type="number"
              :model-value="el.stroke_width ?? 0"
              :label="$t('overlayElements.fields.strokeWidth')"
              :disable="disabled"
              @update:model-value="(v) => patch(idx, { stroke_width: coerceInt(v) })"
            />
            <div class="col">
              <ColorField
                :model-value="el.stroke_color"
                :label="$t('overlayElements.fields.strokeColor')"
                clearable
                :disable="disabled || !(el.stroke_width > 0)"
                @update:model-value="(v) => patch(idx, { stroke_color: v })"
              />
            </div>
          </div>
        </template>

        <!-- Image-specific fields -->
        <template v-if="el.type === 'image'">
          <q-input
            outlined dark dense
            :model-value="el.src"
            :label="$t('overlayElements.fields.src')"
            :hint="$t('overlayElements.srcHint')"
            :disable="disabled"
            :rules="[(v) => !!v || $t('common.required')]"
            @update:model-value="(v) => patch(idx, { src: v })"
          />
          <div class="row q-col-gutter-md">
            <q-input
              outlined dark dense class="col"
              type="number"
              :model-value="el.width ?? null"
              :label="$t('overlayElements.fields.width')"
              :hint="$t('overlayElements.fields.dimensionHint')"
              :disable="disabled"
              @update:model-value="(v) => patch(idx, { width: coerceInt(v) })"
            />
            <q-input
              outlined dark dense class="col"
              type="number"
              :model-value="el.height ?? null"
              :label="$t('overlayElements.fields.height')"
              :hint="$t('overlayElements.fields.dimensionHint')"
              :disable="disabled"
              @update:model-value="(v) => patch(idx, { height: coerceInt(v) })"
            />
            <q-input
              outlined dark dense class="col"
              type="number" step="0.05" min="0" max="1"
              :model-value="el.opacity ?? 1"
              :label="$t('overlayElements.fields.opacity')"
              :disable="disabled"
              @update:model-value="(v) => patch(idx, { opacity: coerceFloat(v) })"
            />
          </div>
        </template>

        <!-- Shared: position + padding -->
        <q-separator dark spaced />
        <div class="text-caption text-grey-6 q-mb-sm">
          {{ $t('overlayElements.fields.position') }}
        </div>
        <div class="row q-col-gutter-md">
          <PositionField
            class="col"
            axis="x"
            :model-value="el.x"
            :label="$t('overlayElements.fields.x')"
            :disable="disabled"
            @update:model-value="(v) => patch(idx, { x: v })"
          />
          <PositionField
            class="col"
            axis="y"
            :model-value="el.y"
            :label="$t('overlayElements.fields.y')"
            :disable="disabled"
            @update:model-value="(v) => patch(idx, { y: v })"
          />
          <q-input
            outlined dark dense class="col"
            type="number"
            :model-value="el.padding ?? 0"
            :label="$t('overlayElements.fields.padding')"
            :hint="$t('overlayElements.paddingHint')"
            :disable="disabled"
            @update:model-value="(v) => patch(idx, { padding: coerceInt(v) })"
          />
        </div>
      </q-card-section>
    </q-card>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import ColorField from 'src/components/ColorField.vue'
import PositionField from 'src/components/PositionField.vue'

const props = defineProps({
  modelValue: { type: Array, default: () => [] },
  disabled: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue'])

const elements = computed(() => props.modelValue || [])

let uidSeq = 0
const uids = new WeakMap()
function uidFor(el) {
  if (!el || typeof el !== 'object') return `el-${String(el)}`
  if (!uids.has(el)) uids.set(el, ++uidSeq)
  return uids.get(el)
}

function emitElements(list) {
  emit('update:modelValue', list)
}

function addElement(type) {
  if (type === 'text') {
    emitElements([
      ...elements.value,
      {
        type: 'text',
        text: '4K',
        x: 'right', y: 'top',
        padding: 16, font_size: 44,
        color: '#ffffff', background: '#000000bb',
        background_radius: 8,
      },
    ])
  } else {
    emitElements([
      ...elements.value,
      {
        type: 'image',
        src: '',
        x: 'left', y: 'bottom',
        padding: 16, width: 120, opacity: 1.0,
      },
    ])
  }
}

function patch(idx, partial) {
  const next = [...elements.value]
  next[idx] = { ...next[idx], ...partial }
  uids.set(next[idx], uidFor(elements.value[idx]))
  // Strip explicit undefined so the payload stays compact.
  for (const k of Object.keys(partial)) {
    if (next[idx][k] === undefined || next[idx][k] === null || next[idx][k] === '') {
      delete next[idx][k]
    }
  }
  emitElements(next)
}

function removeAt(idx) {
  const next = [...elements.value]
  next.splice(idx, 1)
  emitElements(next)
}

function moveUp(idx) {
  if (idx === 0) return
  const next = [...elements.value]
  ;[next[idx - 1], next[idx]] = [next[idx], next[idx - 1]]
  emitElements(next)
}

function moveDown(idx) {
  if (idx >= elements.value.length - 1) return
  const next = [...elements.value]
  ;[next[idx], next[idx + 1]] = [next[idx + 1], next[idx]]
  emitElements(next)
}

function duplicate(idx) {
  const next = [...elements.value]
  next.splice(idx + 1, 0, JSON.parse(JSON.stringify(next[idx])))
  emitElements(next)
}

function coerceInt(v) {
  if (v === null || v === undefined || v === '') return null
  const n = Number(v)
  return Number.isFinite(n) ? Math.trunc(n) : null
}
function coerceFloat(v) {
  if (v === null || v === undefined || v === '') return null
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}
</script>

<style scoped>
.element-card {
  border-left: 3px solid transparent;
}
.element-card.element-text { border-left-color: var(--q-primary, #5fa3ff); }
.element-card.element-image { border-left-color: var(--q-secondary, #ffa05f); }
</style>
