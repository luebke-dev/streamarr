import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'
import { logger } from 'src/utils/logger'

/**
 * Plan-management composable for the membership page.
 *
 * Owns the data and actions surrounding the user's current subscription:
 *
 *  - `currentPlan`, `availablePlans`, `paymentMethod` reactive state hydrated
 *    from the backend via:
 *      * GET /api/subscriptions/packages         (list of plans)
 *      * GET /api/subscriptions/my-subscription  (active sub or null)
 *      * GET /api/subscriptions/payment-methods  (saved cards)
 *      * GET /api/groups/{id}                    (per-package permissions
 *                                                  for the feature list)
 *  - dialog visibility refs (`showPlanDialog`, `showPaymentDialog`,
 *    `showCancelDialog`) and the matching loading flags
 *  - `selectPlan(plan)` / `confirmPlanChange()` upgrade/downgrade flow
 *    (cancel current + subscribe to the new package)
 *  - `renewCurrentPlan()` re-subscribes to the same package
 *  - `updatePaymentMethod(payload)` for the payment dialog (Stripe success)
 *  - `confirmCancelSubscription()` POST /api/subscriptions/cancel
 *  - `refresh()` re-pulls the full state
 *  - small helpers (`getCardIcon`, `getFeaturesFromGroup`)
 *
 * Errors surface via Quasar Notify with localized messages, replacing the
 * silent catches that used to live in MembershipPage.
 */
export function usePlanManagement() {
  const { t } = useI18n()
  const $q = useQuasar()

  // --- Helpers ---------------------------------------------------------
  const getCardIcon = (type) => (type === 'paypal' ? 'account_balance_wallet' : 'credit_card')

  /**
   * Build a localized feature bullet list from a Group's permission flags.
   * The mapping intentionally hides defaults (e.g. ``true`` for ``allow_play``)
   * to keep the card concise.
   */
  function getFeaturesFromGroup(group) {
    if (!group) return []
    const out = []
    const libs = Array.isArray(group.allowed_libraries) ? group.allowed_libraries.length : 0
    if (libs > 0) {
      out.push(t('membership.featureLibraries', { count: libs }))
    }
    if (group.max_concurrent_streams > 0) {
      out.push(
        t('membership.featureScreens', { count: group.max_concurrent_streams }),
      )
    }
    if (group.max_video_quality) {
      out.push(
        t('membership.featureVideoQuality', {
          quality: group.max_video_quality.toUpperCase(),
        }),
      )
    }
    if (group.max_audio_quality) {
      out.push(
        t(`membership.featureAudio_${group.max_audio_quality}`),
      )
    }
    if (group.allow_downloads) {
      out.push(t('membership.featureDownloads'))
    }
    return out
  }

  function formatPrice(priceCents, currency) {
    const amount = (priceCents || 0) / 100
    return `${amount.toFixed(2)} ${(currency || 'EUR').toUpperCase()}`
  }

  function mapPaymentMethod(method) {
    if (!method?.card) return null
    return {
      type: method.card.brand,
      lastFour: method.card.last4,
      expiry: `${String(method.card.exp_month).padStart(2, '0')}/${String(method.card.exp_year).slice(-2)}`,
    }
  }

  // --- Reactive state --------------------------------------------------
  const showPaymentDialog = ref(false)
  const showPlanDialog = ref(false)
  const showCancelDialog = ref(false)
  const selectedPlan = ref(null)
  const renewing = ref(false)
  const changingPlan = ref(false)
  const updatingPayment = ref(false)
  const cancelling = ref(false)
  const loading = ref(false)

  /** Active subscription's package, ``null`` when the user has no plan. */
  const currentPlan = ref(null)

  /** All purchasable packages, hydrated from the backend. */
  const availablePlans = ref([])

  /** Default Stripe payment method, ``null`` when none is on file. */
  const paymentMethod = ref(null)

  // --- API actions -----------------------------------------------------
  function notifyError(messageKey, err) {
    logger.error(`[membership] ${messageKey}:`, err)
    $q.notify({ type: 'negative', message: t(messageKey) })
  }

  /**
   * Resolve a Group payload by id with single-flight caching for the duration
   * of one ``refresh()``.
   */
  async function fetchGroup(cache, groupId) {
    if (!groupId) return null
    if (cache.has(groupId)) return cache.get(groupId)
    const promise = api
      .get(`/api/groups/${groupId}`)
      .then((r) => r.data)
      .catch((err) => {
        logger.warn(`Failed to fetch group ${groupId}:`, err)
        return null
      })
    cache.set(groupId, promise)
    return promise
  }

  function buildPlan(pkg, group) {
    return {
      id: pkg.guid,
      name: pkg.name,
      description: pkg.description || '',
      price: formatPrice(pkg.price_cents, pkg.currency),
      priceCents: pkg.price_cents,
      currency: pkg.currency,
      groupId: pkg.group_id,
      // Mock-era field, kept so the page can keep ``plan.popular`` styling
      // until/unless we expose a real flag from the backend.
      popular: false,
      features: getFeaturesFromGroup(group),
    }
  }

  async function refresh() {
    loading.value = true
    try {
      const [packagesRes, subRes, methodsRes] = await Promise.all([
        api.get('/api/subscriptions/packages', { params: { active_only: true } }),
        api.get('/api/subscriptions/my-subscription'),
        api
          .get('/api/subscriptions/payment-methods')
          .catch((err) => {
            // Stripe disabled is fine — just means no saved cards.
            if ([402, 501, 503].includes(err?.response?.status)) return { data: [] }
            throw err
          }),
      ])

      const packages = Array.isArray(packagesRes.data) ? packagesRes.data : []
      const groupCache = new Map()
      const groups = await Promise.all(packages.map((p) => fetchGroup(groupCache, p.group_id)))
      availablePlans.value = packages.map((p, i) => buildPlan(p, groups[i]))

      const sub = subRes.data
      if (sub) {
        const pkg = packages.find((p) => p.guid === sub.package_id)
        const group = pkg ? await fetchGroup(groupCache, pkg.group_id) : null
        currentPlan.value = pkg
          ? {
              ...buildPlan(pkg, group),
              status: sub.status === 'cancelled' ? 'expiring' : sub.status,
              nextBilling: sub.expires_at ? new Date(sub.expires_at) : null,
              subscriptionId: sub.guid,
              activeSessions: sub.active_sessions ?? 0,
              canStartSession: sub.can_start_session ?? true,
            }
          : null
      } else {
        currentPlan.value = null
      }

      const methods = Array.isArray(methodsRes.data) ? methodsRes.data : []
      const defaultMethod = methods.find((m) => m.is_default) || methods[0] || null
      paymentMethod.value = mapPaymentMethod(defaultMethod)
    } catch (err) {
      notifyError('membership.loadingError', err)
    } finally {
      loading.value = false
    }
  }

  /** Subscribe to a package; resolves with the new subscription or throws. */
  async function subscribe(packageId) {
    const { data } = await api.post('/api/subscriptions/subscribe', {
      package_id: packageId,
    })
    return data
  }

  /** Cancel the active subscription; safe to call when nothing is active. */
  async function cancelActive() {
    try {
      await api.post('/api/subscriptions/cancel')
    } catch (err) {
      // 404 = no active sub, that's fine for the change-plan flow.
      if (err?.response?.status !== 404) throw err
    }
  }

  async function renewCurrentPlan() {
    if (!currentPlan.value?.id) return
    try {
      renewing.value = true
      await subscribe(currentPlan.value.id)
      await refresh()
    } catch (err) {
      notifyError('membership.renewalError', err)
    } finally {
      renewing.value = false
    }
  }

  function selectPlan(plan) {
    selectedPlan.value = plan
    showPlanDialog.value = true
  }

  async function confirmPlanChange() {
    if (!selectedPlan.value?.id) return
    try {
      changingPlan.value = true
      // Plan change = cancel existing + subscribe to new (no dedicated
      // change-plan endpoint exists yet on the backend).
      if (currentPlan.value) await cancelActive()
      await subscribe(selectedPlan.value.id)
      await refresh()
      showPlanDialog.value = false
      selectedPlan.value = null
    } catch (err) {
      notifyError('membership.planChangeError', err)
    } finally {
      changingPlan.value = false
    }
  }

  async function updatePaymentMethod(payload) {
    // Stripe Card Element confirmed the SetupIntent in the dialog and emitted
    // ``{ paymentMethodId }``. We re-fetch the saved payment methods so the
    // UI shows the freshly-attached card.
    try {
      updatingPayment.value = true
      if (payload?.paymentMethodId) {
        const { data } = await api.get('/api/subscriptions/payment-methods')
        const methods = Array.isArray(data) ? data : []
        const fresh =
          methods.find((m) => m.id === payload.paymentMethodId) ||
          methods.find((m) => m.is_default) ||
          methods[0]
        const mapped = mapPaymentMethod(fresh)
        if (mapped) paymentMethod.value = mapped
      }
      showPaymentDialog.value = false
    } catch (err) {
      notifyError('membership.paymentUpdateError', err)
    } finally {
      updatingPayment.value = false
    }
  }

  async function confirmCancelSubscription() {
    try {
      cancelling.value = true
      await cancelActive()
      await refresh()
      showCancelDialog.value = false
    } catch (err) {
      notifyError('membership.cancellationError', err)
    } finally {
      cancelling.value = false
    }
  }

  return {
    // state
    currentPlan,
    availablePlans,
    paymentMethod,
    selectedPlan,
    showPaymentDialog,
    showPlanDialog,
    showCancelDialog,
    loading,
    renewing,
    changingPlan,
    updatingPayment,
    cancelling,
    // helpers
    getCardIcon,
    // actions
    refresh,
    renewCurrentPlan,
    selectPlan,
    confirmPlanChange,
    updatePaymentMethod,
    confirmCancelSubscription,
  }
}
