<template>
  <q-dialog
    :model-value="modelValue"
    persistent
    @update:model-value="emit('update:modelValue', $event)"
  >
    <q-card style="min-width: 420px; max-width: 480px">
      <q-card-section>
        <div class="text-h6">{{ $t('membership.updatePaymentMethod') }}</div>
      </q-card-section>

      <q-card-section class="q-pt-none">
        <!-- Initial loading: setup intent + Stripe.js -->
        <div v-if="initialising" class="text-center q-py-md">
          <q-spinner color="primary" size="2em" />
        </div>

        <!-- Stripe.js disabled / not configured -->
        <q-banner v-else-if="!stripeAvailable" class="bg-warning text-white">
          {{ $t('membership.paymentDisabled') }}
        </q-banner>

        <!-- Setup form -->
        <template v-else>
          <q-input
            v-model="cardholderName"
            :label="$t('membership.cardholderName')"
            outlined
            dense
            class="q-mb-md"
            autocomplete="cc-name"
          />
          <div class="stripe-card-wrapper">
            <div ref="cardElementRef" class="stripe-card-element" />
          </div>
          <div v-if="cardError" class="text-negative text-caption q-mt-sm">
            {{ cardError }}
          </div>
        </template>
      </q-card-section>

      <q-card-actions align="right">
        <q-btn
          flat
          no-caps
          :label="$t('common.cancel')"
          color="grey-7"
          :disable="submitting"
          @click="closeDialog"
        />
        <q-btn
          unelevated
          no-caps
          :label="$t('common.save')"
          color="primary"
          :loading="submitting"
          :disable="submitting || !stripeAvailable || initialising"
          @click="onSubmit"
        />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup>
import { nextTick, ref, watch } from 'vue'
import { api } from 'src/boot/axios'
import { getStripe } from 'src/boot/stripe'
import { logger } from 'src/utils/logger'

const props = defineProps({
  modelValue: { type: Boolean, required: true },
})
const emit = defineEmits(['update:modelValue', 'success', 'error'])

const initialising = ref(false)
const submitting = ref(false)
const stripeAvailable = ref(false)
const cardError = ref('')
const cardholderName = ref('')
const cardElementRef = ref(null)

let stripe = null
let elements = null
let cardElement = null
let clientSecret = null

function resetState() {
  cardError.value = ''
  cardholderName.value = ''
  if (cardElement) {
    try {
      cardElement.unmount()
      cardElement.destroy()
    } catch (err) {
      logger.debug('Stripe card element teardown failed', err)
    }
  }
  stripe = null
  elements = null
  cardElement = null
  clientSecret = null
  stripeAvailable.value = false
}

async function initStripe() {
  initialising.value = true
  try {
    stripe = await getStripe()
    if (!stripe) {
      stripeAvailable.value = false
      return
    }

    const { data } = await api.post('/api/subscriptions/setup-intent')
    clientSecret = data.client_secret

    elements = stripe.elements({ clientSecret })
    stripeAvailable.value = true

    // Wait one tick so the v-if branch is rendered before mounting.
    await nextTick()
    if (!cardElementRef.value) return

    cardElement = elements.create('card', {
      hidePostalCode: false,
      style: {
        base: {
          color: '#ffffff',
          fontFamily: 'Roboto, sans-serif',
          fontSize: '16px',
          '::placeholder': { color: '#9e9e9e' },
        },
        invalid: { color: '#f44336' },
      },
    })
    cardElement.mount(cardElementRef.value)
    cardElement.on('change', (event) => {
      cardError.value = event.error ? event.error.message : ''
    })
  } catch (err) {
    logger.error('Failed to initialise Stripe payment dialog', err)
    stripeAvailable.value = false
    emit('error', err)
  } finally {
    initialising.value = false
  }
}

async function onSubmit() {
  if (!stripe || !cardElement || !clientSecret) return
  submitting.value = true
  cardError.value = ''
  try {
    const { error, setupIntent } = await stripe.confirmCardSetup(clientSecret, {
      payment_method: {
        card: cardElement,
        billing_details: { name: cardholderName.value || undefined },
      },
    })
    if (error) {
      cardError.value = error.message || 'Card confirmation failed'
      return
    }
    emit('success', { paymentMethodId: setupIntent.payment_method })
    emit('update:modelValue', false)
  } catch (err) {
    logger.error('confirmCardSetup threw', err)
    cardError.value = err?.message || 'Unexpected error'
    emit('error', err)
  } finally {
    submitting.value = false
  }
}

function closeDialog() {
  if (submitting.value) return
  emit('update:modelValue', false)
}

watch(
  () => props.modelValue,
  (open) => {
    if (open) {
      void initStripe()
    } else {
      resetState()
    }
  },
)
</script>

<style lang="scss" scoped>
.stripe-card-wrapper {
  padding: 12px 14px;
  border: 1px solid rgba(255, 255, 255, 0.24);
  border-radius: 4px;
  background: rgba(255, 255, 255, 0.04);
}

.stripe-card-element {
  min-height: 22px;
}
</style>
