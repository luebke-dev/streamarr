import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'
import { logger } from 'src/utils/logger'
import { formatAirDate } from 'src/composables/useMediaFormatters'

/**
 * Billing-history composable for the membership page.
 *
 * Owns:
 *  - reactive `billingHistory` rows fetched from
 *    ``GET /api/subscriptions/invoices`` (Stripe invoices). Empty when
 *    payments are disabled or the user has no billing yet.
 *  - localized `billingColumns` definition for the q-table
 *  - `loading` ref for initial fetch
 *  - `downloadingInvoiceId` state and `downloadInvoice(invoiceId)` action
 *    that opens the Stripe-hosted ``invoice_pdf`` URL in a new tab.
 *  - `refresh()` so the page can re-pull after a plan change.
 *  - shared `formatDate` helper bound to the active i18n locale
 *
 * Errors surface via Quasar Notify and are logged.
 */
export function useBillingHistory() {
  const { t, locale: i18nLocale } = useI18n()
  const $q = useQuasar()

  const billingHistory = ref([])
  const loading = ref(false)
  const downloadingInvoiceId = ref(null)

  const formatDate = (date) => formatAirDate(date, i18nLocale.value)

  const billingColumns = [
    {
      name: 'date',
      required: true,
      label: t('membership.billing.date'),
      align: 'left',
      field: 'date',
      format: (val) => formatDate(val),
      sortable: true,
    },
    {
      name: 'plan',
      align: 'left',
      label: t('membership.billing.plan'),
      field: 'plan',
      sortable: true,
    },
    {
      name: 'amount',
      align: 'left',
      label: t('membership.billing.amount'),
      field: 'amount',
      sortable: true,
    },
    {
      name: 'status',
      align: 'center',
      label: t('membership.billing.status'),
      field: 'status',
      sortable: true,
    },
    {
      name: 'actions',
      align: 'center',
      label: t('membership.billing.actions'),
      field: 'actions',
    },
  ]

  /**
   * Convert a Stripe invoice (cents-aware Decimal serialised as string by
   * the backend, plus a unix timestamp) to the row shape the q-table expects.
   */
  function mapInvoice(invoice) {
    const amount = Number(invoice.amount_paid ?? invoice.amount_due ?? 0)
    return {
      id: invoice.id,
      date: invoice.created ? new Date(invoice.created * 1000) : null,
      plan: '',
      amount: `${amount.toFixed(2)} ${(invoice.currency || '').toUpperCase()}`,
      status: invoice.status || 'unknown',
      invoicePdf: invoice.invoice_pdf || null,
    }
  }

  async function refresh() {
    try {
      loading.value = true
      const { data } = await api.get('/api/subscriptions/invoices')
      billingHistory.value = Array.isArray(data) ? data.map(mapInvoice) : []
    } catch (err) {
      // 402/501 = Stripe not configured — that's not user-facing noise.
      const status = err?.response?.status
      if (status === 402 || status === 501) {
        billingHistory.value = []
      } else {
        logger.error('Failed to load billing history:', err)
        $q.notify({ type: 'negative', message: t('membership.billingLoadError') })
      }
    } finally {
      loading.value = false
    }
  }

  async function downloadInvoice(invoiceId) {
    const row = billingHistory.value.find((r) => r.id === invoiceId)
    if (!row?.invoicePdf) {
      $q.notify({ type: 'warning', message: t('membership.invoiceUnavailable') })
      return
    }
    try {
      downloadingInvoiceId.value = invoiceId
      window.open(row.invoicePdf, '_blank', 'noopener,noreferrer')
    } catch (err) {
      logger.error('Failed to open invoice PDF:', err)
      $q.notify({ type: 'negative', message: t('membership.downloadError') })
    } finally {
      downloadingInvoiceId.value = null
    }
  }

  return {
    billingHistory,
    billingColumns,
    loading,
    downloadingInvoiceId,
    downloadInvoice,
    refresh,
    formatDate,
  }
}
