<template>
  <q-dialog
    :model-value="modelValue"
    persistent
    @update:model-value="$emit('update:modelValue', $event)"
  >
    <q-card dark>
      <q-card-section class="row items-center">
        <q-avatar icon="mdi-alert" color="negative" text-color="white" />
        <span class="q-ml-sm">{{ message }}</span>
      </q-card-section>

      <slot />

      <q-card-actions align="right">
        <q-btn flat :label="$t('common.cancel')" @click="$emit('update:modelValue', false)" />
        <q-btn
          flat
          :label="$t('common.delete')"
          color="negative"
          :loading="loading"
          @click="$emit('confirm')"
        />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup>
defineProps({
  modelValue: {
    type: Boolean,
    required: true,
  },
  message: {
    type: String,
    required: true,
  },
  loading: {
    type: Boolean,
    default: false,
  },
})

defineEmits(['update:modelValue', 'confirm'])
</script>
