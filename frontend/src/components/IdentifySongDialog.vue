<template>
  <q-dialog
    :model-value="modelValue"
    @update:model-value="$emit('update:modelValue', $event)"
    position="bottom"
  >
    <q-card dark style="min-width: 300px">
      <q-card-section class="row items-center q-gutter-md">
        <q-icon
          :name="error ? 'mdi-alert-circle' : song ? 'mdi-music-note' : 'mdi-music-off'"
          size="32px"
          :color="error ? 'negative' : song ? 'primary' : 'grey'"
        />
        <div v-if="song">
          <div class="text-weight-bold">{{ song.title }}</div>
          <div class="text-grey">{{ song.artist }}</div>
          <div v-if="song.album" class="text-caption text-grey-6">
            {{ song.album }}
          </div>
        </div>
        <div v-else-if="error" class="text-negative">{{ error }}</div>
        <div v-else class="text-grey">{{ $t('player.noSongMatch') }}</div>
      </q-card-section>
      <q-card-actions align="right">
        <q-btn flat :label="$t('common.close')" color="primary" v-close-popup />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup>
defineProps({
  modelValue: { type: Boolean, default: false },
  song: { type: Object, default: null },
  error: { type: String, default: null },
})

defineEmits(['update:modelValue'])
</script>
