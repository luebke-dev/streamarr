<template>
  <div class="row items-center q-gutter-sm">
    <div class="col-2 text-caption text-bold" style="min-width: 90px">
      {{ label }}
    </div>
    <q-slider
      :model-value="modelValue"
      :min="0"
      :max="50"
      :step="1"
      label
      color="primary"
      class="col"
      @update:model-value="$emit('update:modelValue', $event)"
    />
    <q-input
      :model-value="modelValue"
      type="number"
      dense
      outlined
      :min="0"
      :max="50"
      style="width: 70px"
      @update:model-value="$emit('update:modelValue', Number($event))"
    />
    <div class="text-caption text-grey-5" style="min-width: 30px">pts</div>
  </div>
</template>

<script setup>
defineProps({
  label: {
    type: String,
    required: true,
  },
  modelValue: {
    type: Number,
    default: 0,
  },
})

defineEmits(['update:modelValue'])
</script>
