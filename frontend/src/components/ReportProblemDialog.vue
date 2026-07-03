<template>
  <q-dialog :model-value="modelValue" @update:model-value="$emit('update:modelValue', $event)">
    <q-card dark style="min-width: 400px">
      <q-card-section>
        <div class="text-h6">{{ $t('player.reportProblem') }}</div>
      </q-card-section>
      <q-card-section>
        <q-option-group v-model="reason" :options="reasonOptions" color="primary" />
        <q-input
          v-if="reason === 'other'"
          v-model="details"
          :label="$t('player.reportDetails')"
          outlined
          dense
          dark
          class="q-mt-md"
        />
      </q-card-section>
      <q-card-actions align="right">
        <q-btn flat :label="$t('common.cancel')" @click="close" />
        <q-btn
          color="negative"
          :label="$t('player.reportSubmit')"
          :loading="submitting"
          @click="submit"
        />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from 'boot/axios'
import { logger } from 'src/utils/logger'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  mediaUuid: { type: String, required: true },
})

const emit = defineEmits(['update:modelValue', 'submitted'])

const { t } = useI18n()

const reason = ref('wrong_content')
const details = ref('')
const submitting = ref(false)

const reasonOptions = computed(() => [
  { label: t('player.reportWrongContent'), value: 'wrong_content' },
  { label: t('player.reportWrongLanguage'), value: 'wrong_language' },
  { label: t('player.reportBadQuality'), value: 'bad_quality' },
  { label: t('player.reportBadAudio'), value: 'bad_audio' },
  { label: t('player.reportBrokenFile'), value: 'broken_file' },
  { label: t('player.reportOther'), value: 'other' },
])

const close = () => emit('update:modelValue', false)

const submit = async () => {
  submitting.value = true
  try {
    await api.post(`/api/play/${props.mediaUuid}/report-problem`, {
      reason: reason.value,
      details: details.value || null,
    })
    emit('update:modelValue', false)
    emit('submitted')
  } catch (error) {
    logger.error('Failed to report problem:', error)
  } finally {
    submitting.value = false
  }
}
</script>
