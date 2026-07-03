<template>
  <q-dialog
    :model-value="modelValue"
    persistent
    @update:model-value="emit('update:modelValue', $event)"
  >
    <q-card style="min-width: 500px">
      <q-card-section>
        <div class="text-h6">{{ $t('membership.confirmPlanChange') }}</div>
      </q-card-section>

      <q-card-section class="q-pt-none" v-if="newPlan">
        <p>{{ $t('membership.changePlanConfirmation', { planName: newPlan.name }) }}</p>
        <div class="row items-center q-col-gutter-md plan-comparison q-my-md">
          <div class="col text-center">
            <div class="text-caption text-grey-6 text-uppercase q-mb-xs">
              {{ $t('membership.currentPlan') }}
            </div>
            <div class="text-weight-medium">
              {{ currentPlan.name }} - {{ currentPlan.price }}/{{ $t('membership.month') }}
            </div>
          </div>
          <div class="col-auto">
            <q-icon name="mdi-arrow-right" size="md" color="primary" />
          </div>
          <div class="col text-center">
            <div class="text-caption text-primary text-uppercase q-mb-xs">
              {{ $t('membership.newPlan') }}
            </div>
            <div class="text-weight-medium">
              {{ newPlan.name }} - {{ newPlan.price }}/{{ $t('membership.month') }}
            </div>
          </div>
        </div>
        <p class="text-body2 text-grey-6 text-italic q-mt-md">
          {{ $t('membership.changeEffective') }}
        </p>
      </q-card-section>

      <q-card-actions align="right">
        <q-btn
          flat
          no-caps
          :label="$t('common.cancel')"
          color="grey-7"
          @click="emit('update:modelValue', false)"
        />
        <q-btn
          unelevated
          no-caps
          :label="$t('membership.confirmChange')"
          color="primary"
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
  currentPlan: { type: Object, required: true },
  newPlan: { type: Object, default: null },
  loading: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue', 'confirm'])
</script>

<style lang="scss" scoped>
.plan-comparison {
  background: rgba(255, 255, 255, 0.04);
  border-radius: 8px;
  padding: 16px;
}
</style>
