<template>
  <q-menu anchor="top middle" self="bottom middle" :offset="[0, 8]">
    <q-list style="min-width: 200px">
      <q-item-label header>{{ header }}</q-item-label>

      <!-- Optional "off"/null item (e.g. for subtitles) -->
      <q-item
        v-if="hasNullOption"
        clickable
        v-close-popup
        @click="$emit('select', null)"
        :active="modelValue === null"
      >
        <q-item-section>
          <q-item-label>{{ nullOptionLabel }}</q-item-label>
        </q-item-section>
        <q-item-section side v-if="modelValue === null">
          <q-icon name="mdi-check" color="primary" />
        </q-item-section>
      </q-item>

      <!-- Items -->
      <q-item
        v-for="(item, index) in items"
        :key="index"
        clickable
        v-close-popup
        @click="$emit('select', index)"
        :active="modelValue === index"
        :disable="itemDisabled ? itemDisabled(item) : false"
      >
        <q-item-section>
          <slot name="item" :item="item" :index="index">
            <q-item-label>{{ item.label || `${defaultItemPrefix} ${index + 1}` }}</q-item-label>
            <q-item-label caption v-if="item.language">{{ item.language }}</q-item-label>
          </slot>
        </q-item-section>
        <q-item-section side v-if="modelValue === index">
          <q-icon name="mdi-check" color="primary" />
        </q-item-section>
      </q-item>

      <!-- Empty state -->
      <q-item v-if="items.length === 0">
        <q-item-section>
          <q-item-label caption>{{ emptyLabel }}</q-item-label>
        </q-item-section>
      </q-item>
    </q-list>
  </q-menu>
</template>

<script setup>
defineProps({
  header: { type: String, required: true },
  items: { type: Array, default: () => [] },
  modelValue: { type: [Number, null], default: null },
  emptyLabel: { type: String, default: '' },
  defaultItemPrefix: { type: String, default: 'Item' },
  hasNullOption: { type: Boolean, default: false },
  nullOptionLabel: { type: String, default: '' },
  itemDisabled: { type: Function, default: null },
})

defineEmits(['select'])
</script>
