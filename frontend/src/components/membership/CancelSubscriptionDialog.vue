<template>
  <q-dialog
    :model-value="modelValue"
    persistent
    @update:model-value="emit('update:modelValue', $event)"
  >
    <q-card style="min-width: 450px">
      <q-card-section>
        <div class="text-h6">{{ $t('membership.cancelSubscription') }}</div>
      </q-card-section>

      <q-card-section class="q-pt-none">
        <p>{{ $t('membership.cancelConfirmation') }}</p>
        <p class="text-warning q-mt-md">
          <q-icon name="mdi-alert" color="warning" />
          {{ $t('membership.cancelWarning', { date: nextBillingLabel }) }}
        </p>
      </q-card-section>

      <q-card-actions align="right">
        <q-btn
          flat
          no-caps
          :label="$t('membership.keepSubscription')"
          color="grey-7"
          @click="emit('update:modelValue', false)"
        />
        <q-btn
          unelevated
          no-caps
          :label="$t('membership.confirmCancel')"
          color="negative"
          :loading="loading"
          :disable="loading"
          @click="emit('confirm')"
        />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup>
defineProps({
  modelValue: { type: Boolean, required: true },
  nextBillingLabel: { type: String, required: true },
  loading: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue', 'confirm'])
</script>
