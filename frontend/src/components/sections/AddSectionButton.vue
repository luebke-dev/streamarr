<template>
  <div class="add-section-btn" @click="editor.openAddDialog(orderIndex)">
    <q-icon name="mdi-plus" size="sm" color="grey-5" />
    <span class="text-caption text-grey-5">{{ $t('pageLayouts.addSectionHere') }}</span>
  </div>
</template>

<script setup>
import { useLayoutEditorInject } from 'src/composables/useLayoutEditor'

defineProps({
  orderIndex: { type: Number, required: true },
})

const editor = useLayoutEditorInject()
</script>

<style lang="scss" scoped>
.add-section-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  margin: 8px 16px;
  padding: 12px;
  border: 2px dashed rgba(255, 255, 255, 0.15);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;

  &:hover {
    border-color: rgba(255, 255, 255, 0.3);
    background: rgba(255, 255, 255, 0.05);
  }
}
</style>
