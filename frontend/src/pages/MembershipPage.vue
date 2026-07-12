<template>
  <q-page class="q-pa-md membership-page">
    <div class="membership-container">
      <!-- Header -->
      <div class="row items-center q-mb-lg">
        <div class="col">
          <div class="text-h4 text-weight-bold">
            <q-icon name="mdi-crown" class="q-mr-sm" />
            {{ $t('membership.title') }}
          </div>
          <div class="text-subtitle1 text-grey-6 q-mt-xs">
            {{ $t('membership.subtitle') }}
          </div>
        </div>
      </div>

      <!-- Current Plan Card -->
      <q-card v-if="currentPlan" flat bordered class="q-mb-lg">
        <q-card-section>
          <div class="row items-center q-mb-md">
            <div class="text-h6">
              <q-icon name="mdi-account-star" class="q-mr-sm" />
              {{ $t('membership.currentPlan') }}
            </div>
            <q-space />
            <q-chip
              :color="currentPlan.status === 'active' ? 'positive' : 'warning'"
              text-color="white"
              :label="$t(`membership.status.${currentPlan.status}`)"
              dense
            />
          </div>

          <div class="row q-col-gutter-md">
            <div class="col-12 col-md-6">
              <div class="text-h5 text-weight-medium q-mb-xs">{{ currentPlan.name }}</div>
              <div class="text-subtitle1 text-primary q-mb-sm">
                {{ currentPlan.price }}/{{ $t('membership.month') }}
              </div>
              <div class="text-body2 text-grey-5">{{ currentPlan.description }}</div>
            </div>
            <div class="col-12 col-md-6">
              <div class="text-subtitle2 q-mb-sm">{{ $t('membership.features') }}</div>
              <q-list dense>
                <q-item v-for="feature in currentPlan.features" :key="feature" class="q-px-none">
                  <q-item-section avatar>
                    <q-icon name="mdi-check" color="positive" size="sm" />
                  </q-item-section>
                  <q-item-section>{{ feature }}</q-item-section>
                </q-item>
              </q-list>
            </div>
          </div>
        </q-card-section>

        <q-separator dark />

        <q-card-section>
          <div class="row items-center q-col-gutter-md">
            <div class="col-12 col-md">
              <div class="text-body2 text-grey-5">
                <q-icon name="mdi-calendar-clock" class="q-mr-xs" />
                {{ $t('membership.nextBilling') }}:
                {{ currentPlan.nextBilling ? formatDate(currentPlan.nextBilling) : '—' }}
              </div>
              <div v-if="currentPlan.status === 'expiring'" class="text-warning q-mt-xs">
                <q-icon name="mdi-alert" class="q-mr-xs" />
                {{ $t('membership.expiringWarning') }}
              </div>
            </div>
            <div class="col-12 col-md-auto">
              <q-btn
                v-if="currentPlan.status === 'expiring'"
                color="primary"
                unelevated
                no-caps
                :label="$t('membership.renewNow')"
                :loading="renewing"
                :disable="renewing"
                @click="renewCurrentPlan"
              />
              <q-btn
                v-if="currentPlan.status === 'active'"
                color="negative"
                outline
                no-caps
                :label="$t('membership.cancelSubscription')"
                @click="showCancelDialog = true"
              />
            </div>
          </div>
        </q-card-section>
      </q-card>

      <!-- No active subscription -->
      <q-banner v-else-if="!plansLoading" class="bg-grey-9 text-white q-mb-lg" rounded>
        <template v-slot:avatar>
          <q-icon name="mdi-information" />
        </template>
        {{ $t('membership.noActivePlan') }}
      </q-banner>

      <!-- Voucher Redemption -->
      <q-card flat bordered class="q-mb-lg">
        <q-card-section>
          <div class="text-h6 q-mb-xs">
            <q-icon name="mdi-ticket-percent" class="q-mr-sm" />
            {{ $t('voucher.sectionTitle') }}
          </div>
          <div class="text-subtitle2 text-grey-6 q-mb-md">{{ $t('voucher.sectionSubtitle') }}</div>
          <div class="row q-col-gutter-md items-start">
            <div class="col-12 col-md">
              <q-input
                v-model="voucherCode"
                outlined
                dark
                dense
                :label="$t('voucher.codeLabel')"
                :placeholder="$t('voucher.codePlaceholder')"
                :disable="redeemingVoucher"
                @keyup.enter="redeemVoucher"
              >
                <template v-slot:prepend>
                  <q-icon name="mdi-ticket-confirmation" />
                </template>
              </q-input>
            </div>
            <div class="col-12 col-md-auto">
              <q-btn
                color="primary"
                unelevated
                no-caps
                :label="$t('voucher.redeem')"
                :loading="redeemingVoucher"
                :disable="!voucherCode || redeemingVoucher"
                @click="redeemVoucher"
              />
            </div>
          </div>
        </q-card-section>
      </q-card>

      <!-- Available Plans -->
      <div class="q-mb-md">
        <div class="text-h6">{{ $t('membership.availablePlans') }}</div>
        <div class="text-subtitle2 text-grey-6">{{ $t('membership.upgradeSubtitle') }}</div>
      </div>

      <div class="row q-col-gutter-md q-mb-lg">
        <div v-for="plan in availablePlans" :key="plan.id" class="col-12 col-sm-6 col-md-3">
          <q-card
            flat
            bordered
            class="plan-card full-height column"
            :class="{
              'plan-card--popular': plan.popular,
              'plan-card--current': plan.id === currentPlan?.id,
            }"
          >
            <q-badge
              v-if="plan.popular"
              color="primary"
              floating
              :label="$t('membership.mostPopular')"
              class="plan-badge"
            />

            <q-card-section class="col">
              <div class="text-h6 text-weight-bold q-mb-sm">{{ plan.name }}</div>
              <div class="row items-baseline q-mb-sm">
                <span class="text-h4 text-weight-bold">{{ plan.price }}</span>
                <span class="text-grey-6 q-ml-xs">/{{ $t('membership.month') }}</span>
              </div>
              <div class="text-body2 text-grey-5 q-mb-md">{{ plan.description }}</div>

              <q-list dense>
                <q-item v-for="feature in plan.features" :key="feature" class="q-px-none">
                  <q-item-section avatar>
                    <q-icon name="mdi-check-circle" color="positive" size="xs" />
                  </q-item-section>
                  <q-item-section>{{ feature }}</q-item-section>
                </q-item>
              </q-list>
            </q-card-section>

            <q-card-actions class="q-pa-md">
              <q-btn
                v-if="plan.id === currentPlan?.id"
                color="grey-7"
                outline
                no-caps
                disable
                class="full-width"
                :label="$t('membership.currentPlan')"
              />
              <q-btn
                v-else-if="!currentPlan"
                color="primary"
                unelevated
                no-caps
                class="full-width"
                :label="$t('membership.subscribe')"
                :loading="selectedPlan?.id === plan.id && changingPlan"
                :disable="changingPlan"
                @click="selectPlan(plan)"
              />
              <q-btn
                v-else-if="plan.priceCents > currentPlan.priceCents"
                color="primary"
                unelevated
                no-caps
                class="full-width"
                :label="$t('membership.upgrade')"
                :loading="selectedPlan?.id === plan.id && changingPlan"
                :disable="changingPlan"
                @click="selectPlan(plan)"
              />
              <q-btn
                v-else
                color="secondary"
                outline
                no-caps
                class="full-width"
                :label="$t('membership.downgrade')"
                :loading="selectedPlan?.id === plan.id && changingPlan"
                :disable="changingPlan"
                @click="selectPlan(plan)"
              />
            </q-card-actions>
          </q-card>
        </div>
      </div>

      <!-- Payment Method -->
      <q-card flat bordered class="q-mb-lg">
        <q-card-section>
          <div class="text-h6 q-mb-md">
            <q-icon name="mdi-credit-card-outline" class="q-mr-sm" />
            {{ $t('membership.paymentMethod') }}
          </div>
          <div class="row items-center q-col-gutter-md">
            <template v-if="paymentMethod">
              <div class="col-auto">
                <q-icon :name="getCardIcon(paymentMethod.type)" size="lg" color="primary" />
              </div>
              <div class="col">
                <div class="text-body1 text-weight-medium">
                  **** **** **** {{ paymentMethod.lastFour }}
                </div>
                <div class="text-body2 text-grey-6">
                  {{ $t('membership.expires') }} {{ paymentMethod.expiry }}
                </div>
              </div>
              <div class="col-auto">
                <q-btn
                  flat
                  color="primary"
                  no-caps
                  :label="$t('membership.updatePayment')"
                  @click="showPaymentDialog = true"
                />
              </div>
            </template>
            <template v-else>
              <div class="col text-grey-6">{{ $t('membership.noPaymentMethod') }}</div>
              <div class="col-auto">
                <q-btn
                  unelevated
                  color="primary"
                  no-caps
                  :label="$t('membership.addPaymentMethod')"
                  @click="showPaymentDialog = true"
                />
              </div>
            </template>
          </div>
        </q-card-section>
      </q-card>

      <!-- Billing History -->
      <q-card flat bordered>
        <q-card-section>
          <div class="text-h6 q-mb-md">
            <q-icon name="mdi-receipt-text-outline" class="q-mr-sm" />
            {{ $t('membership.billingHistory') }}
          </div>
          <q-table
            :rows="billingHistory"
            :columns="billingColumns"
            row-key="id"
            flat
            :pagination="{ rowsPerPage: 20 }"
            :no-data-label="$t('membership.noBillingHistory')"
          >
            <template v-slot:body-cell-status="props">
              <q-td :props="props">
                <q-chip
                  :color="props.value === 'paid' ? 'positive' : 'negative'"
                  text-color="white"
                  :label="$t(`membership.billing.${props.value}`)"
                  size="sm"
                  dense
                />
              </q-td>
            </template>
            <template v-slot:body-cell-actions="props">
              <q-td :props="props">
                <q-btn
                  flat
                  dense
                  color="primary"
                  icon="mdi-download"
                  no-caps
                  :label="$t('membership.downloadInvoice')"
                  size="sm"
                  :loading="downloadingInvoiceId === props.row.id"
                  :disable="downloadingInvoiceId !== null"
                  @click="downloadInvoice(props.row.id)"
                />
              </q-td>
            </template>
          </q-table>
        </q-card-section>
      </q-card>
    </div>

    <!-- Dialogs -->
    <PaymentMethodDialog
      v-model="showPaymentDialog"
      @success="updatePaymentMethod"
    />

    <PlanChangeDialog
      v-model="showPlanDialog"
      :current-plan="currentPlan"
      :new-plan="selectedPlan"
      :loading="changingPlan"
      @confirm="confirmPlanChange"
    />

    <CancelSubscriptionDialog
      v-model="showCancelDialog"
      :next-billing-label="currentPlan?.nextBilling ? formatDate(currentPlan.nextBilling) : ''"
      :loading="cancelling"
      @confirm="confirmCancelSubscription"
    />
  </q-page>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useQuasar } from 'quasar'
import { useSettingsStore } from 'src/stores/settings'
import { logger } from 'src/utils/logger'
import { useBillingHistory } from 'src/composables/useBillingHistory'
import { usePlanManagement } from 'src/composables/usePlanManagement'
import PaymentMethodDialog from 'src/components/membership/PaymentMethodDialog.vue'
import PlanChangeDialog from 'src/components/membership/PlanChangeDialog.vue'
import CancelSubscriptionDialog from 'src/components/membership/CancelSubscriptionDialog.vue'
import { redeemVoucher as redeemVoucherRequest } from 'src/services/membershipUserService'

defineOptions({ name: 'MembershipPage' })

const router = useRouter()
const { t } = useI18n()
const $q = useQuasar()
const settingsStore = useSettingsStore()

const {
  billingHistory,
  billingColumns,
  downloadingInvoiceId,
  downloadInvoice,
  refresh: refreshBilling,
  formatDate,
} = useBillingHistory()

const {
  currentPlan,
  availablePlans,
  paymentMethod,
  selectedPlan,
  showPaymentDialog,
  showPlanDialog,
  showCancelDialog,
  loading: plansLoading,
  renewing,
  changingPlan,
  cancelling,
  getCardIcon,
  refresh: refreshPlans,
  renewCurrentPlan,
  selectPlan,
  confirmPlanChange,
  updatePaymentMethod,
  confirmCancelSubscription,
} = usePlanManagement()

// Voucher redemption
const voucherCode = ref('')
const redeemingVoucher = ref(false)

async function redeemVoucher() {
  const code = voucherCode.value.trim()
  if (!code) return
  redeemingVoucher.value = true
  try {
    const res = await redeemVoucherRequest(code)
    voucherCode.value = ''
    const extended = res?.extended
    $q.notify({
      type: 'positive',
      message: t(extended ? 'voucher.redeemSuccessExtend' : 'voucher.redeemSuccessNew'),
    })
    await refreshPlans()
  } catch (err) {
    logger.error('Failed to redeem voucher:', err)
    const status = err?.response?.status
    const detail = err?.response?.data?.detail
    let msgKey = 'voucher.errorGeneric'
    if (status === 404) msgKey = 'voucher.errorNotFound'
    else if (status === 409) msgKey = 'voucher.errorConflict'
    else if (status === 400 && typeof detail === 'string') {
      const d = detail.toLowerCase()
      if (d.includes('inactive')) msgKey = 'voucher.errorInactive'
      else if (d.includes('exhaust')) msgKey = 'voucher.errorExhausted'
      else if (d.includes('expir')) msgKey = 'voucher.errorExpired'
    }
    $q.notify({ type: 'negative', message: t(msgKey) })
  } finally {
    redeemingVoucher.value = false
  }
}

onMounted(async () => {
  // Check if subscriptions are enabled
  if (!settingsStore.subscriptionsLoaded) {
    await settingsStore.fetchSubscriptionSettings()
  }
  if (!settingsStore.isSubscriptionsEnabled) {
    router.push('/')
    return
  }
  logger.debug('MembershipPage mounted')
  await Promise.all([refreshPlans(), refreshBilling()])
})
</script>

<style lang="scss" scoped>
.membership-container {
  max-width: 1200px;
  margin: 0 auto;
}

.plan-card {
  position: relative;
  transition:
    border-color 0.2s ease,
    transform 0.2s ease;

  &:hover {
    transform: translateY(-2px);
  }

  &--popular {
    border-color: var(--q-primary);
  }

  &--current {
    border-color: var(--q-positive);
  }

  .plan-badge {
    top: 12px;
    right: 12px;
  }
}
</style>
